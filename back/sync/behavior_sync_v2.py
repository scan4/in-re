"""
新版用户行为数据同步 — 写入 user_behaviors 表，写入失败自动重试 3 次
"""
import json
import time
import logging
from sqlalchemy import text
from db.connection import get_db_session
from adapters.external_api import fetch_api_data, ExternalApiError
from utils.retry import retry_async

logger = logging.getLogger(__name__)

BEHAVIOR_CATEGORIES = ["browsing", "search", "learning", "signup"]


async def sync_behavior() -> dict:
    """异步同步用户行为数据到 user_behaviors 表"""
    logger.info("========== [V2] 开始行为同步 ==========")
    start = time.time()
    result = {"api_type": "behavior", "status": "failed", "total_records": 0, "by_category": {}, "error": None}

    try:
        data = await fetch_api_data("behavior")
        records = data.get("records", {})
        if not isinstance(records, dict):
            records = {}

        # 封装 DB 写入逻辑，支持重试
        async def _write_behaviors():
            async with get_db_session() as session:
                saved = {"total": 0, "browsing": 0, "search": 0, "learning": 0, "signup": 0}
                for category in BEHAVIOR_CATEGORIES:
                    category_records = records.get(category, [])
                    if not isinstance(category_records, list):
                        category_records = []
                    for raw in category_records:
                        if not isinstance(raw, dict):
                            continue
                        if category == "signup":
                            await _sync_user_profile(session, raw)
                        else:
                            user_id = str(raw.get("ausers", raw.get("id", "")))
                            user_name = raw.get("anames", "")
                            content = raw.get("contents", raw.get("name", ""))
                            extra = {}
                            if category == "learning":
                                extra = {"duration": raw.get("duration", 0),
                                         "startTime": raw.get("startTime", ""),
                                         "endTime": raw.get("endTime", "")}
                            origin_id = str(raw.get("id", ""))
                            await session.execute(
                                text("""
                                    INSERT INTO user_behaviors (origin_id, user_id, user_name, behavior_type, content, extra_info, event_time)
                                    VALUES (:oid, :uid, :un, :bt, :ct, :ex, NOW())
                                    ON CONFLICT (origin_id) DO NOTHING
                                """),
                                {"oid": origin_id, "uid": user_id, "un": user_name, "bt": category,
                                 "ct": content, "ex": json.dumps(extra) if extra else None}
                            )
                        saved[category] += 1
                    saved["total"] += saved[category]
                await session.commit()
                return saved

        saved = await retry_async(_write_behaviors, max_retries=3, base_delay=2.0)
        result["status"] = "success"
        result["by_category"] = {k: v for k, v in saved.items() if k != "total"}
        result["total_records"] = saved["total"]
        logger.info(f"[behavior] 完成: {saved['total']} 条")

    except ExternalApiError as e:
        result["error"] = str(e)
        logger.error(f"[behavior] 接口失败: {e}")

    # 同步日志
    db = get_db_session()
    async with db as s:
        try:
            await s.execute(
                text("""
                    INSERT INTO sync_log (api_type, status, records_count, error_message, duration_ms, started_at, finished_at)
                    VALUES (:type, :status, :count, :error, :duration, NOW(), NOW())
                """),
                {"type": "behavior", "status": result["status"],
                 "count": sum(result["by_category"].values()),
                 "error": result.get("error"), "duration": int((time.time() - start) * 1000)}
            )
            await s.commit()
        except Exception as e:
            logger.warning(f"同步日志写入失败: {e}")

    total = sum(result["by_category"].values())
    logger.info(f"========== [V2] 行为同步结束: {total} 条 ==========")
    return result


async def _sync_user_profile(session, raw: dict):
    """同步用户画像"""
    user_id = raw.get("id") or raw.get("ausers")
    if not user_id:
        return

    def _age_to_group(age) -> str | None:
        try:
            age = int(age)
            if age < 20: return "<20"
            if age < 25: return "20-25"
            if age < 30: return "25-30"
            if age < 35: return "30-35"
            if age < 45: return "35-45"
            return "45+"
        except (ValueError, TypeError):
            return None

    base_tags = {
        "education": raw.get("xueli"),
        "major": raw.get("major"),
        "skills": [s.strip() for s in str(raw.get("skills", "")).split(",") if s.strip()] if raw.get("skills") else [],
        "age_group": _age_to_group(raw.get("ages")),
        "college": raw.get("college"),
        "name": raw.get("name"),
    }
    await session.execute(
        text("""
            INSERT INTO user_profile (user_id, base_tags, behavior_tags, preferred_content_types, last_active_at, updated_at)
            VALUES (:uid, :base, :behav, :pref, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET base_tags = EXCLUDED.base_tags, updated_at = NOW()
        """),
        {"uid": str(user_id), "base": json.dumps(base_tags, ensure_ascii=False),
         "behav": json.dumps({}), "pref": json.dumps({})}
    )
