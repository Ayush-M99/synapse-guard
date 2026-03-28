"""
Data models for Antibody Agent
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime
import json


class RAGTier(Enum):
    """Which RAG tier was used for recovery"""
    REDIS = "redis"           # Tier 1: Cache hit (0.8s)
    NEO4J = "neo4j"          # Tier 2: Graph retrieval (2s)
    POSTGRES = "postgres"    # Tier 3: DNA store (18s)
    LLM = "llm"              # Tier 3+: LLM generation
    EMERGENCY = "emergency"  # Hardcoded fallback


class RecoveryActionType(Enum):
    """Types of recovery actions"""
    RESTART_POD = "restart_pod"
    SCALE_REPLICAS = "scale_replicas"
    APPLY_NETWORK_POLICY = "apply_network_policy"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RATE_LIMIT = "rate_limit"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class FailureEvent:
    """Failure event from ML Pipeline"""
    service: str
    attack_family: str
    rf_confidence: float
    anomaly_score: float
    detection_path: str  # "cusum", "isolation_forest", "lstm"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ml_pipeline_version: str = "1.0"

    def to_dict(self) -> Dict:
        return {
            "service": self.service,
            "attack_family": self.attack_family,
            "rf_confidence": self.rf_confidence,
            "anomaly_score": self.anomaly_score,
            "detection_path": self.detection_path,
            "timestamp": self.timestamp.isoformat(),
            "ml_pipeline_version": self.ml_pipeline_version,
        }


@dataclass
class RecoveryAction:
    """Single recovery action to execute"""
    action_type: RecoveryActionType
    target_service: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # 1=critical, 3=low
    rollback_on_failure: bool = True

    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type.value,
            "target_service": self.target_service,
            "parameters": self.parameters,
            "priority": self.priority,
            "rollback_on_failure": self.rollback_on_failure,
        }


@dataclass
class RecoveryPlaybook:
    """Set of recovery actions for a failure signature"""
    playbook_id: str
    actions: List[RecoveryAction]
    attack_family: str
    success_rate: float
    avg_recovery_time_ms: float
    execution_count: int = 0
    generation: int = 1
    rag_tier: RAGTier = RAGTier.POSTGRES
    confidence: float = 0.8
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "playbook_id": self.playbook_id,
            "actions": [action.to_dict() for action in self.actions],
            "attack_family": self.attack_family,
            "success_rate": self.success_rate,
            "avg_recovery_time_ms": self.avg_recovery_time_ms,
            "execution_count": self.execution_count,
            "generation": self.generation,
            "rag_tier": self.rag_tier.value,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }

    @staticmethod
    def from_dict(data: Dict) -> "RecoveryPlaybook":
        actions = [
            RecoveryAction(
                action_type=RecoveryActionType(action["action_type"]),
                target_service=action["target_service"],
                parameters=action.get("parameters", {}),
                priority=action.get("priority", 1),
                rollback_on_failure=action.get("rollback_on_failure", True),
            )
            for action in data.get("actions", [])
        ]
        return RecoveryPlaybook(
            playbook_id=data["playbook_id"],
            actions=actions,
            attack_family=data["attack_family"],
            success_rate=data["success_rate"],
            avg_recovery_time_ms=data["avg_recovery_time_ms"],
            execution_count=data.get("execution_count", 0),
            generation=data.get("generation", 1),
            rag_tier=RAGTier(data.get("rag_tier", "postgres")),
            confidence=data.get("confidence", 0.8),
        )


@dataclass
class RecoveryContext:
    """Context for a recovery operation"""
    failure_event: FailureEvent
    signature_hash: str
    playbook: RecoveryPlaybook
    start_time: datetime = field(default_factory=datetime.utcnow)
    semaphore_acquired: bool = False

    def elapsed_ms(self) -> float:
        """Time elapsed since recovery started"""
        return (datetime.utcnow() - self.start_time).total_seconds() * 1000


@dataclass
class RecoveryOutcome:
    """Result of a recovery operation"""
    success: bool
    recovery_context: RecoveryContext
    recovery_time_ms: float
    actions_executed: int
    actions_failed: int = 0
    error_message: Optional[str] = None
    completion_time: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "service": self.recovery_context.failure_event.service,
            "attack_family": self.recovery_context.failure_event.attack_family,
            "recovery_time_ms": self.recovery_time_ms,
            "actions_executed": self.actions_executed,
            "actions_failed": self.actions_failed,
            "rag_tier": self.recovery_context.playbook.rag_tier.value,
            "cache_hit": self.recovery_context.playbook.rag_tier == RAGTier.REDIS,
            "error_message": self.error_message,
            "timestamp": self.completion_time.isoformat(),
        }


@dataclass
class DNARecord:
    """Generation record for learning loop"""
    virus_gen: int
    antibody_gen: int
    strand_id: str
    strand_family: str
    target_service: str
    injection_ts: datetime
    detection_ts: datetime
    recovery_ts: datetime
    recovery_ms: float
    recovery_actions: List[Dict]
    success: bool
    cache_hit: bool
    rag_source: str  # "redis", "neo4j", "postgres", "llm"
    rf_label: str
    rf_confidence: float
    detection_path: str
    blast_radius_services: int = 1
    error_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
