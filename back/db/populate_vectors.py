"""
向量预计算脚本 — 将全部现有内容编码为 BGE 向量存入 content_vectors 表
"""
import os
import asyncio
import logging
from sqlalchemy import text
from pgvector.sqlalchemy import Vector
import psycopg2

# Docker 环境下用 PGPOOL_DSN 连接 postgres 容器；本机开发回退到 socket
_PG_DSN = os.environ.get("PGPOOL_DSN", "dbname=recommend_agent host=/tmp")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def populate_vectors():
    from db.connection import get_db_session
    from engine.data_repo import get_all_candidates, get_field_importance, build_candidate_text, TYPE_TO_TABLE
    from engine.embedding import encode_batch

    logger.info("========== 开始向量预计算 ==========")

    total = 0
    for content_type in TYPE_TO_TABLE:
        candidates = await get_all_candidates(content_type)
        if not candidates:
            logger.info(f"  {content_type}: 无候选内容")
            continue

        field_imp = await get_field_importance(TYPE_TO_TABLE[content_type])
        texts = [build_candidate_text(c, field_imp) for c in candidates]
        vectors = encode_batch(texts)

        # 用 psycopg2 原生写入向量（SQLAlchemy 不能直接传 list 给 vector 类型）
        conn = psycopg2.connect(_PG_DSN)
        cur = conn.cursor()
        for c, vec in zip(candidates, vectors):
            cid = str(c.get("content_id", ""))
            cur.execute(
                "INSERT INTO content_vectors (content_id, content_type, embedding, cached_at) "
                "VALUES (%s, %s, %s, NOW()) "
                "ON CONFLICT (content_id) DO UPDATE SET embedding=EXCLUDED.embedding, cached_at=NOW()",
                (cid, content_type, vec)
            )
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"  {content_type}: {len(candidates)} 条向量入库")
        total += len(candidates)

    logger.info(f"========== 向量预计算完成: 共 {total} 条 ==========")
    return total


def build_ivfflat_index():
    """当数据量足够时重建 IVFFlat 索引"""
    conn = psycopg2.connect(_PG_DSN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM content_vectors")
    count = cur.fetchone()[0]
    if count >= 100:
        cur.execute("DROP INDEX IF EXISTS idx_content_embedding")
        cur.execute(
            "CREATE INDEX idx_content_embedding ON content_vectors "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
        )
        conn.commit()
        logger.info(f"IVFFlat 索引重建完成 ({count} 条数据)")
    else:
        logger.info(f"数据量 {count} < 100，暂不重建 IVFFlat 索引")
    cur.close()
    conn.close()


if __name__ == "__main__":
    asyncio.run(populate_vectors())
    build_ivfflat_index()
