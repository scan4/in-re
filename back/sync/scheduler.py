"""定时任务调度器 — V2: 分表同步"""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sync.content_sync_v2 import sync_all_content
from sync.behavior_sync_v2 import sync_behavior
from config import SYNC_INTERVAL_CONTENT, SYNC_INTERVAL_BEHAVIOR

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler():
    """启动定时同步任务 — V2 写入分表"""
    scheduler.add_job(
        sync_all_content,
        trigger="interval",
        minutes=SYNC_INTERVAL_CONTENT,
        id="content_sync",
        name="内容数据同步"
    )
    logger.info(f"定时任务: 内容同步 (每 {SYNC_INTERVAL_CONTENT} 分钟) → 分表写入")

    scheduler.add_job(
        sync_behavior,
        trigger="interval",
        minutes=SYNC_INTERVAL_BEHAVIOR,
        id="behavior_sync",
        name="用户行为同步"
    )
    logger.info(f"定时任务: 行为同步 (每 {SYNC_INTERVAL_BEHAVIOR} 分钟) → user_behaviors 表")

    scheduler.start()
    logger.info("AsyncIOScheduler 已启动")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("调度器已停止")


async def run_all_sync_now():
    """启动时执行首次全量同步"""
    logger.info(">>> [V2] 首次全量同步 <<<")
    try:
        b = await sync_behavior()
        logger.info(f"行为: {b['status']}, {sum(b['by_category'].values())} 条")
    except Exception as e:
        logger.error(f"首次行为同步失败: {e}")

    try:
        c = await sync_all_content()
        logger.info(f"内容: {c['success']}/{len(c['details'])}, 共 {c['total']} 条")
    except Exception as e:
        logger.error(f"首次内容同步失败: {e}")

    logger.info(">>> [V2] 首次同步完成 <<<")
