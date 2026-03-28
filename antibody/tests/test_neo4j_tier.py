"""
Unit tests for Antibody Agent - Neo4j Tier 2
"""

import pytest
from unittest.mock import Mock, patch

from antibody.models import RecoveryPlaybook, RecoveryAction, RecoveryActionType, RAGTier
from antibody.connectors.neo4j_tier import Neo4jGraphTier


@pytest.fixture
def neo4j_tier():
    """Create Neo4j tier instance for testing"""
    with patch('antibody.connectors.neo4j_tier.GraphDatabase.driver'):
        tier = Neo4jGraphTier(uri="bolt://localhost:7687")
        tier.driver = Mock()
        tier.connected = True
        return tier


class TestNeo4jGraphTier:
    """Test cases for Neo4j Tier 2"""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful Neo4j connection"""
        with patch('antibody.connectors.neo4j_tier.GraphDatabase.driver') as mock_driver:
            mock_session = Mock()
            mock_driver.return_value.session.return_value.__enter__ = Mock(return_value=mock_session)
            mock_driver.return_value.session.return_value.__exit__ = Mock(return_value=None)
            mock_session.run.return_value = Mock()

            tier = Neo4jGraphTier()
            result = await tier.connect()

            assert result is True
            assert tier.connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test failed Neo4j connection"""
        with patch('antibody.connectors.neo4j_tier.GraphDatabase.driver') as mock_driver:
            mock_driver.side_effect = Exception("Connection refused")

            tier = Neo4jGraphTier()
            result = await tier.connect()

            assert result is False
            assert tier.connected is False

    @pytest.mark.asyncio
    async def test_retrieve_similar_playbooks_found(self, neo4j_tier):
        """Test retrieval of similar playbooks"""
        mock_session = Mock()
        mock_result = Mock()
        mock_node = {
            "id": "playbook-1",
            "family": "pod_crash",
            "success_rate": 0.98,
            "recovery_time": 2000,
            "execution_count": 5,
        }
        mock_result.data.return_value = [{"playbook": mock_node}]

        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.return_value = mock_result

        playbooks = await neo4j_tier.retrieve_similar_playbooks(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
            limit=5,
        )

        assert len(playbooks) > 0
        assert playbooks[0].rag_tier == RAGTier.NEO4J

    @pytest.mark.asyncio
    async def test_retrieve_similar_playbooks_not_found(self, neo4j_tier):
        """Test retrieval when no similar playbooks found"""
        mock_session = Mock()
        mock_result = Mock()
        mock_result.data.return_value = []

        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.return_value = mock_result

        playbooks = await neo4j_tier.retrieve_similar_playbooks(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
        )

        assert len(playbooks) == 0

    @pytest.mark.asyncio
    async def test_retrieve_similar_playbooks_not_connected(self):
        """Test retrieval when not connected"""
        tier = Neo4jGraphTier()
        tier.connected = False

        playbooks = await tier.retrieve_similar_playbooks(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
        )

        assert playbooks == []

    @pytest.mark.asyncio
    async def test_store_attack_recovery_success(self, neo4j_tier):
        """Test storing attack-recovery relationship"""
        mock_session = Mock()
        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.return_value = Mock()

        playbook = RecoveryPlaybook(
            playbook_id="test-1",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=1500,
        )

        result = await neo4j_tier.store_attack_recovery(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
            playbook=playbook,
            recovery_time_ms=1500,
            success=True,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_store_attack_recovery_not_connected(self):
        """Test storing when not connected"""
        tier = Neo4jGraphTier()
        tier.connected = False

        playbook = RecoveryPlaybook(
            playbook_id="test-1",
            actions=[],
            attack_family="pod_crash",
            success_rate=0.98,
            avg_recovery_time_ms=1500,
        )

        result = await tier.store_attack_recovery(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
            playbook=playbook,
            recovery_time_ms=1500,
            success=True,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, neo4j_tier):
        """Test health check when Neo4j is healthy"""
        mock_session = Mock()
        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.return_value = Mock()

        result = await neo4j_tier.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, neo4j_tier):
        """Test health check when Neo4j is unhealthy"""
        mock_session = Mock()
        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.side_effect = Exception("Connection lost")

        result = await neo4j_tier.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self, neo4j_tier):
        """Test Neo4j disconnection"""
        neo4j_tier.driver.close = Mock()

        await neo4j_tier.disconnect()

        assert neo4j_tier.connected is False
        neo4j_tier.driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_similarity_score_calculation(self, neo4j_tier):
        """Test that similarity scores are used for ranking"""
        mock_session = Mock()

        # Two playbooks - one closer match than other
        mock_result = Mock()
        mock_result.data.return_value = [
            {"playbook": {"id": "closer", "success_rate": 0.98}},
            {"playbook": {"id": "farther", "success_rate": 0.95}},
        ]

        neo4j_tier.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        neo4j_tier.driver.session.return_value.__exit__ = Mock(return_value=None)
        mock_session.run.return_value = mock_result

        playbooks = await neo4j_tier.retrieve_similar_playbooks(
            attack_family="pod_crash",
            service="payment-service",
            anomaly_score=0.92,
            rf_confidence=0.88,
            limit=2,
        )

        # First playbook should be the closest match
        assert playbooks[0].playbook_id == "closer"
        assert playbooks[1].playbook_id == "farther"
