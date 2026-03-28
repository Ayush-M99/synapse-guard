"""
DARWIN data models and dataclasses
"""

from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import json


@dataclass
class ServiceTarget:
    """Target service for attack injection"""

    namespace: str
    service_name: str
    pod_name: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class AttackResult:
    """Result of attack injection"""

    success: bool
    attack_id: str
    target_service: str
    timestamp: datetime
    error: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class FailureSignature:
    """7-feature telemetry vector representing system state"""

    cpu_usage: float  # 0-4 (CPUs)
    memory_mb: int  # 64-2048 MB
    error_rate: float  # 0-1 (0% - 100%)
    latency_p99_ms: int  # 10-10000 ms
    pod_restarts: int  # 0-10
    network_rx_mbps: int  # 0-100 Mbps
    network_tx_mbps: int  # 0-100 Mbps
    service: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_array(self) -> List[float]:
        """Convert to numpy-compatible array"""
        return [
            self.cpu_usage,
            self.memory_mb,
            self.error_rate,
            self.latency_p99_ms,
            self.pod_restarts,
            self.network_rx_mbps,
            self.network_tx_mbps,
        ]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class DetectionResult:
    """Result of ML detection pipeline"""

    is_anomaly: bool
    anomaly_score: float  # 0-1, from CUSUM
    isolated_service: Optional[str]  # Service identified by IF
    attack_family: Optional[str]  # Classification from RF
    attack_family_confidence: float  # 0-1, from RF
    predicted_recovery: Optional[str]  # From LSTM
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class Recovery:
    """Recovery strategy and actions"""

    recovery_id: str
    actions: List[Dict[str, Any]]  # List of {type, target, ...}
    success_rate: float  # 0-1
    avg_recovery_time_seconds: float
    tier_used: str  # "cache", "retrieval", "generation", "emergency"
    confidence: float = 0.5
    generation: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Recovery":
        return Recovery(**data)


@dataclass
class RecoveryOutcome:
    """Result of recovery execution"""

    successful: bool
    recovery_time_seconds: float
    actions_executed: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
