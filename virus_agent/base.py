"""
Virus Agent - DARWIN Chaos Injection System
Base classes and interfaces for attack plugins
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
import json


@dataclass
class AttackResult:
    """Result of attack injection"""

    success: bool
    attack_id: str
    target_service: str
    target_pod: Optional[str] = None
    timestamp: datetime = None
    error: Optional[str] = None
    message: Optional[str] = None
    generation: int = 1

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "attack_id": self.attack_id,
            "target_service": self.target_service,
            "target_pod": self.target_pod,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "message": self.message,
            "generation": self.generation,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class AttackPlugin(ABC):
    """
    Abstract base class for all attack plugins

    Each attack family implements this interface to be discovered and loaded
    by the plugin registry.
    """

    @abstractmethod
    def get_attack_id(self) -> str:
        """
        Unique identifier for this attack

        Examples: "pod_crash", "network_latency", "resource_pressure"
        """
        pass

    @abstractmethod
    def get_description(self) -> str:
        """Human-readable description of the attack"""
        pass

    @abstractmethod
    def get_generation(self) -> int:
        """
        Generation level (1, 2, or 3)

        1 = Obvious/detectable attack
        2 = Moderate/harder to detect
        3 = Stealthy/very hard to detect (camouflage)
        """
        pass

    @abstractmethod
    async def execute_attack(
        self, namespace: str, target_service: str
    ) -> AttackResult:
        """
        Execute the attack against the target service

        Args:
            namespace: Kubernetes namespace (e.g., "darwin-target")
            target_service: Service name (e.g., "payment-service")

        Returns:
            AttackResult with success/failure status
        """
        pass

    @abstractmethod
    async def cleanup(self, namespace: str, target_service: str) -> bool:
        """
        Clean up attack artifacts (optional)

        Some attacks need cleanup (e.g., removing NetworkPolicies).
        Others don't (e.g., pod crash - pod recreates automatically).

        Args:
            namespace: Kubernetes namespace
            target_service: Service name

        Returns:
            True if cleanup succeeded
        """
        pass
