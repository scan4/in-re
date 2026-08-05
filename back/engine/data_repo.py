"""
数据仓库 V3 — 精确查用户 + pgvector 向量检索初筛
"""
import os
import json
import logging
from sqlalchemy import text
from db.connection import get_db_session
from db.schema_v2 import TABLE_NAME_MAP
from engine.embedding import encode_text_async

logger = logging.getLogger(__name__)

TYPE_TO_TABLE = TABLE_NAME_MAP

PRE_SCREEN_LIMIT = 30
SIMILARITY_THRESHOLD = 0.45


async def get_user_profile(user_id: str) -> dict | None:
    db = get_db_session()
    async with db as session:
        r = await session.execute(
            text("SELECT user_id, base_tags FROM user_profile WHERE user_id = :uid"),
            {"uid": user_id}
        )
        row = r.fetchone()
        if not row:
            return None
        base = row[1] or {}
        if isinstance(base, str):
            try: base = json.loads(base)
            except: base = {}
        return {"user_id": str(row[0]), "base_tags": base}


async def get_user_behaviors(user_id: str, limit: int = 20) -> list[dict]:
    db = get_db_session()
    async with db as session:
        r = await session.execute(
            text("""
                SELECT behavior_type, content, extra_info, event_time
                FROM user_behaviors
                WHERE user_id = :uid
                ORDER BY event_time DESC
                LIMIT :limit
            """),
            {"uid": user_id, "limit": limit}
        )
        rows = r.fetchall()
        return [
            {"type": row[0], "content": row[1],
             "extra": json.loads(row[2]) if isinstance(row[2], str) else row[2],
             "time": str(row[3])}
            for row in rows
        ]


async def get_all_candidates(content_type: str, user_id: str = "") -> list[dict]:
    table = TYPE_TO_TABLE.get(content_type)
    if not table:
        return []
    db = get_db_session()
    async with db as session:
        # 权限过滤（news 是全平台共享，不走过滤）
        use_filter = False
        if user_id and content_type != "news":
            chk = await session.execute(
                text("SELECT 1 FROM user_content_visible WHERE user_id = :uid AND content_type = :ct LIMIT 1"),
                {"uid": user_id, "ct": content_type}
            )
            has_perms = chk.fetchone() is not None
            require_perms = os.environ.get("REQUIRE_PERMISSIONS", "false").lower() == "true"
            if require_perms:
                use_filter = True  # 生产模式：有权限才推荐，无权限返回空
            else:
                use_filter = has_perms  # 调试模式：该类型有权限就过滤，没有就返回全量

        if use_filter:
            r = await session.execute(
                text(f"""
                    SELECT t.* FROM {table} t
                    INNER JOIN user_content_visible v ON t.origin_id = v.origin_id
                    WHERE t.status='active' AND t.has_vector = TRUE
                    AND v.user_id = :uid AND v.content_type = :ct
                    ORDER BY t.id
                """),
                {"uid": user_id, "ct": content_type}
            )
        else:
            r = await session.execute(
                text(f"SELECT * FROM {table} WHERE status='active' AND has_vector = TRUE ORDER BY id")
            )
        rows = r.fetchall()
        if not rows:
            return []
        first_mapping = rows[0]._mapping
        columns = list(first_mapping.keys())
        candidates = []
        for row in rows:
            item = dict(row._mapping)
            item["content_id"] = str(item.get("origin_id", item.get("id", "")))
            item["content_type"] = content_type
            item["title"] = item.get("name") or item.get("title", "")
            for k, v in list(item.items()):
                if hasattr(v, 'isoformat'):
                    item[k] = v.isoformat()
            # 清掉之前内存 compare 用的临时字段
            item.pop("_sim", None)
            candidates.append(item)
        return candidates


async def get_field_importance(table_name: str) -> dict:
    db = get_db_session()
    async with db as session:
        r = await session.execute(
            text("SELECT field_name, field_label, importance, description, weight FROM field_importance WHERE table_name = :tbl ORDER BY importance DESC"),
            {"tbl": table_name}
        )
        rows = r.fetchall()
        result = {}
        for row in rows:
            result[row[0]] = {
                "field_label": row[1],
                "importance": row[2],
                "description": row[3],
                "weight": row[4],
            }
        return result


# ══════════════════════════════════════════════
# pgvector 向量检索 — 连接池复用，避免每次请求新建连接
# ══════════════════════════════════════════════

_pool = None

