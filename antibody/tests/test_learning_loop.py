"""
Unit tests for Antibody Agent - Learning Loop
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from antibody.models import (
    RecoveryOutcome,
    RecoveryContext,
    FailureEvent,
    RecoveryPlaybook,
    RecoveryAction,
    RecoveryActionType,
    DNARecord,
)
from antibody.learning_loop import LearningLoop


@pytest.fixture
def learning_loop():
    """Create learning loop for testing"""
    postgres_tier = Mock()
    postgres_tier.record_recovery_generation = AsyncMock(return_value=True)

    redis_tier = Mock()
    redis_tier.cache_playbook = AsyncMock(return_value=True)

    neo4j_tier = Mock()
    neo4j_tier.store_attack_recovery = AsyncMock(return_value=True)

    return LearningLoop(
        postgres_tier=postgres_tier,
        redis_tier=redis_tier,
        neo4j_tier=neo4j_tier,
        virus_gen=1,
        antibody_gen=1,
    )


@pytest.fixture
def recovery_outcome():
    """Create sample recovery outcome"""
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
            ),
        ],
        attack_family="pod_crash",
        success_rate=0.98,
        avg_recovery_time_ms=1500.0,
    )

    recovery_context = RecoveryContext(
        failure_event=failure_event,
        signature_hash="abc123",
        playbook=playbook,
    )

    return RecoveryOutcome(
        success=True,
        recovery_context=recovery_context,
        recovery_time_ms=1500.0,
        actions_executed=1,
        actions_failed=0,
    )


class TestLearningLoop:
    """Test cases for Learning Loop"""

    @pytest.mark.asyncio
    async def test_record_recovery_success(self, learning_loop, recovery_outcome):
        """Test successful recovery recording"""
        result = await learning_loop.record_recovery(recovery_outcome)

        assert result is True
        learning_loop.postgres_tier.record_recovery_generation.assert_called_once()
        learning_loop.redis_tier.cache_playbook.assert_called_once()
        learning_loop.neo4j_tier.store_attack_recovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_generation_counter_increments(self, learning_loop, recovery_outcome):
        """Test that generation counter increments"""
        initial_gen = learning_loop.antibody_gen

        await learning_loop.record_recovery(recovery_outcome)

        assert learning_loop.antibody_gen == initial_gen + 1

    @pytest.mark.asyncio
    async def test_record_recovery_to_postgres(self, learning_loop, recovery_outcome):
        """Test that recovery is recorded to PostgreSQL"""
        await learning_loop.record_recovery(recovery_outcome)

        # Verify PostgreSQL was called
        learning_loop.postgres_tier.record_recovery_generation.assert_called_once()
        call_args = learning_loop.postgres_tier.record_recovery_generation.call_args
        dna_record = call_args[0][0]

        assert isinstance(dna_record, DNARecord)
        assert dna_record.success is True
        assert dna_record.recovery_ms == 1500.0

    @pytest.mark.asyncio
    async def test_record_recovery_to_redis(self, learning_loop, recovery_outcome):
        """Test that successful recovery is cached in Redis"""
        recovery_outcome.success = True
        await learning_loop.record_recovery(recovery_outcome)

        # Verify Redis was called for successful recovery
        learning_loop.redis_tier.cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_failed_recovery_no_redis_update(self, learning_loop, recovery_outcome):
        """Test that failed recovery is NOT cached in Redis"""
        recovery_outcome.success = False
        learning_loop.redis_tier.cache_playbook.reset_mock()

        await learning_loop.record_recovery(recovery_outcome)

        # Redis should NOT be called for failed recovery
        learning_loop.redis_tier.cache_playbook.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_recovery_to_neo4j(self, learning_loop, recovery_outcome):
        """Test that successful recovery updates Neo4j"""
        recovery_outcome.success = True
        await learning_loop.record_recovery(recovery_outcome)

        # Verify Neo4j was called
        learning_loop.neo4j_tier.store_attack_recovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_dna_record_fields_populated(self, learning_loop, recovery_outcome):
        """Test that DNARecord has all required fields"""
        await learning_loop.record_recovery(recovery_outcome)

        call_args = learning_loop.postgres_tier.record_recovery_generation.call_args
        dna_record = call_args[0][0]

        assert dna_record.virus_gen > 0
        assert dna_record.antibody_gen > 0
        assert dna_record.strand_id is not None
        assert dna_record.strand_family == "pod_crash"
        assert dna_record.target_service == "payment-service"
        assert dna_record.recovery_ms == 1500.0
        assert dna_record.rf_confidence == 0.91
        assert dna_record.detection_path == "isolation_forest"

    @pytest.mark.asyncio
    async def test_cache_hit_tracking(self, learning_loop, recovery_outcome):
        """Test that cache hits are tracked"""
        recovery_outcome.recovery_context.playbook.rag_tier.value = "redis"
        await learning_loop.record_recovery(recovery_outcome)

        call_args = learning_loop.postgres_tier.record_recovery_generation.call_args
        dna_record = call_args[0][0]

        assert dna_record.cache_hit is True

    @pytest.mark.asyncio
    async def test_postgres_failure_aborts_recording(self, learning_loop, recovery_outcome):
        """Test that PostgreSQL failure aborts recording"""
        learning_loop.postgres_tier.record_recovery_generation = AsyncMock(return_value=False)

        result = await learning_loop.record_recovery(recovery_outcome)

        assert result is False
        # Redis and Neo4j should NOT be called if PostgreSQL fails
        learning_loop.redis_tier.cache_playbook.assert_not_called()
        learning_loop.neo4j_tier.store_attack_recovery.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_failure_non_critical(self, learning_loop, recovery_outcome):
        """Test that Redis failure is non-critical"""
        learning_loop.redis_tier.cache_playbook = AsyncMock(return_value=False)

        result = await learning_loop.record_recovery(recovery_outcome)

        # Overall result should still be True
        assert result is True
        # Neo4j should still be called despite Redis failure
        learning_loop.neo4j_tier.store_attack_recovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_playbook_execution_count_tracked(self, learning_loop, recovery_outcome):
        """Test that playbook execution count is tracked"""
        initial_count = recovery_outcome.recovery_context.playbook.execution_count

        await learning_loop.record_recovery(recovery_outcome)

        # Execution count should be incremented during caching
        call_args = learning_loop.redis_tier.cache_playbook.call_args
        updated_playbook = call_args[0][1]

        assert updated_playbook.execution_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_recovery_time_averaging(self, learning_loop, recovery_outcome):
        """Test that recovery times are averaged"""
        # First recovery: 1500ms
        initial_avg = recovery_outcome.recovery_context.playbook.avg_recovery_time_ms

        await learning_loop.record_recovery(recovery_outcome)

        call_args = learning_loop.redis_tier.cache_playbook.call_args
        updated_playbook = call_args[0][1]

        # Average should be calculated: (1500 * 1 + 1500) / 2 = 1500
        # (Since execution_count was 0, it's incremented to 1 before calculation)
        expected_avg = (initial_avg * 0 + 1500) / 1
        assert updated_playbook.avg_recovery_time_ms == expected_avg

    @pytest.mark.asyncio
    async def test_learning_curve_retrieval(self, learning_loop):
        """Test learning curve data retrieval"""
        curve_data = await learning_loop.get_learning_curve("pod_crash", limit=10)

        # Should return list (even if empty for now)
        assert isinstance(curve_data, list)
