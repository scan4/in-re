"""
推荐引擎编排器 V5 — LLM出分数+理由 → 本地融合重新计算 → 本地排序返回

全链路：
1. user_id 精确查画像 + 行为
2. BGE 语义初筛 (缩减到 30 条)
3. LLM 对初筛结果评分 + 出推荐理由
4. 本地融合: BGE相似度×0.3 + LLM分数×0.4 + 字段完整性×0.15 + 时间衰减×0.15
5. 本地按融合分排序 → 返回本地分 + LLM理由
"""
import math
import json
import hashlib
import asyncio
import logging
from datetime import datetime, timezone

from engine.data_repo import (
    get_user_profile, get_user_behaviors, get_user_click_preferences,
    get_all_candidates, get_field_importance, build_user_vector_text,
    pre_screen_candidates, build_user_context, TYPE_TO_TABLE,
)
from engine.embedding import encode_text_async
from engine.llm_scorer import llm_score_and_rank, LLMError
from engine.circuit_breaker import llm_breaker, CircuitOpenError

logger = logging.getLogger(__name__)

# ═══════ 测试开关 ═══════
DISABLE_LLM = False           # True=跳过LLM，走纯BGE降级模式；False=正常用LLM

TIME_DECAY_CONFIG = {
    "news":     {"half_life_days": 90,  "weight": 0.15},
    "training": {"half_life_days": 60,  "weight": 0.15},
    "skill":    {"half_life_days": 180, "weight": 0.15},
    "course":   {"half_life_days": None, "weight": 0.0},
    "scale":    {"half_life_days": None, "weight": 0.0},
    "career":   {"half_life_days": None, "weight": 0.0},
}


async def run_recommend_v2(
    user_id: str, context_type: str,
    context_text: str, limit: int = 4, content_types: list[str] | None = None,
) -> dict:
    logger.info(f"[V5] 推荐: user={user_id}, types={content_types}")
    if not content_types:
        content_types = ["course", "training", "skill", "scale", "career", "news"]

    # ── 冷启动检测 ──
    profile = await get_user_profile(user_id)
    behaviors = await get_user_behaviors(user_id)
    click_prefs = await get_user_click_preferences(user_id)  # 历史点击偏好 → 评分微调
    
    has_major = bool(profile and profile.get("base_tags", {}).get("major"))
    has_skills = bool(profile and profile.get("base_tags", {}).get("skills"))
    has_behaviors = len(behaviors) > 0
    
    if not has_major and not has_skills and not has_behaviors:
        logger.info(f"[V5] 冷启动: user={user_id}, 无专业/技能/行为记录")
        return await _cold_start_recommend(profile, behaviors, content_types, limit)

    # 用户向量只编码一次，供所有类型复用（同一请求内用户向量固定，避免重复 BGE 编码）
    user_vec_text = build_user_vector_text(profile, behaviors)
    user_vector = await encode_text_async(user_vec_text)

    async def process_type(ct: str):
        try:
            return await _recommend_for_type(user_id, profile, behaviors, click_prefs, context_text, ct, limit, user_vector=user_vector)
        except Exception as e:
            logger.error(f"[V5] {ct} 失败: {e}")
            return {"type": ct, "items": [], "fallback": True}

    results = await asyncio.gather(*[process_type(ct) for ct in content_types])

    all_items = []
    any_fallback = False
    for r in results:
        all_items.extend(r.get("items", []))
        if r.get("fallback"):
            any_fallback = True

    all_items.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    return _build_response(all_items, fallback_used=any_fallback)


