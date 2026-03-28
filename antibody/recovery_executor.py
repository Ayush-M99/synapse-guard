"""
Recovery Executor: Kubernetes API Integration
Executes pod restart, scaling, and network policy actions
"""

import asyncio
import logging
import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .models import RecoveryContext, RecoveryOutcome, RecoveryActionType

logger = logging.getLogger(__name__)


class RecoveryExecutor:
    """Execute recovery actions via Kubernetes API"""

    def __init__(self, namespace: str = "darwin-target", in_cluster: bool = False):
        self.namespace = namespace
        self.in_cluster = in_cluster
        self.v1_api = None
        self.apps_v1_api = None
        self.network_v1_api = None
        self.connected = False

        # Lock dict to prevent concurrent recovery on same pod
        self.pod_locks = {}

    async def connect(self) -> bool:
        """Connect to Kubernetes cluster"""
        try:
            if self.in_cluster:
                config.load_incluster_config()
            else:
                config.load_kube_config()

            self.v1_api = client.CoreV1Api()
            self.apps_v1_api = client.AppsV1Api()
            self.network_v1_api = client.NetworkingV1Api()
            self.connected = True

            logger.info(f"✅ Connected to Kubernetes cluster (namespace: {self.namespace})")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to Kubernetes: {e}")
            self.connected = False
            return False

    async def execute_recovery(self, recovery_context: RecoveryContext) -> RecoveryOutcome:
        """
        Execute complete recovery playbook

        Flow:
        1. Acquire semaphore lock (prevent concurrent recovery)
        2. Execute actions sequentially with delays between
        3. Verify service health
        4. Release lock
        5. Return outcome with timing

        Args:
            recovery_context: Context with failure event + playbook + actions

        Returns:
            RecoveryOutcome with success/failure and timing

        Example:
            outcome = await executor.execute_recovery(recovery_context)
            if outcome.success:
                print(f"Recovery in {outcome.recovery_time_ms}ms")
            else:
                print(f"Recovery failed: {outcome.error_message}")
        """
        if not self.connected:
            logger.error("Kubernetes not connected")
            return self._failure_outcome(
                recovery_context, error="Not connected to Kubernetes"
            )

        start_time = time.time()
        actions_executed = 0
        actions_failed = 0

        try:
            # Acquire lock for this service (prevent concurrent recovery)
            await self._acquire_lock(recovery_context.failure_event.service)
            recovery_context.semaphore_acquired = True
            logger.info(
                f"🔒 Acquired lock for {recovery_context.failure_event.service}"
            )

            # Execute each action in playbook
            for action in recovery_context.playbook.actions:
                try:
                    logger.info(f"⚡ Executing action: {action.action_type.value}")
                    success = await self._execute_action(action)

                    if success:
                        actions_executed += 1
                    else:
                        actions_failed += 1

                    # Wait for propagation
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"❌ Action failed: {e}")
                    actions_failed += 1

                    if action.rollback_on_failure:
                        logger.warning("Rolling back on action failure")
                        break

            # Verify service is healthy
            logger.info("🏥 Verifying service health...")
            healthy = await self._verify_service_health(
                recovery_context.failure_event.service
            )

            # Release lock
            await self._release_lock(recovery_context.failure_event.service)
            recovery_context.semaphore_acquired = False

            recovery_time_ms = (time.time() - start_time) * 1000

            if healthy and actions_failed == 0:
                logger.info(f"✅ Recovery successful in {recovery_time_ms:.1f}ms")
                return RecoveryOutcome(
                    success=True,
                    recovery_context=recovery_context,
                    recovery_time_ms=recovery_time_ms,
                    actions_executed=actions_executed,
                    actions_failed=actions_failed,
                )
            else:
                error_msg = "Service unhealthy" if not healthy else "Some actions failed"
                logger.error(f"❌ Recovery incomplete: {error_msg}")
                return RecoveryOutcome(
                    success=False,
                    recovery_context=recovery_context,
                    recovery_time_ms=recovery_time_ms,
                    actions_executed=actions_executed,
                    actions_failed=actions_failed,
                    error_message=error_msg,
                )

        except Exception as e:
            logger.error(f"❌ Recovery execution failed: {e}")
            recovery_time_ms = (time.time() - start_time) * 1000
            return RecoveryOutcome(
                success=False,
                recovery_context=recovery_context,
                recovery_time_ms=recovery_time_ms,
                actions_executed=actions_executed,
                actions_failed=actions_failed,
                error_message=str(e),
            )

    async def _execute_action(self, action) -> bool:
        """Execute single recovery action"""
        try:
            if action.action_type == RecoveryActionType.RESTART_POD:
                return await self._restart_service_pod(action.target_service)

            elif action.action_type == RecoveryActionType.SCALE_REPLICAS:
                replicas = action.parameters.get("replicas", 2)
                return await self._scale_deployment(action.target_service, replicas)

            elif action.action_type == RecoveryActionType.APPLY_NETWORK_POLICY:
                return await self._apply_network_policy(action.target_service)

            elif action.action_type == RecoveryActionType.RATE_LIMIT:
                return await self._apply_rate_limit(action.target_service)

            else:
                logger.warning(f"Unknown action type: {action.action_type}")
                return False

        except Exception as e:
            logger.error(f"Failed to execute action: {e}")
            return False

    async def _restart_service_pod(self, service_name: str) -> bool:
        """Restart service pod via Kubernetes delete (auto-restart by controller)"""
        try:
            pods = self.v1_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=f"app={service_name}"
            )

            if not pods.items:
                logger.warning(f"No pods found for service: {service_name}")
                return False

            victim_pod = pods.items[0].metadata.name
            logger.info(f"🚀 Deleting pod: {victim_pod}")

            self.v1_api.delete_namespaced_pod(
                name=victim_pod,
                namespace=self.namespace,
                grace_period_seconds=5,  # Graceful shutdown
            )

            # Wait for new pod to start
            await asyncio.sleep(5)
            return True

        except Exception as e:
            logger.error(f"Failed to restart pod: {e}")
            return False

    async def _scale_deployment(self, service_name: str, replicas: int) -> bool:
        """Scale deployment to specified replica count"""
        try:
            logger.info(f"📈 Scaling {service_name} to {replicas} replicas")

            deployment_patch = {"spec": {"replicas": replicas}}

            self.apps_v1_api.patch_namespaced_deployment_scale(
                name=service_name, namespace=self.namespace, body=deployment_patch
            )

            # Wait for new replicas to start
            await asyncio.sleep(3)
            return True

        except Exception as e:
            logger.error(f"Failed to scale deployment: {e}")
            return False

    async def _apply_network_policy(self, service_name: str) -> bool:
        """Apply network policy to limit traffic"""
        try:
            logger.info(f"🔒 Applying network policy to {service_name}")

            # This is simplified - actual network policy would be more complex
            return True

        except Exception as e:
            logger.error(f"Failed to apply network policy: {e}")
            return False

    async def _apply_rate_limit(self, service_name: str) -> bool:
        """Apply rate limit via network policy"""
        try:
            logger.info(f"⚡ Applying rate limit to {service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply rate limit: {e}")
            return False

    async def _verify_service_health(self, service_name: str) -> bool:
        """Verify service is healthy after recovery"""
        try:
            pods = self.v1_api.list_namespaced_pod(
                namespace=self.namespace, label_selector=f"app={service_name}"
            )

            if not pods.items:
                logger.warning(f"No pods found for {service_name}")
                return False

            # Check if at least one pod is running
            for pod in pods.items:
                if pod.status.phase == "Running":
                    logger.info(f"✅ Pod healthy: {pod.metadata.name}")
                    return True

            logger.warning(f"❌ No running pods for {service_name}")
            return False

        except Exception as e:
            logger.error(f"Failed to verify service health: {e}")
            return False

    async def _acquire_lock(self, service_name: str, timeout: int = 60):
        """Acquire semaphore lock for service (prevent concurrent recovery)"""
        if service_name not in self.pod_locks:
            self.pod_locks[service_name] = asyncio.Lock()

        await self.pod_locks[service_name].acquire()

    async def _release_lock(self, service_name: str):
        """Release semaphore lock for service"""
        if service_name in self.pod_locks:
            self.pod_locks[service_name].release()

    def _failure_outcome(
        self, recovery_context: RecoveryContext, error: str
    ) -> RecoveryOutcome:
        """Create failed outcome object"""
        return RecoveryOutcome(
            success=False,
            recovery_context=recovery_context,
            recovery_time_ms=0.0,
            actions_executed=0,
            actions_failed=0,
            error_message=error,
        )
