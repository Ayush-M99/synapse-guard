"""
Unit tests for DARWIN core interfaces and models
"""

import pytest
import asyncio
from datetime import datetime

from core.models import (
    AttackResult,
    DetectionResult,
    FailureSignature,
    Recovery,
    RecoveryOutcome,
    ServiceTarget,
)
from core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


class TestModels:
    """Test data models and serialization"""

    def test_service_target(self):
        """Test ServiceTarget model"""
        target = ServiceTarget("darwin-target", "payment-service", "payment-xyz")
        assert target.namespace == "darwin-target"
        assert target.service_name == "payment-service"
        assert target.pod_name == "payment-xyz"

    def test_failure_signature(self):
        """Test FailureSignature model"""
        sig = FailureSignature(
            cpu_usage=2.5,
            memory_mb=1024,
            error_rate=0.3,
            latency_p99_ms=5000,
            pod_restarts=5,
            network_rx_mbps=50,
            network_tx_mbps=100,
            service="payment-service",
        )

        # Test to_array
        arr = sig.to_array()
        assert len(arr) == 7
        assert arr[0] == 2.5

        # Test serialization
        data = sig.to_dict()
        assert data["cpu_usage"] == 2.5
        assert data["service"] == "payment-service"

        # Test JSON serialization
        json_str = sig.to_json()
        assert "cpu_usage" in json_str

    def test_attack_result(self):
        """Test AttackResult model"""
        now = datetime.utcnow()
        result = AttackResult(
            success=True,
            attack_id="pod_crash",
            target_service="payment-service",
            timestamp=now,
        )

        assert result.success is True
        assert result.attack_id == "pod_crash"

        # Test serialization
        data = result.to_dict()
        assert data["success"] is True

    def test_detection_result(self):
        """Test DetectionResult model"""
        result = DetectionResult(
            is_anomaly=True,
            anomaly_score=0.87,
            isolated_service="payment-service",
            attack_family="pod_crash",
            attack_family_confidence=0.91,
            predicted_recovery="restart_and_scale",
        )

        assert result.is_anomaly is True
        assert result.anomaly_score == 0.87
        assert result.attack_family == "pod_crash"

    def test_recovery(self):
        """Test Recovery model"""
        recovery = Recovery(
            recovery_id="rec-001",
            actions=[
                {"type": "restart_pod", "target": "payment-service"},
                {"type": "scale_replicas", "deployment": "payment-service", "count": 3},
            ],
            success_rate=0.95,
            avg_recovery_time_seconds=2.1,
            tier_used="retrieval",
        )

        assert recovery.success_rate == 0.95
        assert len(recovery.actions) == 2

        # Test serialization and deserialization
        data = recovery.to_dict()
        recovered = Recovery.from_dict(data)
        assert recovered.recovery_id == recovery.recovery_id

    def test_recovery_outcome(self):
        """Test RecoveryOutcome model"""
        outcome = RecoveryOutcome(
            successful=True, recovery_time_seconds=2.1, actions_executed=2
        )

        assert outcome.successful is True
        assert outcome.recovery_time_seconds == 2.1


class TestCircuitBreaker:
    """Test circuit breaker pattern"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_normal_operation(self):
        """Test circuit breaker in closed state"""
        breaker = CircuitBreaker("test", failure_threshold=3, timeout_seconds=1)

        async def success_func():
            return "success"

        # Should succeed normally
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after threshold"""
        breaker = CircuitBreaker("test", failure_threshold=3, timeout_seconds=1)

        async def failing_func():
            raise Exception("Service unavailable")

        # Fail 3 times
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(failing_func)

        # Circuit should be open now
        assert breaker.state == CircuitState.OPEN

        # Should raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(failing_func)

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker recovery through half-open state"""
        breaker = CircuitBreaker("test", failure_threshold=2, timeout_seconds=1)

        async def failing_func():
            raise Exception("Service unavailable")

        # Fail twice to open circuit
        for i in range(2):
            with pytest.raises(Exception):
                await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        await asyncio.sleep(1.1)

        # Should be half-open now, try to call
        async def success_func():
            return "recovered"

        result = await breaker.call(success_func)
        assert result == "recovered"
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_health_status(self):
        """Test circuit breaker status reporting"""
        breaker = CircuitBreaker("test", failure_threshold=5)
        status = breaker.get_state()

        assert status["name"] == "test"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
