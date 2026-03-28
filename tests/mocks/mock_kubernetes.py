"""
Mock Kubernetes Client for testing
Tracks pod deletions, scaling, etc. without real Kubernetes
"""

from typing import Optional, List, Dict, Any
from core.interfaces import IKubernetesClient
import uuid


class MockKubernetesClient(IKubernetesClient):
    """Mock implementation of Kubernetes client for testing"""

    def __init__(self):
        self.deleted_pods = []
        self.scaled_deployments = []
        self.created_network_policies = []
        self.deleted_network_policies = []
        self.pods = {}
        self._init_test_pods()

    def _init_test_pods(self):
        """Initialize test pods"""
        for service in ["payment", "auth", "order", "inventory", "gateway", "notification"]:
            pod_name = f"{service}-service-{uuid.uuid4().hex[:8]}"
            self.pods[pod_name] = {
                "name": pod_name,
                "namespace": "darwin-target",
                "service": f"{service}-service",
                "status": "Running",
                "restarts": 0,
            }

    async def delete_pod(
        self, namespace: str, pod_name: str, grace_period_seconds: int = 0
    ) -> bool:
        """Delete a pod (mock)"""
        self.deleted_pods.append(
            {"namespace": namespace, "pod_name": pod_name, "timestamp": str(__import__("datetime").datetime.utcnow())}
        )

        # Simulate pod deletion
        if pod_name in self.pods:
            del self.pods[pod_name]

        # Create replacement pod
        service = pod_name.rsplit("-", 2)[0]
        new_pod_name = f"{service}-{uuid.uuid4().hex[:8]}"
        self.pods[new_pod_name] = {
            "name": new_pod_name,
            "namespace": namespace,
            "service": service,
            "status": "Running",
            "restarts": 0,
        }

        return True

    async def get_pod_status(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Get pod status (mock)"""
        if pod_name in self.pods:
            return self.pods[pod_name]
        return {"status": "NotFound"}

    async def list_pods(
        self, namespace: str, label_selector: str = ""
    ) -> List[Dict[str, Any]]:
        """List pods in namespace (mock)"""
        pods = [p for p in self.pods.values() if p["namespace"] == namespace]

        if label_selector:
            # Simple label filtering
            service = label_selector.split("=")[-1]
            pods = [p for p in pods if service in p["service"]]

        return pods

    async def scale_deployment(
        self, namespace: str, deployment_name: str, replicas: int
    ) -> bool:
        """Scale deployment (mock)"""
        self.scaled_deployments.append(
            {
                "namespace": namespace,
                "deployment": deployment_name,
                "replicas": replicas,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )
        return True

    async def create_network_policy(
        self, namespace: str, policy_name: str, policy_spec: Dict
    ) -> bool:
        """Create network policy (mock)"""
        self.created_network_policies.append(
            {
                "namespace": namespace,
                "policy_name": policy_name,
                "spec": policy_spec,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )
        return True

    async def delete_network_policy(self, namespace: str, policy_name: str) -> bool:
        """Delete network policy (mock)"""
        self.deleted_network_policies.append(
            {
                "namespace": namespace,
                "policy_name": policy_name,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )
        return True

    def get_operations_history(self) -> Dict[str, Any]:
        """Get history of all operations for testing"""
        return {
            "deleted_pods": self.deleted_pods,
            "scaled_deployments": self.scaled_deployments,
            "created_policies": self.created_network_policies,
            "deleted_policies": self.deleted_network_policies,
        }

    def reset(self):
        """Reset mock state"""
        self.deleted_pods = []
        self.scaled_deployments = []
        self.created_network_policies = []
        self.deleted_network_policies = []
        self.pods = {}
        self._init_test_pods()
