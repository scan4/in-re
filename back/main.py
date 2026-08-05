"""FastAPI 服务入口 — V2: LLM打分推荐引擎，分内容类型建表"""
import os
import logging
import asyncio
import concurrent.futures
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import API_PORT, LOG_LEVEL
from api.recommend import router as recommend_router
from api.llm_config import router as llm_config_router

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# 线程池 — 替换 Python 默认的 32 线程上限
# 当前机器 384 核仅用 ~6 核，空余 ~378 核，全拿来用
_THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", "256"))
THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=_THREAD_POOL_SIZE,
    thread_name_prefix="bge-worker"
)
logger.info(f"线程池已创建: max_workers={_THREAD_POOL_SIZE}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """异步生命周期: 启动 → 注册定时同步任务 → 关闭时清理"""
    # 替换默认 executor → 所有 asyncio.to_thread / run_in_executor(None) 都会用这个池
    loop = asyncio.get_running_loop()
    loop.set_default_executor(THREAD_POOL)
    logger.info(f"默认线程池已替换: {_THREAD_POOL_SIZE} workers (原 32)")

    logger.info("========== 推荐 Agent V2 启动 (LLM打分 + 分表架构) ==========")
    logger.info("FastAPI → SQLAlchemy[async] → asyncpg → PostgreSQL")

    # 启动定时同步
    try:
        from sync.scheduler import start_scheduler, stop_scheduler, run_all_sync_now
        await run_all_sync_now()
        start_scheduler()
    except Exception as e:
        logger.warning(f"同步调度器启动失败（不影响推荐服务）: {e}")

    yield

    try:
        from sync.scheduler import stop_scheduler as stop_sched
        stop_sched()
    except Exception:
        pass
    logger.info("========== 推荐 Agent V2 关闭 ==========")
    THREAD_POOL.shutdown(wait=True)


app = FastAPI(
    title="智能推荐 Agent V2",
    description="V2: 分内容类型建表 + 字段重要性分级 + LLM打分排序",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend_router)
app.include_router(llm_config_router)


@app.get("/api/v1/health")
async def health_check():
    """健康检查"""
    from db.connection import engine
    from sqlalchemy import text as sa_text
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok",
        "version": "3.0.0",
        "architecture": "V2: LLM打分 + 分内容类型独立表 + 字段重要性分级",
        "checks": {"database": db_status}
    }


@app.get("/api/v1/sync/trigger")
async def trigger_sync():
    """手动触发全量同步 — V2 写入新表"""
    from sync.content_sync_v2 import sync_all_content
    from sync.behavior_sync_v2 import sync_behavior

    behavior = await sync_behavior()
    content = await sync_all_content()

    return {
        "behavior": {
            "status": behavior["status"],
            "records": sum(behavior["by_category"].values()),
            "by_category": behavior["by_category"]
        },
        "content": {
            "success": content["success"],
            "failed": content["failed"],
            "total": content["total"],
        },
    }


if __name__ == "__main__":
    workers = int(os.environ.get("UVICORN_WORKERS", "8"))
    logger.info(f"uvicorn 启动: workers={workers}, port={API_PORT}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_PORT,
        workers=workers,
        reload=False,
        log_level=LOG_LEVEL,
    )
