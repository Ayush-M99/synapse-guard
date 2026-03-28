"""
Abstract interfaces for DARWIN components
All components depend on these interfaces, not concrete implementations
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class IKubernetesClient(ABC):
    """Interface for Kubernetes operations"""

    @abstractmethod
    async def delete_pod(
        self, namespace: str, pod_name: str, grace_period_seconds: int = 0
    ) -> bool:
        """Delete a pod immediately"""
        pass

    @abstractmethod
    async def get_pod_status(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Get pod current status"""
        pass

    @abstractmethod
    async def list_pods(
        self, namespace: str, label_selector: str = ""
    ) -> List[Dict[str, Any]]:
        """List pods in namespace"""
        pass

    @abstractmethod
    async def scale_deployment(
        self, namespace: str, deployment_name: str, replicas: int
    ) -> bool:
        """Scale deployment to N replicas"""
        pass

    @abstractmethod
    async def create_network_policy(
        self, namespace: str, policy_name: str, policy_spec: Dict
    ) -> bool:
        """Create network policy to block traffic"""
        pass

    @abstractmethod
    async def delete_network_policy(self, namespace: str, policy_name: str) -> bool:
        """Delete network policy"""
        pass


class IMessageBus(ABC):
    """Interface for NATS pub/sub message bus"""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to NATS server"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from NATS server"""
        pass

    @abstractmethod
    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish message to channel"""
        pass

    @abstractmethod
    async def subscribe(
        self, channel: str, callback: callable
    ) -> None:
        """Subscribe to channel with callback"""
        pass

    @abstractmethod
    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from channel"""
        pass


class ICacheStore(ABC):
    """Interface for Redis cache"""

    @abstractmethod
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get value from cache"""
        pass

    @abstractmethod
    async def set(self, key: str, value: Dict[str, Any], ttl_seconds: int = 86400) -> bool:
        """Set value in cache with TTL"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        pass

    @abstractmethod
    async def increment(self, key: str, delta: int = 1) -> int:
        """Increment counter"""
        pass


class IKnowledgeGraph(ABC):
    """Interface for Neo4j knowledge graph"""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to Neo4j"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from Neo4j"""
        pass

    @abstractmethod
    async def store_failure_recovery(
        self, failure_signature: Dict[str, Any], recovery: Dict[str, Any]
    ) -> str:
        """Store failure->recovery relationship, return node ID"""
        pass

    @abstractmethod
    async def retrieve_similar_failures(
        self, failure_signature: Dict[str, Any], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Find similar past failures using vector similarity"""
        pass

    @abstractmethod
    async def get_failure_recovery_count(self) -> int:
        """Get total failure->recovery relationships in graph"""
        pass
