"""
新版内容数据同步 — 将外部接口数据写入分内容类型的新表
写入失败自动重试 3 次（指数退避）
仅对内容实际变化的数据刷新向量
"""
import os
import json
import time
import hashlib
import logging
from sqlalchemy import text
from db.connection import get_db_session
from adapters.external_api import fetch_api_data, ExternalApiError
from utils.retry import retry_async
from engine.data_repo import TYPE_TO_TABLE, get_field_importance, build_candidate_text
from engine.embedding import encode_text

# Docker 环境下用 PGPOOL_DSN 连接 postgres 容器；本机开发回退到 socket
_PG_DSN = os.environ.get("PGPOOL_DSN", "dbname=recommend_agent host=/tmp")
import psycopg2

logger = logging.getLogger(__name__)

CONTENT_API_TYPES = ["courses", "training", "skills", "scales", "career"]

TABLE_MAP = {
    "courses": "courses",
    "training": "training_classes",
    "skills": "skill_positions",
    "scales": "assessment_scales",
    "career": "career_plans",
}

# 指纹计算字段：每种类型用核心文本字段计算 MD5
FINGERPRINT_FIELDS = {
    "courses":   ["name", "texts1", "Texts2", "Texts3", "Texts4"],
    "training":  ["name", "classify", "training", "regions", "places"],
    "skills":    ["trade", "grade", "name", "degree", "major", "working"],
    "scales":    ["name", "tags", "texts1", "values"],
    "career":    ["name", "crouds", "emphasis", "details"],
}


def _build_fingerprint(raw: dict, api_type: str) -> str:
    """对一条记录的核心字段计算 MD5 指纹"""
    fields = FINGERPRINT_FIELDS.get(api_type, ["name"])
    seed = ""
    for f in fields:
        val = raw.get(f, "") or ""
        seed += str(val)
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


async def _load_existing_fingerprints(api_type: str, session) -> dict[str, str]:
    """加载已有内容的指纹: {origin_id: content_hash}（直接读已存的，不临时计算）"""
    table = TABLE_MAP.get(api_type)
    if not table:
        return {}
    r = await session.execute(
        text(f"SELECT origin_id, content_hash FROM {table} WHERE status='active'")
    )
    rows = r.fetchall()
    return {str(row[0]): str(row[1] or "") for row in rows}





