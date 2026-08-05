"""Redis 连接 — 异步客户端，用于缓存 LLM 评分结果"""
import os
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
LLM_CACHE_TTL = int(os.environ.get("LLM_CACHE_TTL", "600"))  # 默认 10 分钟

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """获取全局异步 Redis 连接（延迟连接）"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,  # 自动 bytes→str
            max_connections=10,
        )
        await _redis.ping()
        logger.info(f"Redis 已连接: {REDIS_URL}")
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis 已关闭")