async def process_type_stream(user_id: str, context_type: str, context_text: str,
                              limit: int = 4, content_types: list[str] | None = None):
    """流式推荐生成器 — 每完成一个类型就 yield 一个 chunk"""
    content_types = content_types or list(TYPE_TO_TABLE.keys())

    profile = await get_user_profile(user_id)
    behaviors = await get_user_behaviors(user_id)
    click_prefs = await get_user_click_preferences(user_id)

    # 冷启动
    has_major = profile and profile.get("major")
    has_skills = profile and profile.get("skills") and len(profile.get("skills", [])) > 0
    has_behaviors = len(behaviors) > 0
    is_cold = not has_major and not has_skills and not has_behaviors

    if is_cold:
        # 冷启动直接返回全部，不分流
        all_items = []
        for ct in content_types:
            result = await _cold_start_for_type(profile, behaviors, click_prefs, context_text, ct, limit)
            all_items.extend(result.get("items", []))
            yield {"type": result.get("type", ct), "items": result.get("items", []), "fallback": result.get("fallback", True), "done": False}
        yield {"type": "_done", "items": [], "fallback": False, "done": True}
        return

    # 用户向量只编码一次，供所有类型复用
    user_vec_text = build_user_vector_text(profile, behaviors)
    user_vector = await encode_text_async(user_vec_text)

    async def process_and_yield(ct: str):
        try:
            result = await _recommend_for_type(user_id, profile, behaviors, click_prefs, context_text, ct, limit, user_vector=user_vector)
            return result
        except Exception as e:
            logger.error(f"[V5] {ct} 失败: {e}")
            return {"type": ct, "items": [], "fallback": True}

    # asyncio.as_completed: 谁先完成先 yield
    tasks = [process_and_yield(ct) for ct in content_types]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        yield {"type": result.get("type"), "items": result.get("items", []),
               "fallback": result.get("fallback", False), "done": False}

    yield {"type": "_done", "items": [], "fallback": False, "done": True}


async def _cold_start_for_type(profile, behaviors, click_prefs, context_text, ct, limit):
    """冷启动：单类型推荐（复用 _cold_start_recommend 逻辑，但按类型拆分）"""
    from engine.data_repo import get_all_candidates, get_field_importance
    table = TYPE_TO_TABLE.get(ct)
    if not table:
        return {"type": ct, "items": [], "fallback": True}
    candidates = await get_all_candidates(ct)
    field_imp = await get_field_importance(table)
    scored = []
    all_with_scores = []
    for c in candidates:
        fs = _calc_field_completeness(c, field_imp)
        item = {"content_id": str(c.get("content_id", "")), "title": c.get("title", ""),
                "content_type": ct, "score": round(fs, 4),
                "reason": _template_reason(c.get("title", ""), ct)}
        if fs >= 0.4:
            scored.append(item)
        else:
            all_with_scores.append(item)
    if not scored and all_with_scores:
        all_with_scores.sort(key=lambda x: x["score"], reverse=True)
        scored = all_with_scores[:1]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {"type": ct, "items": scored[:limit], "fallback": True}


async def _cold_start_recommend(profile: dict | None, behaviors: list,
                                content_types: list[str], limit: int) -> dict:
    """
    新用户冷启动：无专业/技能/行为 → 无法个性化匹配。
    按「字段完整度高、内容质量好」推荐热门内容，每种类型取 limit 条。
    不使用 LLM（没有可匹配的上下文），用模板理由。
    """
    items = []

    for ct in content_types:
        table = TYPE_TO_TABLE.get(ct)
        if not table:
            continue
        field_imp = await get_field_importance(table)
        candidates = await get_all_candidates(ct, user_id)
        if not candidates:
            continue

        # 按字段完整性得分排序
        scored = []
        all_with_scores = []
        for c in candidates:
            fs = _calc_field_completeness(c, field_imp)
            item = {
                "content_id": str(c.get("content_id", "")),
                "title": c.get("title", ""),
                "content_type": ct,
                "score": round(fs, 4),
                "reason": _template_reason(c.get("title", ""), ct),
            }
            if fs >= 0.4:
                scored.append(item)
            else:
                all_with_scores.append(item)
        # 保底：至少返回最高分的一条
        if not scored and all_with_scores:
            all_with_scores.sort(key=lambda x: x["score"], reverse=True)
            scored = all_with_scores[:1]
            logger.info(f"[V5] 冷启动 {ct}: 全部低于阈值，保底返回 1 条 (score={scored[0]['score']})")
        scored.sort(key=lambda x: x["score"], reverse=True)
        items.extend(scored[:limit])

    items.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"[V5] 冷启动完成: {len(items)} 条")
    return _build_response(items, fallback_used=False)


