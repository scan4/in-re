"""
重试工具 — 用于同步任务的指数退避重试，区分 DB 故障和业务异常
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 数据库瞬时故障异常（连接超时、死锁、事务冲突等），触发重试
DB_TRANSIENT_ERRORS = ()

# 运行时动态导入，避免在没有 asyncpg/sqlalchemy 时启动报错
def _get_db_retry_errors():
    global DB_TRANSIENT_ERRORS
    if not DB_TRANSIENT_ERRORS:
        try:
            from sqlalchemy.exc import OperationalError, TimeoutError as SATimeout, DisconnectionError
            from asyncpg.exceptions import (
                ConnectionDoesNotExistError, TooManyConnectionsError,
                ConnectionFailureError, IdleSessionTimeoutError,
            )
            DB_TRANSIENT_ERRORS = (
                OperationalError, SATimeout, DisconnectionError,
                ConnectionDoesNotExistError, TooManyConnectionsError,
                ConnectionFailureError, IdleSessionTimeoutError,
            )
        except ImportError:
            DB_TRANSIENT_ERRORS = (Exception,)  # 兜底
    return DB_TRANSIENT_ERRORS


async def retry_async(fn, *args, max_retries: int = 3, base_delay: float = 2.0,
                       retry_on: tuple | None = None, **kwargs):
    """
    异步函数重试，指数退避。
    默认只重试 DB 瞬时故障，不重试 API 异常和业务逻辑异常。

    Args:
        fn: 要重试的异步函数
        max_retries: 最大重试次数（共执行 max_retries 次）
        base_delay: 基础延迟秒数，第n次重试延迟 = base_delay × 2^(n-1)
        retry_on: 指定重试的异常类型，默认自动检测 DB 异常

    Returns:
        fn 的返回值，最后一次失败抛异常
    """
    if retry_on is None:
        retry_on = _get_db_retry_errors()

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retry_on as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(f"重试 {attempt}/{max_retries}: {fn.__name__} 失败 "
                               f"({type(e).__name__}: {e}), {delay}s 后重试")
                await asyncio.sleep(delay)
            else:
                logger.error(f"重试 {attempt}/{max_retries}: {fn.__name__} 最终失败: {e}")
    raise last_error
