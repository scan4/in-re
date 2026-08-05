"""推荐 API 路由 — V2: LLM打分引擎 + SSE流式"""
import json
import base64
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from schemas.recommend import RecommendRequest, RecommendResponse, FeedbackRequest
from engine.orchestrator_v2 import run_recommend_v2, process_type_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["recommend"])


def _parse_jwt_payload(token: str) -> dict:
    """手动解码 JWT payload (不验签，网关已验证)
    返回 {phone, username, user_id, institution_id, role}
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("无效的 JWT 格式")
        # 补齐 base64 padding
        payload_b64 = parts[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        return json.loads(payload_json)
    except Exception as e:
        logger.warning(f"JWT 解析失败: {e}")
        raise HTTPException(status_code=401, detail="Token 无效")


async def _ensure_user_exists(phone: str, username: str, token: str = ""):
    """首次访问：注册用户 → 补全画像 → 同步可见内容权限"""
    from sqlalchemy import text
    from db.connection import get_db_session

    if not phone:
        return

    db = get_db_session()
    async with db as session:
        row = await session.execute(
            text("SELECT base_tags FROM user_profile WHERE user_id = :uid"),
            {"uid": phone}
        )
        existing = row.fetchone()

        need_profile = True
        if existing:
            tags = existing[0] or {}
            if isinstance(tags, str):
                tags = json.loads(tags)
            if tags.get("major"):
                need_profile = False  # 已有完整画像

        if need_profile:
            base_tags = {"name": username}
            await session.execute(
                text("""
                    INSERT INTO user_profile (user_id, base_tags, updated_at)
                    VALUES (:uid, CAST(:tags AS jsonb), NOW())
                    ON CONFLICT (user_id) DO NOTHING
                """),
                {"uid": phone, "tags": json.dumps(base_tags, ensure_ascii=False)}
            )
            await session.commit()
            logger.info(f"新用户已注册: phone={phone}, name={username}")

            # 补全画像
            try:
                from adapters.external_api import fetch_api_data
                data = await fetch_api_data("behavior")
                records = data.get("records", {})
                signup_data = None
                if isinstance(records, dict):
                    for cat in ["signup", "browsing", "search"]:
                        items = records.get(cat, [])
                        for item in (items or []):
                            if isinstance(item, dict) and item.get("ausers") == phone:
                                if cat == "signup":
                                    signup_data = item
                                break
                        if signup_data:
                            break
                if signup_data:
                    base_tags["education"] = signup_data.get("xueli")
                    base_tags["major"] = signup_data.get("major")
                    base_tags["college"] = signup_data.get("college")
                    skills_raw = signup_data.get("skills")
                    base_tags["skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()] if (skills_raw and isinstance(skills_raw, str)) else []
                    await session.execute(
                        text("UPDATE user_profile SET base_tags = CAST(:tags AS jsonb), updated_at = NOW() WHERE user_id = :uid"),
                        {"uid": phone, "tags": json.dumps(base_tags, ensure_ascii=False)}
                    )
                    await session.commit()
                    logger.info(f"用户画像已补全: major={base_tags.get('major')}")
            except Exception as e:
                logger.warning(f"补全画像失败: {e}")

        # 检查是否需要同步该用户的可见内容权限
        import os
        if os.environ.get("REQUIRE_PERMISSIONS", "false").lower() == "true":
            row2 = await session.execute(
                text("SELECT 1 FROM user_content_visible WHERE user_id = :uid LIMIT 1"),
                {"uid": phone}
            )
            if not row2.fetchone() and token:
                logger.info(f"首次访问 {phone}，开始同步可见内容权限...")
                await _sync_user_permissions(session, phone, token)


async def _sync_user_permissions(session, user_id: str, token: str):
    """用该用户的 Token 拉取 6 个内容接口，记录可访问的 origin_id"""
    from adapters.external_api import fetch_all_apis
    from sqlalchemy import text

    # 只拉内容接口，不拉 behavior 和 news（news 是平台共享资讯）
    content_apis = ["courses", "training", "skills", "scales", "career"]
    api_to_type = {
        "courses": "course", "training": "training", "skills": "skill",
        "scales": "scale", "career": "career",
    }

    try:
        results = await fetch_all_apis(content_apis, token=token)
        # 检查完整性：至少 4/5 种类型有数据才认可这次同步有效
        types_with_data = sum(1 for d in results.values() if d.get("records"))
        if types_with_data < 4:
            logger.warning(f"{user_id}: 权限同步不完整 ({types_with_data}/5 类型有数据)，丢弃")
            return
        inserted = 0
        for api_name, data in results.items():
            ct = api_to_type.get(api_name, api_name)
            records = data.get("records", [])
            if isinstance(records, list):
                for item in records:
                    if isinstance(item, dict):
                        oid = str(item.get("id") or item.get("origin_id") or "")
                        if oid:
                            await session.execute(
                                text("""
                                    INSERT INTO user_content_visible (user_id, origin_id, content_type, synced_at)
                                    VALUES (:uid, :oid, :ct, NOW())
                                    ON CONFLICT (user_id, content_type, origin_id) DO NOTHING
                                """),
                                {"uid": user_id, "oid": oid, "ct": ct}
                            )
                            inserted += 1
        await session.commit()
        logger.info(f"{user_id}: 权限同步完成, {inserted} 条可见内容")
    except Exception as e:
        logger.warning(f"{user_id}: 权限同步失败 (推荐将使用默认内容池): {e}")


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest):
    """获取个性化推荐 — JWT 鉴权 + V2 引擎"""
    try:
        payload = _parse_jwt_payload(req.token)
        user_id = payload.get("phone", "")  # phone 对应现有数据中的 user_id

        if not user_id:
            raise HTTPException(status_code=401, detail="Token 中缺少 phone 字段")

        # 自动注册 + 同步可见内容权限
        await _ensure_user_exists(user_id, payload.get("username", ""), req.token)

        result = await run_recommend_v2(
            user_id=user_id,
            context_type=req.context_type,
            context_text=req.context_text,
            limit=req.limit,
            content_types=req.content_types,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"推荐失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommend/stream")
async def recommend_stream(req: RecommendRequest):
    """流式推荐 — 每完成一个类型就推给前端"""
    try:
        payload = _parse_jwt_payload(req.token)
        user_id = payload.get("phone", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token 中缺少 phone 字段")

        await _ensure_user_exists(user_id, payload.get("username", ""), req.token)

        async def generate():
            async for chunk in process_type_stream(
                user_id=user_id,
                context_type=req.context_type,
                context_text=req.context_text,
                limit=req.limit,
                content_types=req.content_types,
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"流式推荐失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommend/feedback")
async def feedback(req: FeedbackRequest):
    """上报推荐反馈 (曝光/点击)"""
    from sqlalchemy import text
    from db.connection import get_db_session

    db = get_db_session()
    async with db as session:
        await session.execute(
            text("""
                INSERT INTO recommend_log (user_id, trace_id, event_type, content_id, content_type, position, event_time, created_at)
                VALUES (:uid, :tid, :etype, :cid, :ctype, :pos, NOW(), NOW())
            """),
            {"uid": req.user_id, "tid": req.trace_id, "etype": req.event_type,
             "cid": req.content_id, "ctype": req.content_type, "pos": req.position}
        )
        await session.commit()
    return {"code": 200, "message": "ok"}
