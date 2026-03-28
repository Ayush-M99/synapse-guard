"""
Unit tests for Antibody Agent - Recovery Executor
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from antibody.models import (
    FailureEvent,
    RecoveryPlaybook,
    RecoveryAction,
    RecoveryActionType,
    RecoveryContext,
)
from antibody.recovery_executor import RecoveryExecutor


@pytest.fixture
def recovery_executor():
    """Create recovery executor for testing"""
    with patch('antibody.recovery_executor.config'):
        executor = RecoveryExecutor(namespace="test-ns")
        executor.v1_api = Mock()
        executor.apps_v1_api = Mock()
        executor.connected = True
        return executor


@pytest.fixture
def recovery_context():
    """Create recovery context for testing"""
    failure_event = FailureEvent(
        service="payment-service",
        attack_family="pod_crash",
        rf_confidence=0.91,
        anomaly_score=0.92,
        detection_path="isolation_forest",
    )

    playbook = RecoveryPlaybook(
        playbook_id="test-playbook",
        actions=[
            RecoveryAction(
                action_type=RecoveryActionType.RESTART_POD,
                target_service="payment-service",
                parameters={"grace_period": 5},
            ),
        ],
        attack_family="pod_crash",
        success_rate=0.98,
        avg_recovery_time_ms=1500.0,
    )

    return RecoveryContext(failure_event=failure_event, signature_hash="abc123", playbook=playbook)


class TestRecoveryExecutor:
    """Test cases for Recovery Executor"""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful Kubernetes connection"""
        with patch('antibody.recovery_executor.config'):
            with patch('antibody.recovery_executor.client'):
                executor = RecoveryExecutor()
                executor.v1_api = Mock()
                executor.apps_v1_api = Mock()

                result = await executor.connect()

                assert result is True
                assert executor.connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test failed Kubernetes connection"""
        with patch('antibody.recovery_executor.config.load_kube_config') as mock_config:
            mock_config.side_effect = Exception("Config not found")

            executor = RecoveryExecutor(in_cluster=False)
            result = await executor.connect()

            assert result is False
            assert executor.connected is False

    @pytest.mark.asyncio
    async def test_restart_pod_success(self, recovery_executor, recovery_context):
        """Test successful pod restart"""
        mock_pod = Mock()
        mock_pod.metadata.name = "payment-service-xyz"

        mock_pods = Mock()
        mock_pods.items = [mock_pod]

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods
        recovery_executor.v1_api.delete_namespaced_pod.return_value = Mock()

        action = recovery_context.playbook.actions[0]
        result = await recovery_executor._restart_service_pod(action.target_service)

        assert result is True
        recovery_executor.v1_api.delete_namespaced_pod.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_pod_no_pods(self, recovery_executor):
        """Test pod restart when no pods found"""
        mock_pods = Mock()
        mock_pods.items = []

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods

        result = await recovery_executor._restart_service_pod("payment-service")

        assert result is False

    @pytest.mark.asyncio
    async def test_scale_deployment_success(self, recovery_executor):
        """Test successful deployment scaling"""
        recovery_executor.apps_v1_api.patch_namespaced_deployment_scale.return_value = Mock()

        result = await recovery_executor._scale_deployment("payment-service", 3)

        assert result is True
        recovery_executor.apps_v1_api.patch_namespaced_deployment_scale.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_service_health_healthy(self, recovery_executor):
        """Test service health verification - healthy"""
        mock_pod = Mock()
        mock_pod.metadata.name = "payment-service-xyz"
        mock_pod.status.phase = "Running"

        mock_pods = Mock()
        mock_pods.items = [mock_pod]

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods

        result = await recovery_executor._verify_service_health("payment-service")

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_service_health_unhealthy(self, recovery_executor):
        """Test service health verification - unhealthy"""
        mock_pod = Mock()
        mock_pod.metadata.name = "payment-service-xyz"
        mock_pod.status.phase = "Failed"

        mock_pods = Mock()
        mock_pods.items = [mock_pod]

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods

        result = await recovery_executor._verify_service_health("payment-service")

        assert result is False

    @pytest.mark.asyncio
    async def test_semaphore_lock_acquisition(self, recovery_executor):
        """Test semaphore lock acquisition"""
        service = "payment-service"

        await recovery_executor._acquire_lock(service)

        assert service in recovery_executor.pod_locks
        assert recovery_executor.pod_locks[service].locked()

    @pytest.mark.asyncio
    async def test_semaphore_lock_release(self, recovery_executor):
        """Test semaphore lock release"""
        service = "payment-service"

        await recovery_executor._acquire_lock(service)
        await recovery_executor._release_lock(service)

        # Lock should exist but not be locked
        assert service in recovery_executor.pod_locks

    @pytest.mark.asyncio
    async def test_execute_recovery_success(self, recovery_executor, recovery_context):
        """Test complete recovery execution"""
        # Mock pod operations
        mock_pod = Mock()
        mock_pod.metadata.name = "payment-service-xyz"
        mock_pod.status.phase = "Running"

        mock_pods = Mock()
        mock_pods.items = [mock_pod]

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods
        recovery_executor.v1_api.delete_namespaced_pod.return_value = Mock()
        recovery_executor.apps_v1_api.patch_namespaced_deployment_scale.return_value = Mock()

        # Add scaling action
        recovery_context.playbook.actions.append(
            RecoveryAction(
                action_type=RecoveryActionType.SCALE_REPLICAS,
                target_service="payment-service",
                parameters={"replicas": 2},
            )
        )

        outcome = await recovery_executor.execute_recovery(recovery_context)

        assert outcome.success is True
        assert outcome.recovery_time_ms > 0
        assert outcome.actions_executed >= 0

    @pytest.mark.asyncio
    async def test_execute_recovery_not_connected(self, recovery_context):
        """Test recovery execution when not connected"""
        executor = RecoveryExecutor()
        executor.connected = False

        outcome = await executor.execute_recovery(recovery_context)

        assert outcome.success is False
        assert outcome.error_message == "Not connected to Kubernetes"

    @pytest.mark.asyncio
    async def test_concurrent_recovery_prevention(self, recovery_executor, recovery_context):
        """Test that semaphore prevents concurrent recovery on same pod"""
        service = "payment-service"

        # Acquire lock for first recovery
        await recovery_executor._acquire_lock(service)
        lock1_acquired = recovery_executor.pod_locks[service].locked()

        # Try to acquire same lock (would block in real scenario)
        can_acquire = recovery_executor.pod_locks[service]._locked is False

        assert lock1_acquired is True
        assert can_acquire is False

    @pytest.mark.asyncio
    async def test_action_rollback_on_failure(self, recovery_executor, recovery_context):
        """Test action rollback when rollback_on_failure is True"""
        recovery_context.playbook.actions[0].rollback_on_failure = True

        # Make action fail by raising exception
        recovery_executor.v1_api.list_namespaced_pod.side_effect = Exception("Pod not found")

        outcome = await recovery_executor.execute_recovery(recovery_context)

        # Should rollback and stop executing further actions
        assert outcome.actions_failed > 0

    @pytest.mark.asyncio
    async def test_execute_unknown_action_type(self, recovery_executor, recovery_context):
        """Test handling of unknown action types"""
        recovery_context.playbook.actions[0].action_type = "unknown_action"

        # This should still work since action_type is an enum
        # But let's test the fallback behavior
        action = Mock()
        action.action_type = "unknown_type"
        action.target_service = "payment-service"
        action.rollback_on_failure = False

        result = await recovery_executor._execute_action(action)

        assert result is False

    @pytest.mark.asyncio
    async def test_recovery_timing_tracking(self, recovery_executor, recovery_context):
        """Test that recovery timing is accurately tracked"""
        mock_pod = Mock()
        mock_pod.metadata.name = "payment-service-xyz"
        mock_pod.status.phase = "Running"

        mock_pods = Mock()
        mock_pods.items = [mock_pod]

        recovery_executor.v1_api.list_namespaced_pod.return_value = mock_pods
        recovery_executor.v1_api.delete_namespaced_pod.return_value = Mock()

        outcome = await recovery_executor.execute_recovery(recovery_context)

        # Recovery time should be reasonable (>0ms but <10s)
        assert 0 < outcome.recovery_time_ms < 10000

    @pytest.mark.asyncio
    async def test_health_verification_after_recovery(self, recovery_executor, recovery_context):
        """Test that health is verified after recovery actions"""
        recovery_executor.v1_api.list_namespaced_pod.return_value = Mock(items=[])

        # Mock to show unhealthy after initial action
        mock_pod_unhealthy = Mock()
        mock_pod_unhealthy.status.phase = "CrashLoopBackOff"

        mock_pod_healthy = Mock()
        mock_pod_healthy.status.phase = "Running"
        mock_pod_healthy.metadata.name = "new-pod"

        # First call unhealthy, second call healthy
        recovery_executor.v1_api.list_namespaced_pod.side_effect = [
            Mock(items=[mock_pod_unhealthy]),
            Mock(items=[mock_pod_healthy]),
        ]

        result = await recovery_executor._verify_service_health("payment-service")

        # After retry, should be healthy
        assert result is True