# 连接池大小 — 384核机器只用了6核，放大连接池匹配高并发
# 注意：不要超过 PG 的 max_connections（默认100）
_POOL_MIN = int(os.environ.get("PGPOOL_MIN", "2"))
_POOL_MAX = int(os.environ.get("PGPOOL_MAX", "6"))
_PG_DSN = os.environ.get("PGPOOL_DSN", "dbname=recommend_agent host=/tmp")


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg2 import pool
        _pool = pool.ThreadedConnectionPool(_POOL_MIN, _POOL_MAX, _PG_DSN)
        logger.info(f"psycopg2 连接池已创建 (min={_POOL_MIN}, max={_POOL_MAX}, dsn={_PG_DSN[:40]})")
    return _pool


async def vector_search(
    user_vector_text: str,
    content_type: str,
    top_k: int = PRE_SCREEN_LIMIT,
    user_vector: list[float] | None = None,
) -> dict[str, float]:
    """
    用 pgvector 做近似最近邻搜索。
    psycopg2 同步查询 → run_in_executor，连接池复用避免反复新建。

    user_vector: 可传入已编码好的用户向量（列表），复用一次编码结果，
                 避免每个 content_type 都重新调用 BGE 编码同一用户文本。
    """
    import asyncio

    # 复用已编码的用户向量，避免重复 BGE 编码（同一请求内用户向量固定）
    user_vec = user_vector if user_vector is not None else await encode_text_async(user_vector_text)
    vec_str = f"[{','.join(f'{v:.6f}' for v in user_vec)}]"
    pool = _get_pool()

    def _do_search():
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            # IVFFlat probes: 确保扫描足够比例的列表，避免漏掉低密度 content_type 的向量
            # lists=5, probes=3 → 扫描 60% 数据，对于 62 条/类型足够覆盖 LIMIT 30
            cur.execute("SET ivfflat.probes = 3")
            cur.execute(
                "SELECT content_id, 1 - (embedding <=> %s::vector) AS similarity "
                "FROM content_vectors WHERE content_type = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (vec_str, content_type, vec_str, top_k)
            )
            rows = cur.fetchall()
            cur.close()
            return rows
        finally:
            pool.putconn(conn)

    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, _do_search)

    sim_map = {}
    for row in rows:
        cid = str(row[0])
        sim = float(row[1])
        if sim >= SIMILARITY_THRESHOLD:
            sim_map[cid] = sim
    return sim_map


