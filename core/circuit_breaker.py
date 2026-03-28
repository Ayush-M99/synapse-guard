"""
Circuit Breaker pattern for fault tolerance
Prevents cascading failures when components are unavailable
"""

import time
from enum import Enum
from typing import Callable, Any


class CircuitState(Enum):
    """Circuit breaker states"""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, don't call
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreakerOpenError(Exception):
    """Raised when circuit is open"""

    pass


class CircuitBreaker:
    """
    Circuit breaker to isolate failing components

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        try:
            result = await breaker.call(some_async_function, arg1, arg2)
        except CircuitBreakerOpenError:
            # Circuit is open, try alternative
            result = fallback_function()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        half_open_timeout_seconds: int = 30,
    ):
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout_seconds
        self.half_open_timeout = half_open_timeout_seconds
        self.last_failure_time = None
        self.last_success_time = None

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""

        if self.state == CircuitState.OPEN:
            # Check if timeout elapsed
            if (
                self.last_failure_time
                and time.time() - self.last_failure_time > self.timeout
            ):
                self.state = CircuitState.HALF_OPEN
                print(
                    f"[{self.name}] Circuit HALF_OPEN - testing recovery"
                )
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN"
                )

        try:
            result = await func(*args, **kwargs)

            # Success - reset on HALF_OPEN, or just track on CLOSED
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                print(
                    f"[{self.name}] Circuit CLOSED - component recovered"
                )
            else:
                self.failure_count = 0
                self.last_success_time = time.time()

            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                print(
                    f"[{self.name}] Circuit OPEN after {self.failure_count} failures"
                )

            raise e

    def get_state(self) -> Dict[str, Any]:
        """Get circuit breaker status"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
        }

    def reset(self):
        """Manually reset circuit breaker"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        print(f"[{self.name}] Circuit manually reset to CLOSED")


from typing import Dict

__all__ = ["CircuitBreaker", "CircuitState", "CircuitBreakerOpenError"]
