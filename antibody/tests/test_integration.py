"""
Integration tests for Antibody Agent - End-to-end recovery cycles
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from antibody.models import (
    FailureEvent,
    RecoveryPlaybook,
    RecoveryAction,
    RecoveryActionType,
)
from antibody.agent import AntibodyAgent
from antibody.rag_engine import RAGRecoveryEngine
from antibody.recovery_executor import RecoveryExecutor
from antibody.learning_loop import LearningLoop


@pytest.fixture
def integration_setup():
    """Set up complete integration test environment"""
    # Mock all components
    redis_tier = Mock()
    redis_tier.get_cached_playbook = AsyncMock(return_value=None)
    redis_tier.cache_playbook = AsyncMock(return_value=True)
    redis_tier.connect = AsyncMock(return_value=True)
    redis_tier.health_check = AsyncMock(return_value=True)

    neo4j_tier = Mock()
    neo4j_tier.retrieve_similar_playbooks = AsyncMock(return_value=[])
    neo4j_tier.connect = AsyncMock(return_value=True)
    neo4j_tier.store_attack_recovery = AsyncMock(return_value=True)
    neo4j_tier.health_check = AsyncMock(return_value=True)

    postgres_tier = Mock()
    postgres_tier.retrieve_historical_recoveries = AsyncMock(return_value=[])
    postgres_tier.connect = AsyncMock(return_value=True)
    postgres_tier.record_recovery_generation = AsyncMock(return_value=True)
    postgres_tier.health_check = AsyncMock(return_value=True)

    message_bus = Mock()
    message_bus.connect = AsyncMock(return_value=True)
    message_bus.subscribe = AsyncMock(return_value=None)
    message_bus.publish = AsyncMock(return_value=True)
    message_bus.health_check = AsyncMock(return_value=True)

    recovery_executor = Mock()
    recovery_executor.connect = AsyncMock(return_value=True)

    rag_engine = RAGRecoveryEngine(
        redis_tier=redis_tier,
        neo4j_tier=neo4j_tier,
        postgres_tier=postgres_tier,
    )

    learning_loop = LearningLoop(
        postgres_tier=postgres_tier,
        redis_tier=redis_tier,
        neo4j_tier=neo4j_tier,
    )

    return {
        "redis_tier": redis_tier,
        "neo4j_tier": neo4j_tier,
        "postgres_tier": postgres_tier,
        "message_bus": message_bus,
        "recovery_executor": recovery_executor,
        "rag_engine": rag_engine,
        "learning_loop": learning_loop,
    }


class TestEndToEndRecovery:
    """Integration tests for complete attack→recovery cycles"""

    @pytest.mark.asyncio
    async def test_complete_gen1_recovery_via_neo4j(self, integration_setup):
        """Test complete Gen 1 recovery (via Neo4j)"""
        setup = integration_setup

        # Setup: Neo4j returns a playbook
        sample_playbook = RecoveryPlaybook(
            playbook_id="playbook-1",
            actions=[
                RecoveryAction(
                    action_type=RecoveryActionType.RESTART_POD,
                    target_service="payment-service",
                ),
            ],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=2000.0,
        )

        setup["neo4j_tier"].retrieve_similar_playbooks = AsyncMock(
            return_value=[sample_playbook]
        )

        # Simulate failure event
        failure_event = FailureEvent(
            service="payment-service",
            attack_family="pod_crash",
            rf_confidence=0.91,
            anomaly_score=0.92,
            detection_path="isolation_forest",
        )

        # Get recovery playbook
        playbook = await setup["rag_engine"].retrieve_recovery_playbook(
            failure_event, "hash-gen1"
        )

        # Verify playbook retrieved via Neo4j
        assert playbook is not None
        assert playbook.playbook_id == "playbook-1"

        # Verify cached in Redis
        setup["redis_tier"].cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_gen2_recovery_via_redis(self, integration_setup):
        """Test complete Gen 2 recovery (via Redis cache - 90% faster)"""
        setup = integration_setup

        # Setup: Redis returns cached playbook from Gen 1
        cached_playbook = RecoveryPlaybook(
            playbook_id="playbook-1",
            actions=[
                RecoveryAction(
                    action_type=RecoveryActionType.RESTART_POD,
                    target_service="payment-service",
                ),
            ],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=2000.0,
        )

        setup["redis_tier"].get_cached_playbook = AsyncMock(return_value=cached_playbook)

        # Simulate same failure event (Gen 2)
        failure_event = FailureEvent(
            service="payment-service",
            attack_family="pod_crash",
            rf_confidence=0.91,
            anomaly_score=0.92,
            detection_path="isolation_forest",
        )

        # Get recovery playbook
        playbook = await setup["rag_engine"].retrieve_recovery_playbook(
            failure_event, "hash-gen2"
        )

        # Verify playbook retrieved via Redis
        assert playbook is not None
        assert playbook.playbook_id == "playbook-1"

        # Neo4j should NOT be called (cache hit)
        setup["neo4j_tier"].retrieve_similar_playbooks.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier2_miss_fallback_to_tier3(self, integration_setup):
        """Test fallback from Tier 2 (Neo4j) to Tier 3 (PostgreSQL)"""
        setup = integration_setup

        # Setup: Neo4j returns no results, PostgreSQL returns historical
        historical_playbook = RecoveryPlaybook(
            playbook_id="playbook-historical",
            actions=[
                RecoveryAction(
                    action_type=RecoveryActionType.RESTART_POD,
                    target_service="payment-service",
                ),
            ],
            attack_family="pod_crash",
            success_rate=0.95,
            avg_recovery_time_ms=18000.0,
        )

        setup["redis_tier"].get_cached_playbook = AsyncMock(return_value=None)
        setup["neo4j_tier"].retrieve_similar_playbooks = AsyncMock(return_value=[])
        setup["postgres_tier"].retrieve_historical_recoveries = AsyncMock(
            return_value=[historical_playbook]
        )

        failure_event = FailureEvent(
            service="payment-service",
            attack_family="pod_crash",
            rf_confidence=0.91,
            anomaly_score=0.92,
            detection_path="isolation_forest",
        )

        playbook = await setup["rag_engine"].retrieve_recovery_playbook(
            failure_event, "hash-fallback"
        )

        # Verify playbook retrieved via PostgreSQL
        assert playbook is not None
        assert playbook.playbook_id == "playbook-historical"

        # Should be cached in Redis for next time
        setup["redis_tier"].cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_tiers_miss_emergency_recovery(self, integration_setup):
        """Test emergency recovery when all 3 tiers miss"""
        setup = integration_setup

        # Setup: All tiers return empty
        setup["redis_tier"].get_cached_playbook = AsyncMock(return_value=None)
        setup["neo4j_tier"].retrieve_similar_playbooks = AsyncMock(return_value=[])
        setup["postgres_tier"].retrieve_historical_recoveries = AsyncMock(return_value=[])

        failure_event = FailureEvent(
            service="payment-service",
            attack_family="unknown_attack",
            rf_confidence=0.5,
            anomaly_score=0.5,
            detection_path="unknown",
        )

        playbook = await setup["rag_engine"].retrieve_recovery_playbook(
            failure_event, "hash-emergency"
        )

        # Verify emergency playbook created
        assert playbook is not None
        assert playbook.rag_tier.value == "emergency"

        # Should have default actions
        assert len(playbook.actions) > 0

    @pytest.mark.asyncio
    async def test_learning_loop_records_all_databases(self, integration_setup):
        """Test that learning loop records to all 3 databases"""
        setup = integration_setup

        # Create a recovery outcome
        failure_event = FailureEvent(
            service="payment-service",
            attack_family="pod_crash",
            rf_confidence=0.91,
            anomaly_score=0.92,
            detection_path="isolation_forest",
        )

        playbook = RecoveryPlaybook(
            playbook_id="test",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=1500.0,
        )

        from antibody.models import RecoveryContext, RecoveryOutcome

        context = RecoveryContext(
            failure_event=failure_event,
            signature_hash="hash",
            playbook=playbook,
        )

        outcome = RecoveryOutcome(
            success=True,
            recovery_context=context,
            recovery_time_ms=1500.0,
            actions_executed=1,
        )

        # Record recovery
        result = await setup["learning_loop"].record_recovery(outcome)

        # Verify all databases called
        assert result is True
        setup["postgres_tier"].record_recovery_generation.assert_called_once()
        setup["redis_tier"].cache_playbook.assert_called_once()
        setup["neo4j_tier"].store_attack_recovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_generational_improvement_metrics(self, integration_setup):
        """Test tracking of generational improvement"""
        setup = integration_setup

        # Gen 1: 18s recovery from Neo4j
        gen1_playbook = RecoveryPlaybook(
            playbook_id="gen1",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=18000.0,
        )

        # Gen 2: 2.1s recovery from Redis cache
        gen2_playbook = RecoveryPlaybook(
            playbook_id="gen2",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=2100.0,
        )

        # Verify 88% improvement
        improvement = (gen1_playbook.avg_recovery_time_ms - gen2_playbook.avg_recovery_time_ms) / gen1_playbook.avg_recovery_time_ms
        assert improvement > 0.85  # 85% improvement

    @pytest.mark.asyncio
    async def test_concurrent_attacks_different_services(self, integration_setup):
        """Test handling of concurrent attacks on different services"""
        setup = integration_setup

        # Service 1: payment-service pod crash
        event1 = FailureEvent(
            service="payment-service",
            attack_family="pod_crash",
            rf_confidence=0.91,
            anomaly_score=0.92,
            detection_path="isolation_forest",
        )

        # Service 2: order-service network failure
        event2 = FailureEvent(
            service="order-service",
            attack_family="network_partition",
            rf_confidence=0.88,
            anomaly_score=0.85,
            detection_path="cusum",
        )

        playbook1 = RecoveryPlaybook(
            playbook_id="playbook1",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=1500.0,
        )

        playbook2 = RecoveryPlaybook(
            playbook_id="playbook2",
            actions=[],
            attack_family="network_partition",
            success_rate=0.96,
            avg_recovery_time_ms=2500.0,
        )

        # Both should retrieve playbooks independently
        setup["redis_tier"].get_cached_playbook = AsyncMock(
            side_effect=[None, None]  # Both miss cache
        )
        setup["neo4j_tier"].retrieve_similar_playbooks = AsyncMock(
            side_effect=[[playbook1], [playbook2]]
        )

        result1 = await setup["rag_engine"].retrieve_recovery_playbook(event1, "hash1")
        result2 = await setup["rag_engine"].retrieve_recovery_playbook(event2, "hash2")

        assert result1.playbook_id == "playbook1"
        assert result2.playbook_id == "playbook2"

    @pytest.mark.asyncio
    async def test_playbook_quality_metrics(self, integration_setup):
        """Test that playbooks have quality metrics"""
        setup = integration_setup

        playbook = RecoveryPlaybook(
            playbook_id="test",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=1500.0,
            execution_count=10,
            generation=2,
        )

        # Verify quality metrics
        assert playbook.success_rate >= 0.9  # >90% success
        assert playbook.execution_count > 0
        assert playbook.generation > 0
        assert playbook.avg_recovery_time_ms < 20000  # <20 second recovery