async def _sync_single_type(api_type: str) -> dict:
    """异步同步单个内容类型到对应新表"""
    start = time.time()
    result = {"api_type": api_type, "status": "failed", "count": 0, "duration_ms": 0, "error": None}

    try:
        data = await fetch_api_data(api_type)
        records = data.get("records", [])
        if not records:
            result["status"] = "success"
            result["count"] = 0
            logger.info(f"[{api_type}] 无新数据")
            return result

        target_table = TABLE_MAP.get(api_type)
        if not target_table:
            result["error"] = f"未知接口类型: {api_type}"
            return result

        # 加载已有内容指纹（用于判断是否实际变化）
        db = get_db_session()
        async with db as session:
            existing_fps = await _load_existing_fingerprints(api_type, session)

        # 封装 DB 写入逻辑，支持重试
        async def _write_to_db():
            async with get_db_session() as session:
                saved = 0
                changed = []
                for raw in records:
                    if not isinstance(raw, dict):
                        continue
                    origin_id = str(raw.get("id", ""))

                    # 判断内容是否实际变化
                    new_fp = _build_fingerprint(raw, api_type)
                    old_fp = existing_fps.get(origin_id)
                    is_new = origin_id not in existing_fps
                    is_changed = not is_new and new_fp != old_fp

                    try:
                        if api_type == "courses":
                            await session.execute(text("""
                                INSERT INTO courses (origin_id, num_xs, name, texts1, texts2, texts3, texts4, content_hash)
                                VALUES (:oid, :num, :name, :t1, :t2, :t3, :t4, :hash)
                                ON CONFLICT (origin_id)
                                DO UPDATE SET name=EXCLUDED.name, texts1=EXCLUDED.texts1,
                                              texts2=EXCLUDED.texts2, texts3=EXCLUDED.texts3,
                                              texts4=EXCLUDED.texts4, content_hash=EXCLUDED.content_hash, sync_at=NOW()
                            """), {
                                "oid": origin_id, "num": str(raw.get("numXs", "")),
                                "name": raw.get("name", ""),
                                "t1": raw.get("texts1", ""), "t2": raw.get("Texts2", ""),
                                "t3": raw.get("Texts3", ""), "t4": raw.get("Texts4", ""),
                                "hash": new_fp,
                            })
                        elif api_type == "training":
                            await session.execute(text("""
                                INSERT INTO training_classes (origin_id, snum, name, classify, start_apply, end_apply,
                                    start_study, end_study, limits, regions, places, training, certif, deleted, content_hash)
                                VALUES (:oid, :sn, :n, :cl, :sa, :ea, :ss, :es, :li, :reg, :pl, :tr, :ce, :de, :hash)
                                ON CONFLICT (origin_id)
                                DO UPDATE SET name=EXCLUDED.name, training=EXCLUDED.training,
                                              classify=EXCLUDED.classify, start_apply=EXCLUDED.start_apply,
                                              end_apply=EXCLUDED.end_apply, limits=EXCLUDED.limits,
                                              regions=EXCLUDED.regions, places=EXCLUDED.places,
                                              content_hash=EXCLUDED.content_hash, sync_at=NOW()
                            """), {
                                "oid": origin_id, "sn": str(raw.get("snum", "")),
                                "n": raw.get("name", ""), "cl": raw.get("classify", ""),
                                "sa": raw.get("startApply", ""), "ea": raw.get("endApply", ""),
                                "ss": raw.get("startStudy", ""), "es": raw.get("endStudy", ""),
                                "li": int(raw.get("limits", 0)) if raw.get("limits") else None,
                                "reg": raw.get("regions", ""), "pl": raw.get("places", ""),
                                "tr": raw.get("training", ""), "ce": raw.get("certif", ""),
                                "de": raw.get("deleted", "正常"),
                                "hash": new_fp,
                            })
                        elif api_type == "skills":
                            await session.execute(text("""
                                INSERT INTO skill_positions (origin_id, trade, grade, codes, name, years, salary, degree, major, working, content_hash)
                                VALUES (:oid, :tr, :gr, :co, :n, :yr, :sa, :de, :ma, :wo, :hash)
                                ON CONFLICT (origin_id)
                                DO UPDATE SET name=EXCLUDED.name, trade=EXCLUDED.trade, major=EXCLUDED.major,
                                              degree=EXCLUDED.degree, working=EXCLUDED.working,
                                              content_hash=EXCLUDED.content_hash, sync_at=NOW()
                            """), {
                                "oid": origin_id, "tr": raw.get("trade", ""), "gr": raw.get("grade", ""),
                                "co": str(raw.get("codes", "")), "n": raw.get("name", ""),
                                "yr": str(raw.get("years", "")), "sa": str(raw.get("salary", "")),
                                "de": raw.get("degree", ""), "ma": raw.get("major", ""), "wo": raw.get("working", ""),
                                "hash": new_fp,
                            })
                        elif api_type == "scales":
                            await session.execute(text("""
                                INSERT INTO assessment_scales (origin_id, product_id, name, tags, pnums, ptimes, texts1, vals, content_hash)
                                VALUES (:oid, :pid, :n, :tg, :pn, :pt, :t1, :v, :hash)
                                ON CONFLICT (origin_id)
                                DO UPDATE SET name=EXCLUDED.name, texts1=EXCLUDED.texts1, vals=EXCLUDED.vals,
                                              content_hash=EXCLUDED.content_hash, sync_at=NOW()
                            """), {
                                "oid": origin_id, "pid": raw.get("productId"),
                                "n": raw.get("name", ""), "tg": raw.get("tags", ""),
                                "pn": int(raw.get("pnums", 0)) if raw.get("pnums") else None,
                                "pt": int(raw.get("ptimes", 0)) if raw.get("ptimes") else None,
                                "t1": raw.get("texts1", ""), "v": raw.get("values", ""),
                                "hash": new_fp,
                            })
                        elif api_type == "career":
                            await session.execute(text("""
                                INSERT INTO career_plans (origin_id, customId, staffId, name, crouds, emphasis,
                                    actions, tools, details, position, remarks, addTime, raw_data, content_hash)
                                VALUES (:oid, :cid, :sid, :n, :cr, :em, :ac, :tl, :dt, :pos, :rm, :at, :raw, :hash)
                                ON CONFLICT (origin_id)
                                DO UPDATE SET name=EXCLUDED.name, crouds=EXCLUDED.crouds,
                                              emphasis=EXCLUDED.emphasis, details=EXCLUDED.details,
                                              actions=EXCLUDED.actions, tools=EXCLUDED.tools,
                                              position=EXCLUDED.position, remarks=EXCLUDED.remarks,
                                              addTime=EXCLUDED.addTime, raw_data=EXCLUDED.raw_data,
                                              content_hash=EXCLUDED.content_hash, sync_at=NOW()
                            """), {
                                "oid": origin_id,
                                # customId/staffId 接口可能返回整数，schema 为 VARCHAR，统一转字符串
                                "cid": str(raw.get("customId") or ""), "sid": str(raw.get("staffId") or ""),
                                "n": raw.get("title", raw.get("name", "")),
                                "cr": raw.get("crouds", ""), "em": raw.get("emphasis", ""),
                                "ac": raw.get("actions", ""), "tl": raw.get("tools", ""),
                                "dt": raw.get("details", raw.get("texts1", "")),
                                "pos": raw.get("position", ""), "rm": raw.get("remarks", ""),
                                "at": raw.get("addTime", ""),
                                "raw": json.dumps(raw, ensure_ascii=False),
                                "hash": new_fp,
                            })
                        saved += 1
                        if is_new or is_changed:
                            changed.append(origin_id)
                    except Exception as e:
                        logger.warning(f"[{api_type}] 单条写入失败 (id={origin_id}): {e}")
                await session.commit()
                return saved, changed

        stored, changed_ids = await retry_async(_write_to_db, max_retries=3, base_delay=2.0)
        result["status"] = "success"
        result["count"] = stored
        result["changed_ids"] = changed_ids
        logger.info(f"[{api_type}] 同步完成: {stored} 条")

    except ExternalApiError as e:
        result["error"] = str(e)
        logger.error(f"[{api_type}] 接口失败: {e}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[{api_type}] 未知错误: {e}")

    result["duration_ms"] = int((time.time() - start) * 1000)
    return result


