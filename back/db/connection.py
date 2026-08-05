"""数据库连接管理 — asyncpg + SQLAlchemy 异步引擎"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import DATABASE_URL

# mysql/postgresql:// → postgresql+asyncpg://
_async_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# 多 worker 模式下，每 worker 分担连接数，避免超 PG max_connections(100)
# 8 workers × (async 6 + psycopg2 6) = 96 ≤ 100
_ASYNC_POOL_SIZE = int(os.environ.get("ASYNC_POOL_SIZE", "3"))
_ASYNC_MAX_OVERFLOW = int(os.environ.get("ASYNC_MAX_OVERFLOW", "3"))

engine = create_async_engine(
    _async_url,
    pool_size=_ASYNC_POOL_SIZE,
    max_overflow=_ASYNC_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[empty-body]
    """FastAPI 依赖注入: async with get_db() as db"""
    async with AsyncSessionLocal() as session:
        yield session


def get_db_session() -> AsyncSession:
    """获取异步会话 (用于后台任务)"""
    return AsyncSessionLocal()