async def _recommend_for_type(user_id: str, profile: dict | None, behaviors: list, click_prefs: dict,
                               context_text: str, content_type: str, limit: int,
                               user_vector: list[float] | None = None) -> dict:
    import time as _time
    _t0 = _time.monotonic()

    table = TYPE_TO_TABLE.get(content_type)
    if not table:
        return {"type": content_type, "items": [], "fallback": False, "cache_hit": False}

    all_candidates = await get_all_candidates(content_type, user_id)
    field_imp = await get_field_importance(table)
    if not all_candidates:
        return {"type": content_type, "items": [], "fallback": False, "cache_hit": False}

    # ── 1. BGE 语义初筛 ──
    _t1 = _time.monotonic()
    if user_vector is not None:
        # 复用 run_recommend_v2 已编码的用户向量，不再重复 BGE 编码
        user_vec_text = ""
    else:
        user_vec_text = build_user_vector_text(profile, behaviors)
    candidates = await pre_screen_candidates(all_candidates, field_imp, user_vector_text=user_vec_text, user_vector=user_vector)
    _t_bge = _time.monotonic() - _t1
    logger.info(f"[V5] {content_type}: 初筛 {len(all_candidates)} → {len(candidates)} ({_t_bge*1000:.0f}ms)")

    # ── 2. LLM 评分 + 理由 (带 Redis 缓存) ──
    # 截断 LLM 候选，按 BGE 相似度取 top 8
    # (pre_screen 在候选≤30时不排序，需手动排序避免截到低分内容)
    candidates.sort(key=lambda x: x.get("_sim", 0), reverse=True)
    llm_candidates = candidates[:8] if len(candidates) > 8 else candidates
    user_context = build_user_context(profile, behaviors, context_text)
    llm_results = {}  # content_id → {llm_score, reason}
    fallback = False
    cache_key = ""
    _cached_from_redis = False  # 标记本类型是否命中缓存

    if not DISABLE_LLM:
        # 构建缓存 key: candidates 指纹 + 上下文指纹
        _cand_ids = sorted(str(c.get("content_id", "")) for c in llm_candidates)
        _cand_fp = hashlib.md5(",".join(_cand_ids).encode()).hexdigest()[:12]
        _ctx_fp = hashlib.md5(user_context.encode()).hexdigest()[:12]
        cache_key = f"llm_score:{user_id}:{content_type}:{_cand_fp}:{_ctx_fp}"

        # 尝试读缓存
        cached = None
        try:
            from db.redis_client import get_redis
            _r = await get_redis()
            raw = await _r.get(cache_key)
            if raw:
                cached = json.loads(raw)
                _cached_from_redis = True
                logger.info(f"[V5] {content_type}: \033[34mRedis 缓存命中\033[0m ({cache_key})")
        except Exception:
            _r = None  # Redis 不可用 → 静默降级

        if cached:
            llm_results = {}
            for cid, v in cached.items():
                llm_results[cid] = {"score": v["s"], "reason": v["r"]}
            logger.info(f"[V5] {content_type}: \033[34m复用缓存\033[0m (跳过 API 调用)")
        else:
            try:
                llm_results = await llm_breaker.call(
                    llm_score_and_rank(user_context, llm_candidates, field_imp, content_type, limit)
                )
                if llm_results:
                    sample = list(llm_results.items())[0]
                    logger.info(f"[V5] LLM原始返回样例: {sample}")

                # 写入 Redis 缓存
                if llm_results and cache_key and _r is not None:
                    try:
                        val = {cid: {"s": info["score"], "r": info["reason"]}
                               for cid, info in llm_results.items()}
                        from db.redis_client import LLM_CACHE_TTL
                        await _r.setex(cache_key, LLM_CACHE_TTL, json.dumps(val, ensure_ascii=False))
                        logger.info(f"[V5] {content_type}: LLM 结果已缓存 (TTL={LLM_CACHE_TTL}s)")
                    except Exception:
                        pass  # 缓存写入失败不影响主流程
            except (LLMError, CircuitOpenError) as e:
                logger.warning(f"[V5] LLM不可用: {e}")
                fallback = True
            except Exception as e:
                logger.error(f"[V5] LLM异常: {e}")
                fallback = True
    else:
        fallback = True
        logger.info(f"[V5] LLM 已禁用，走降级模式")

    # ── 3. 本地融合计算 ──
    time_cfg = TIME_DECAY_CONFIG.get(content_type, {})
    now = datetime.now(timezone.utc)
    scored = []
    all_with_scores = []  # 记录所有候选及其分数（不分低于 0.4 的也要）

    for c in candidates:
        cid = str(c.get("content_id", ""))
        bge_sim = c.get("_sim", 0.0)

        llm_info = llm_results.get(cid, {})
        llm_score = float(llm_info.get("score", 0.0))
        reason = llm_info.get("reason", "")

        # 字段完整性得分
        field_score = _calc_field_completeness(c, field_imp)

        # 时间衰减
        time_decay = _calc_time_decay(c, content_type, time_cfg, now)

        # 历史点击偏好加分（同一类型的历史点击越多，略微加分）
        click_count = click_prefs.get(content_type, 0)
        click_boost = min(click_count * 0.015, 0.05)  # 最多加 0.05

        # 融合公式: LLM×0.7 + BGE×0.1 + 字段×0.05 + 时间×time_weight
        time_weight = time_cfg.get("weight", 0.0)
        if fallback:
            final = bge_sim * 0.5 + field_score * 0.35 + time_decay * 0.15 + click_boost
        else:
            final = llm_score * 0.7 + bge_sim * 0.1 + field_score * 0.05 + time_decay * time_weight + click_boost

        # 过滤低分（但保留一份完整列表供底线兜底）
        if final >= 0.4:
            scored.append({
                "content_id": cid,
                "title": c.get("title", ""),
                "content_type": content_type,
                "score": round(final, 4),
                "reason": reason or _template_reason(c.get("title", ""), content_type),
            })
        else:
            all_with_scores.append({
                "content_id": cid,
                "title": c.get("title", ""),
                "content_type": content_type,
                "score": round(final, 4),
                "reason": reason or _template_reason(c.get("title", ""), content_type),
            })

    # 底线保底：该类型若全部低于 0.4，返回最高分的一个
    if not scored and all_with_scores:
        all_with_scores.sort(key=lambda x: x["score"], reverse=True)
        scored = all_with_scores[:1]
        logger.info(f"[V5] {content_type}: 全部低于阈值，保底返回 1 条 (score={scored[0]['score']})")

    scored.sort(key=lambda x: x["score"], reverse=True)
    items = scored[:limit]
    _t_total = _time.monotonic() - _t0
    logger.info(f"[V5] {content_type}: \033[36mtotal={_t_total*1000:.0f}ms\033[0m "
                f"(BGE={_t_bge*1000:.0f}ms, cache={'hit' if _cached_from_redis else 'miss'}), "
                f"top={[(i['title'][:10], i['score']) for i in items]}".replace("'", ""))
    return {"type": content_type, "items": items, "fallback": fallback, "cache_hit": _cached_from_redis}