async def refresh_vectors_by_ids(content_type: str, origin_ids: list[str]):
    """仅刷新指定 origin_id 的向量"""
    if not origin_ids:
        return

    table = TYPE_TO_TABLE.get(content_type)
    if not table:
        return
    field_imp = await get_field_importance(table)
    if not field_imp:
        return

    # 从分表拉对应内容
    db = get_db_session()
    async with db as session:
        placeholders = ",".join(f":cid{i}" for i in range(len(origin_ids)))
        r = await session.execute(
            text(f"SELECT * FROM {table} WHERE origin_id IN ({placeholders})"),
            {f"cid{i}": cid for i, cid in enumerate(origin_ids)}
        )
        rows = r.fetchall()
        if not rows:
            return
        columns = list(rows[0]._mapping.keys())
        items = []
        for row in rows:
            item = dict(row._mapping)
            item["title"] = item.get("name") or item.get("title", "")
            items.append(item)

    # 编码并写入向量表
    texts = [build_candidate_text(item, field_imp) for item in items]
    vectors = [encode_text(t) for t in texts]

    conn = psycopg2.connect(_PG_DSN)
    cur = conn.cursor()
    for item, vec in zip(items, vectors):
        cid = str(item.get("origin_id", ""))
        cur.execute(
            "INSERT INTO content_vectors (content_id, content_type, embedding, cached_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (content_id) DO UPDATE SET embedding=EXCLUDED.embedding, cached_at=NOW()",
            (cid, content_type, vec)
        )
    conn.commit()
    cur.close()
    conn.close()

    # 标记内容向量已就绪
    db = get_db_session()
    table = TYPE_TO_TABLE[content_type]
    placeholders = ",".join(f":cid{i}" for i in range(len(origin_ids)))
    async with db as session:
        await session.execute(
            text(f"UPDATE {table} SET has_vector = TRUE WHERE origin_id IN ({placeholders})"),
            {f"cid{i}": cid for i, cid in enumerate(origin_ids)}
        )
        await session.commit()

    logger.info(f"[{content_type}] 刷新 {len(items)} 条向量 (按 ID)")


async def sync_all_content() -> dict:
    """异步同步所有内容类型到新表"""
    logger.info("========== [V2] 开始全量内容同步 ==========")
    summary = {"total": 0, "success": 0, "failed": 0, "details": []}

    for api_type in CONTENT_API_TYPES:
        result = await _sync_single_type(api_type)
        summary["details"].append(result)

        # 同步日志
        db = get_db_session()
        async with db as s:
            await s.execute(
                text("""
                    INSERT INTO sync_log (api_type, status, records_count, error_message, duration_ms, started_at, finished_at)
                    VALUES (:type, :status, :count, :error, :duration, NOW(), NOW())
                """),
                {"type": result["api_type"], "status": result["status"],
                 "count": result["count"], "error": result.get("error"), "duration": result["duration_ms"]}
            )
            await s.commit()

        if result["status"] == "success":
            summary["success"] += 1
            summary["total"] += result["count"]
            # 只刷新变更过的内容的向量
            changed = result.get("changed_ids", [])
            if changed:
                try:
                    content_type = {"courses": "course", "training": "training",
                                    "skills": "skill", "scales": "scale",
                                    "career": "career"}.get(api_type)
                    if content_type:
                        # 先标记向量失效，再刷新
                        table = TYPE_TO_TABLE.get(content_type)
                        if table and changed:
                            db = get_db_session()
                            async with db as session:
                                placeholders = ",".join(f":cid{i}" for i in range(len(changed)))
                                await session.execute(
                                    text(f"UPDATE {table} SET has_vector = FALSE WHERE origin_id IN ({placeholders})"),
                                    {f"cid{i}": cid for i, cid in enumerate(changed)}
                                )
                                await session.commit()
                        await refresh_vectors_by_ids(content_type, changed)
                except Exception as e:
                    logger.warning(f"[{api_type}] 向量刷新失败: {e}")
        else:
            summary["failed"] += 1

    logger.info(f"========== [V2] 内容同步结束: {summary['success']}/{len(CONTENT_API_TYPES)} 成功, 共 {summary['total']} 条 ==========")
    return summary
