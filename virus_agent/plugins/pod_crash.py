"""
Pod Crash Attack - Generation 1
Simplest attack: immediately delete a pod
Pod will be recreated by Kubernetes automatically
"""

import logging
from kubernetes import client, config
from base import AttackPlugin, AttackResult


logger = logging.getLogger("virus-agent.pod-crash")


class PodCrashAttack(AttackPlugin):
    """Delete a pod immediately - Generation 1 (obvious)"""

    def __init__(self):
        self.v1 = client.CoreV1Api()
        self.logger = logger

    def get_attack_id(self) -> str:
        return "pod_crash"

    def get_description(self) -> str:
        return "Immediately kill a pod - Generation 1 (obvious attack)"

    def get_generation(self) -> int:
        return 1

    async def execute_attack(
        self, namespace: str, target_service: str
    ) -> AttackResult:
        """Delete a random pod from the target service"""

        try:
            # Get all pods for this service
            pods = self.v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app={target_service}"
            )

            if not pods.items:
                return AttackResult(
                    success=False,
                    attack_id="pod_crash",
                    target_service=target_service,
                    error=f"No pods found for {target_service}",
                )

            # Delete the first pod
            target_pod = pods.items[0].metadata.name
            self.logger.info(f"Killing pod: {target_pod}")

            self.v1.delete_namespaced_pod(
                name=target_pod,
                namespace=namespace,
                grace_period_seconds=0  # Immediate termination
            )

            self.logger.info(f"Pod crashed: {target_pod}")

            return AttackResult(
                success=True,
                attack_id="pod_crash",
                target_service=target_service,
                target_pod=target_pod,
                message=f"Crashed pod {target_pod}",
                generation=1,
            )

        except Exception as e:
            self.logger.error(f"Pod crash attack failed: {e}")
            return AttackResult(
                success=False,
                attack_id="pod_crash",
                target_service=target_service,
                error=str(e),
            )

    async def cleanup(self, namespace: str, target_service: str) -> bool:
        """No cleanup needed - pod recreates automatically"""
        return True