def _calc_field_completeness(item: dict, field_imp: dict) -> float:
    """计算字段完整性和质量得分，归一化到 [0,1]"""
    total = 0.0
    max_total = 0.0
    for field, info in field_imp.items():
        imp = info.get("importance", 1)
        weight = info.get("weight", 1.0)
        max_total += imp * weight
        val = str(item.get(field, "")).strip()
        if val and val != "-":
            len_factor = min(len(val) / 80.0, 1.0)
            total += imp * weight * (0.3 + 0.7 * len_factor)
    return total / max_total if max_total > 0 else 0.5


def _calc_time_decay(item: dict, content_type: str, cfg: dict, now: datetime) -> float:
    half_life = cfg.get("half_life_days")
    if half_life is None:
        return 1.0

    if content_type == "training":
        end_apply = item.get("end_apply", "")
        if end_apply:
            try:
                deadline = datetime.strptime(end_apply, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if now > deadline:
                    return 0.5
            except (ValueError, TypeError):
                pass

    sync_val = item.get("sync_at")
    if sync_val and isinstance(sync_val, str):
        try:
            sync_at = datetime.fromisoformat(sync_val)
            if sync_at.tzinfo is None:
                sync_at = sync_at.replace(tzinfo=timezone.utc)
            days = max(0, (now - sync_at).total_seconds() / 86400.0)
            return math.pow(2, -days / half_life)
        except (ValueError, TypeError):
            pass
    return 1.0


def _template_reason(title: str, content_type: str) -> str:
    labels = {"course": "课程", "training": "培训班", "skill": "岗位",
              "scale": "测评", "career": "方案", "news": "资讯"}
    return f"根据您的背景为您推荐该{labels.get(content_type, '内容')}"


def _build_response(items: list[dict], fallback_used: bool = False) -> dict:
    import uuid
    return {
        "code": 200,
        "data": {
            "trace_id": f"rec-{uuid.uuid4().hex[:12]}",
            "fallback_used": fallback_used,
            "recommendations": [{
                "content_id": str(i.get("content_id", "")),
                "content_type": i.get("content_type", ""),
                "title": i.get("title", ""),
                "reason": i.get("reason", ""),
                "score": round(float(i.get("score", 0.5)), 4),
                "tags": i.get("tags", []),
            } for i in items],
        }
    }