async def pre_screen_candidates(
    all_candidates: list[dict],
    field_importance: dict,
    max_keep: int = PRE_SCREEN_LIMIT,
    user_vector_text: str = "",
    user_vector: list[float] | None = None,
) -> list[dict]:
    """
    用 pgvector 检索结果对全量候选做初筛。
    命中向量检索的 + 少量未命中兜底。
    user_vector: 可传入预编码的用户向量，供所有类型复用，避免重复 BGE 编码。
    """
    if not all_candidates:
        return []

    ct = all_candidates[0].get("content_type", "")

    # 始终做向量检索（数据量少时也需要 _sim 供降级评分使用）
    sim_map = await vector_search(user_vector_text, ct, max_keep, user_vector=user_vector)

    relevant = []
    for c in all_candidates:
        cid = str(c.get("content_id", ""))
        if cid in sim_map:
            c["_sim"] = sim_map[cid]
            relevant.append(c)

    relevant.sort(key=lambda x: x.get("_sim", 0), reverse=True)

    # 兜底：少量未命中的
    hit_ids = {c.get("content_id") for c in relevant}
    unhit = [c for c in all_candidates if c.get("content_id") not in hit_ids]
    diversity_count = min(len(unhit), max(1, max_keep // 4))
    result = relevant[:max_keep - diversity_count] + unhit[:diversity_count]

    # 数据量少时，不管检索结果如何，返回全部（带 _sim）
    if len(all_candidates) <= max_keep:
        for c in all_candidates:
            if "_sim" not in c:
                c["_sim"] = 0.0
        result = all_candidates

    logger.info(f"初筛(pgvector): {len(all_candidates)} → {len(result)} 条 "
                f"(命中{len(relevant)}, 兜底{diversity_count})")
    return result


# ══════════════════════════════════════════════
# 向量一致性检查
# ══════════════════════════════════════════════

async def get_missing_vector_ids(content_type: str) -> list[str]:
    """找出有内容但缺少向量的 origin_id 列表"""
    table = TYPE_TO_TABLE.get(content_type)
    if not table:
        return []
    db = get_db_session()
    async with db as session:
        r = await session.execute(
            text(f"""
                SELECT origin_id FROM {table} t
                WHERE t.status = 'active'
                  AND t.origin_id NOT IN (
                    SELECT content_id FROM content_vectors WHERE content_type = :ct
                  )
            """),
            {"ct": content_type}
        )
        return [str(row[0]) for row in r.fetchall()]


async def repair_missing_vectors(content_type: str) -> int:
    """为缺少向量的内容补生成向量"""
    import psycopg2
    missing_ids = await get_missing_vector_ids(content_type)
    if not missing_ids:
        return 0

    field_imp = await get_field_importance(TYPE_TO_TABLE.get(content_type, ""))
    if not field_imp:
        return 0

    # 拉内容
    db = get_db_session()
    async with db as session:
        table = TYPE_TO_TABLE[content_type]
        placeholders = ",".join(f":id{i}" for i in range(len(missing_ids)))
        r = await session.execute(
            text(f"SELECT * FROM {table} WHERE origin_id IN ({placeholders})"),
            {f"id{i}": cid for i, cid in enumerate(missing_ids)}
        )
        rows = r.fetchall()
        if not rows:
            return 0
        columns = list(rows[0]._mapping.keys())
        items = []
        for row in rows:
            item = dict(row._mapping)
            item["title"] = item.get("name") or item.get("title", "")
            items.append(item)

    # 编码写入
    texts = [build_candidate_text(item, field_imp) for item in items]
    vectors = [await encode_text_async(t) for t in texts]

    conn = psycopg2.connect(_PG_DSN)
    cur = conn.cursor()
    repaired = 0
    for item, vec in zip(items, vectors):
        cid = str(item.get("origin_id", ""))
        cur.execute(
            "INSERT INTO content_vectors (content_id, content_type, embedding, cached_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (content_id) DO UPDATE SET embedding=EXCLUDED.embedding, cached_at=NOW()",
            (cid, content_type, vec)
        )
        repaired += 1
    conn.commit()
    cur.close()
    conn.close()

    # 标记内容 has_vector = TRUE
    db = get_db_session()
    async with db as session:
        table = TYPE_TO_TABLE[content_type]
        placeholders = ",".join(f":id{i}" for i in range(len(missing_ids)))
        await session.execute(
            text(f"UPDATE {table} SET has_vector = TRUE WHERE origin_id IN ({placeholders})"),
            {f"id{i}": cid for i, cid in enumerate(missing_ids)}
        )
        await session.commit()

    logger.info(f"向量修复: {content_type} 补了 {repaired} 条")
    return repaired


# ══════════════════════════════════════════════
# 用户文本构建 & 上下文
# ══════════════════════════════════════════════

def build_user_vector_text(profile: dict | None, behaviors: list[dict]) -> str:
    parts = []
    if profile:
        base = profile.get("base_tags", {})
        segs = []
        for key, label in [("major", "专业"), ("skills", "技能"), ("education", "学历"), ("college", "毕业院校")]:
            val = base.get(key, "")
            if val:
                if isinstance(val, list):
                    val = " ".join(val)
                segs.append(f"{label}: {val}")
        if segs:
            parts.append(" ".join(segs))
    if behaviors:
        recent = behaviors[:5]
        parts.append("行为记录: " + " ".join(b.get("content", "") for b in recent))
    return " ".join(parts)


def build_candidate_text(item: dict, field_importance: dict) -> str:
    parts = []
    for field, info in field_importance.items():
        if info.get("importance", 0) >= 4:
            val = item.get(field, "")
            if val and str(val).strip():
                parts.append(str(val).strip())
    return " ".join(parts)


async def get_user_click_preferences(user_id: str) -> dict:
    """查询用户历史点击偏好: {content_type: click_count}"""
    db = get_db_session()
    async with db as session:
        r = await session.execute(
            text("""
                SELECT content_type, COUNT(*) as cnt
                FROM recommend_log
                WHERE user_id = :uid AND event_type = 'click'
                GROUP BY content_type
                ORDER BY cnt DESC
            """),
            {"uid": user_id}
        )
        rows = r.fetchall()
        return {str(row[0]): int(row[1]) for row in rows}


def build_user_context(profile: dict | None, behaviors: list[dict], context_text: str) -> str:
    parts = []
    if profile:
        base = profile.get("base_tags", {})
        segments = []
        for key, label in [("name", "姓名"), ("education", "学历"), ("major", "专业"),
                           ("skills", "技能"), ("college", "毕业院校"), ("age_group", "年龄段")]:
            val = base.get(key, "")
            if val:
                if isinstance(val, list): val = ", ".join(val)
                segments.append(f"{label}: {val}")
        parts.append("【用户基础画像】\n" + " | ".join(segments))
    else:
        parts.append("【用户信息】未找到用户画像")
    if behaviors:
        bmap = {"browsing": "浏览", "search": "搜索", "learning": "学习"}
        parts.append("【用户历史行为记录】\n" + "\n".join(
            f"- [{bmap.get(b['type'], b['type'])}] {b['content']}" for b in behaviors[:15]
        ))
    parts.append(f"【当前浏览/搜索内容】{context_text}")
    return "\n\n".join(parts)
