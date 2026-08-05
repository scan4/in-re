"""熔断器 — LLM 不可用时自动降级"""
import time
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 10, recovery_timeout: float = 30.0):
        self.state = State.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0.0

    async def call(self, coro):
        """包装异步调用，自动熔断"""
        if self.state == State.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = State.HALF_OPEN
                logger.info("熔断器: HALF_OPEN → 尝试恢复")
            else:
                logger.warning("熔断器 OPEN: 拒绝调用")
                raise CircuitOpenError("熔断器已打开，使用降级策略")

        try:
            result = await coro
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        if self.state == State.HALF_OPEN:
            logger.info("熔断器: HALF_OPEN 调用成功 → CLOSED")
        self.state = State.CLOSED
        self.failure_count = 0

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = State.OPEN
            logger.warning(f"熔断器: 连续失败 {self.failure_count} 次 → OPEN")


# 全局单例
llm_breaker = CircuitBreaker(failure_threshold=10, recovery_timeout=30.0)
