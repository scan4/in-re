"""外部接口适配层 — 异步调用 6 个业务 API"""
import asyncio
import logging
import httpx
from config import JWT_TOKEN, EXTERNAL_API_BASE
from utils.enums import API_TYPES

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5
TIMEOUT = 30


class ExternalApiError(Exception):
    pass


def build_url(api_type: str, token: str = "") -> str:
    type_param = API_TYPES[api_type]
    _token = token or JWT_TOKEN
    return f"{EXTERNAL_API_BASE}index/types/{type_param}/tokens/{_token}"


async def fetch_api_data(api_type: str, token: str = "") -> dict:
    """异步调用外部接口，返回 msgs 中的业务数据。token 为空时使用全局 JWT_TOKEN"""
    url = build_url(api_type, token)
    logger.info(f"调用外部接口: {api_type}")

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                states = data.get("states", "")
                codes = data.get("codes", 0)
                codes = int(codes) if isinstance(codes, str) else codes
                msgs = data.get("msgs", [])

                if states != "ok":
                    raise ExternalApiError(f"states={states}, 预期 ok")
                if codes != 500:
                    raise ExternalApiError(f"codes={codes}, 预期 500")

                record_count = len(msgs) if isinstance(msgs, (list, dict)) else 0
                logger.info(f"接口 {api_type} 成功: {record_count} 条")
                return {
                    "api_type": api_type,
                    "records": msgs,
                    "count": record_count
                }

        except (httpx.TimeoutException, ExternalApiError) as e:
            last_error = e
            logger.warning(f"接口 {api_type} 第 {attempt}/{MAX_RETRIES} 次失败: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
        except httpx.HTTPStatusError as e:
            last_error = e
            logger.error(f"接口 {api_type} HTTP 错误: {e.response.status_code}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            last_error = e
            logger.error(f"接口 {api_type} 未知错误: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    raise ExternalApiError(f"接口 {api_type} 重试 {MAX_RETRIES} 次后仍失败: {last_error}")


async def fetch_all_apis(api_types: list[str] | None = None, token: str = "") -> dict[str, dict]:
    """批量异步调用多个接口。

    注意：这里**串行**逐个调用，而不是并发（asyncio.gather）。
    原因：外部接口对并发连接有限流/不稳定，并发时部分接口会超时被丢弃，
    导致权限同步（_sync_user_permissions）漏掉 training/career 等类型。
    串行 + 每个接口内部自带重试，牺牲少量速度换取类型完整、稳定。
    token 为空时使用全局 JWT_TOKEN。
    """
    if api_types is None:
        api_types = list(API_TYPES.keys())

    async def _safe_fetch(t: str):
        try:
            return await fetch_api_data(t, token=token)
        except ExternalApiError as e:
            logger.error(f"接口 {t} 失败: {e}")
            return {"api_type": t, "records": [], "count": 0, "error": str(e)}

    results = {}
    for t in api_types:
        # 串行逐个调用；每个接口内部已有 MAX_RETRIES 重试
        r = await _safe_fetch(t)
        results[t] = r
        # 轻微间隔，避免触发外部接口的突发限流
        await asyncio.sleep(0.5)
    return results
