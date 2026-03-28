"""
Unit tests for Antibody Agent - RAG Engine
"""

import pytest
from unittest.mock import Mock, AsyncMock

from antibody.models import FailureEvent, RecoveryPlaybook, RecoveryAction, RecoveryActionType, RAGTier
from antibody.rag_engine import RAGRecoveryEngine


@pytest.fixture
def rag_engine():
    """Create RAG engine with mocked tiers"""
    redis_tier = Mock()
    redis_tier.get_cached_playbook = AsyncMock(return_value=None)
    redis_tier.cache_playbook = AsyncMock(return_value=True)

    neo4j_tier = Mock()
    neo4j_tier.retrieve_similar_playbooks = AsyncMock(return_value=[])

    postgres_tier = Mock()
    postgres_tier.retrieve_historical_recoveries = AsyncMock(return_value=[])

    return RAGRecoveryEngine(
        redis_tier=redis_tier,
        neo4j_tier=neo4j_tier,
        postgres_tier=postgres_tier,
    )


@pytest.fixture
def failure_event():
    """Create sample failure event"""
    return FailureEvent(
        service="payment-service",
        attack_family="pod_crash",
        rf_confidence=0.91,
        anomaly_score=0.92,
        detection_path="isolation_forest",
    )


@pytest.fixture
def sample_playbook():
    """Create sample playbook"""
    return RecoveryPlaybook(
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


class TestRAGRecoveryEngine:
    """Test cases for RAG Recovery Engine"""

    @pytest.mark.asyncio
    async def test_tier1_redis_hit(self, rag_engine, failure_event, sample_playbook):
        """Test Tier 1 (Redis) cache hit"""
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=sample_playbook)

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        assert playbook is not None
        assert playbook.playbook_id == "test-playbook"
        assert playbook.rag_tier == RAGTier.REDIS
        # Neo4j and PostgreSQL should NOT be called
        rag_engine.neo4j_tier.retrieve_similar_playbooks.assert_not_called()
        rag_engine.postgres_tier.retrieve_historical_recoveries.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier1_miss_tier2_hit(self, rag_engine, failure_event, sample_playbook):
        """Test Tier 1 miss, Tier 2 (Neo4j) hit"""
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(
            return_value=[sample_playbook]
        )

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        assert playbook is not None
        assert playbook.rag_tier == RAGTier.NEO4J
        # Redis should be called to cache
        rag_engine.redis_tier.cache_playbook.assert_called_once()
        # PostgreSQL should NOT be called
        rag_engine.postgres_tier.retrieve_historical_recoveries.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier2_miss_tier3_hit(self, rag_engine, failure_event, sample_playbook):
        """Test Tier 2 miss, Tier 3 (PostgreSQL) hit"""
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(return_value=[])
        rag_engine.postgres_tier.retrieve_historical_recoveries = AsyncMock(
            return_value=[sample_playbook]
        )

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        assert playbook is not None
        assert playbook.rag_tier == RAGTier.POSTGRES
        # Should cache in Redis
        rag_engine.redis_tier.cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_tiers_miss_emergency_fallback(
        self, rag_engine, failure_event
    ):
        """Test all tiers miss - emergency fallback"""
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(return_value=[])
        rag_engine.postgres_tier.retrieve_historical_recoveries = AsyncMock(return_value=[])

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        assert playbook is not None
        assert playbook.rag_tier == RAGTier.EMERGENCY
        assert playbook.confidence == 0.3  # Low confidence for hardcoded recovery
        # Should still cache emergency recovery
        rag_engine.redis_tier.cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_emergency_recovery_has_actions(self, rag_engine, failure_event):
        """Test that emergency recovery includes default actions"""
        playbook = rag_engine._create_emergency_recovery(failure_event)

        assert len(playbook.actions) > 0
        # Should include pod restart
        assert any(
            action.action_type == RecoveryActionType.RESTART_POD
            for action in playbook.actions
        )
        # Should include scaling
        assert any(
            action.action_type == RecoveryActionType.SCALE_REPLICAS
            for action in playbook.actions
        )

    @pytest.mark.asyncio
    async def test_fallback_chain_order(self, rag_engine, failure_event):
        """Test that fallback chain respects tier order"""
        # Set up so Tier 2 and Tier 3 would both have results
        # but should stop at Tier 2

        playbook2 = RecoveryPlaybook(
            playbook_id="tier2-playbook",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=2000.0,
        )

        playbook3 = RecoveryPlaybook(
            playbook_id="tier3-playbook",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.95,
            avg_recovery_time_ms=18000.0,
        )

        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(
            return_value=[playbook2]
        )
        rag_engine.postgres_tier.retrieve_historical_recoveries = AsyncMock(
            return_value=[playbook3]
        )

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        # Should use Tier 2 result, not Tier 3
        assert playbook.playbook_id == "tier2-playbook"
        assert playbook.rag_tier == RAGTier.NEO4J
        # Tier 3 should NOT be called
        rag_engine.postgres_tier.retrieve_historical_recoveries.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_multiple_tiers(self, rag_engine, failure_event, sample_playbook):
        """Test that playbooks from all tiers are cached"""
        # Test Tier 2 → caches
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(
            return_value=[sample_playbook]
        )

        await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        # Redis cache should be called
        rag_engine.redis_tier.cache_playbook.assert_called_once()

        # Reset and test Tier 3 → caches
        rag_engine.redis_tier.cache_playbook.reset_mock()
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(return_value=[])
        rag_engine.postgres_tier.retrieve_historical_recoveries = AsyncMock(
            return_value=[sample_playbook]
        )

        await rag_engine.retrieve_recovery_playbook(failure_event, "hash456")

        # Redis should still be called for Tier 3 result
        rag_engine.redis_tier.cache_playbook.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_selection_by_success_rate(self, rag_engine, failure_event):
        """Test that highest success rate is selected from multiple results"""
        playbook_high = RecoveryPlaybook(
            playbook_id="high-success",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.99,
            avg_recovery_time_ms=1500.0,
        )

        playbook_low = RecoveryPlaybook(
            playbook_id="low-success",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.85,
            avg_recovery_time_ms=1500.0,
        )

        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        # Return highest success rate first (as sorted by Neo4j)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(
            return_value=[playbook_high, playbook_low]
        )

        playbook = await rag_engine.retrieve_recovery_playbook(failure_event, "hash123")

        # Should select highest success rate
        assert playbook.playbook_id == "high-success"
        assert playbook.success_rate == 0.99

    @pytest.mark.asyncio
    async def test_emergency_recovery_low_confidence(self, rag_engine, failure_event):
        """Test that emergency recovery has appropriate low confidence"""
        playbook = rag_engine._create_emergency_recovery(failure_event)

        assert playbook.confidence < 0.5
        assert playbook.rag_tier == RAGTier.EMERGENCY

    @pytest.mark.asyncio
    async def test_playbook_target_service_matches(self, rag_engine, failure_event, sample_playbook):
        """Test that playbook actions target the correct service"""
        playbook = rag_engine._create_emergency_recovery(failure_event)

        for action in playbook.actions:
            assert action.target_service == failure_event.service

    @pytest.mark.asyncio
    async def test_signature_hash_used_for_caching(self, rag_engine, failure_event, sample_playbook):
        """Test that signature hash is passed to cache operations"""
        rag_engine.redis_tier.get_cached_playbook = AsyncMock(return_value=None)
        rag_engine.neo4j_tier.retrieve_similar_playbooks = AsyncMock(
            return_value=[sample_playbook]
        )

        signature_hash = "abc123def456"
        await rag_engine.retrieve_recovery_playbook(failure_event, signature_hash)

        # Verify hash was used
        call_args = rag_engine.redis_tier.cache_playbook.call_args
        assert call_args[0][0] == signature_hash
