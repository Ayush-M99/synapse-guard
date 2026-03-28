"""
DARWIN Core Module - Shared interfaces, models, and utilities
"""

from .interfaces import (
    IKubernetesClient,
    IMessageBus,
    ICacheStore,
    IKnowledgeGraph,
)

from .models import (
    AttackResult,
    DetectionResult,
    Recovery,
    RecoveryOutcome,
    ServiceTarget,
    FailureSignature,
)

from .circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenError
from .health import ComponentHealthCheck

__all__ = [
    "IKubernetesClient",
    "IMessageBus",
    "ICacheStore",
    "IKnowledgeGraph",
    "AttackResult",
    "DetectionResult",
    "Recovery",
    "RecoveryOutcome",
    "ServiceTarget",
    "FailureSignature",
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenError",
    "ComponentHealthCheck",
]
