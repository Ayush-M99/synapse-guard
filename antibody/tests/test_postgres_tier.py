"""
Unit tests for Antibody Agent - PostgreSQL Tier 3
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from antibody.models import RecoveryActionType, DNARecord
from antibody.connectors.postgres_tier import PostgresDBTier


@pytest.fixture
def postgres_tier():
    """Create PostgreSQL tier instance for testing"""
    with patch('antibody.connectors.postgres_tier.psycopg2.connect'):
        tier = PostgresDBTier(host="localhost")
        tier.conn = Mock()
        tier.connected = True
        return tier


class TestPostgresDBTier:
    """Test cases for PostgreSQL Tier 3"""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful PostgreSQL connection"""
        with patch('antibody.connectors.postgres_tier.psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_connect.return_value = mock_conn

            tier = PostgresDBTier()
            result = await tier.connect()

            assert result is True
            assert tier.connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test failed PostgreSQL connection"""
        with patch('antibody.connectors.postgres_tier.psycopg2.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")

            tier = PostgresDBTier()
            result = await tier.connect()

            assert result is False
            assert tier.connected is False

    @pytest.mark.asyncio
    async def test_retrieve_historical_recoveries_found(self, postgres_tier):
        """Test retrieval of historical recoveries"""
        mock_cursor = Mock()
        mock_record = {
            "recovery_actions": '[{"type": "restart_pod", "target": "payment-service"}]',
            "recovery_ms": 1500.0,
            "execution_count": 5,
            "success_rate": 0.98,
        }
        mock_cursor.fetchall.return_value = [mock_record]

        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)

        playbooks = await postgres_tier.retrieve_historical_recoveries(
            attack_family="pod_crash",
            limit=10,
        )

        assert len(playbooks) > 0
        assert playbooks[0].attack_family == "pod_crash"
        assert playbooks[0].success_rate == 0.98

    @pytest.mark.asyncio
    async def test_retrieve_historical_recoveries_not_found(self, postgres_tier):
        """Test retrieval when no historical recoveries found"""
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []

        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)

        playbooks = await postgres_tier.retrieve_historical_recoveries(
            attack_family="unknown_attack",
            limit=10,
        )

        assert len(playbooks) == 0

    @pytest.mark.asyncio
    async def test_retrieve_historical_recoveries_not_connected(self):
        """Test retrieval when not connected"""
        tier = PostgresDBTier()
        tier.connected = False

        playbooks = await tier.retrieve_historical_recoveries(
            attack_family="pod_crash",
            limit=10,
        )

        assert playbooks == []

    @pytest.mark.asyncio
    async def test_record_recovery_generation_success(self, postgres_tier):
        """Test recording recovery generation"""
        mock_cursor = Mock()
        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)
        postgres_tier.conn.commit = Mock()

        dna_record = DNARecord(
            virus_gen=1,
            antibody_gen=1,
            strand_id="pod_crash_A",
            strand_family="pod_crash",
            target_service="payment-service",
            injection_ts=datetime.utcnow(),
            detection_ts=datetime.utcnow(),
            recovery_ts=datetime.utcnow(),
            recovery_ms=1500.0,
            recovery_actions=[{"type": "restart_pod"}],
            success=True,
            cache_hit=False,
            rag_source="neo4j",
            rf_label="pod_crash",
            rf_confidence=0.91,
            detection_path="isolation_forest",
        )

        result = await postgres_tier.record_recovery_generation(dna_record)

        assert result is True
        mock_cursor.execute.assert_called_once()
        postgres_tier.conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_recovery_generation_not_connected(self):
        """Test recording when not connected"""
        tier = PostgresDBTier()
        tier.connected = False

        dna_record = DNARecord(
            virus_gen=1,
            antibody_gen=1,
            strand_id="pod_crash_A",
            strand_family="pod_crash",
            target_service="payment-service",
            injection_ts=datetime.utcnow(),
            detection_ts=datetime.utcnow(),
            recovery_ts=datetime.utcnow(),
            recovery_ms=1500.0,
            recovery_actions=[],
            success=True,
            cache_hit=False,
            rag_source="neo4j",
            rf_label="pod_crash",
            rf_confidence=0.91,
            detection_path="isolation_forest",
        )

        result = await tier.record_recovery_generation(dna_record)

        assert result is False

    @pytest.mark.asyncio
    async def test_record_recovery_generation_failure(self, postgres_tier):
        """Test handling of record failure"""
        mock_cursor = Mock()
        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_cursor.execute.side_effect = Exception("Database error")
        postgres_tier.conn.rollback = Mock()

        dna_record = DNARecord(
            virus_gen=1,
            antibody_gen=1,
            strand_id="pod_crash_A",
            strand_family="pod_crash",
            target_service="payment-service",
            injection_ts=datetime.utcnow(),
            detection_ts=datetime.utcnow(),
            recovery_ts=datetime.utcnow(),
            recovery_ms=1500.0,
            recovery_actions=[],
            success=True,
            cache_hit=False,
            rag_source="neo4j",
            rf_label="pod_crash",
            rf_confidence=0.91,
            detection_path="isolation_forest",
        )

        result = await postgres_tier.record_recovery_generation(dna_record)

        assert result is False
        postgres_tier.conn.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, postgres_tier):
        """Test health check when PostgreSQL is healthy"""
        mock_cursor = Mock()
        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)

        result = await postgres_tier.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, postgres_tier):
        """Test health check when PostgreSQL is unhealthy"""
        mock_cursor = Mock()
        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)
        mock_cursor.execute.side_effect = Exception("Connection lost")

        result = await postgres_tier.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self, postgres_tier):
        """Test PostgreSQL disconnection"""
        postgres_tier.conn.close = Mock()

        await postgres_tier.disconnect()

        assert postgres_tier.connected is False
        postgres_tier.conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_recovery_actions(self, postgres_tier):
        """Test parsing of recovery actions from JSON"""
        actions_json = '[{"type": "restart_pod", "target": "payment-service", "parameters": {"grace_period": 5}}]'

        actions = postgres_tier._parse_actions(actions_json)

        assert len(actions) > 0
        assert actions[0].action_type == RecoveryActionType.RESTART_POD
        assert actions[0].target_service == "payment-service"

    @pytest.mark.asyncio
    async def test_parse_recovery_actions_invalid(self, postgres_tier):
        """Test parsing of invalid recovery actions"""
        invalid_json = "not valid json"

        actions = postgres_tier._parse_actions(invalid_json)

        assert actions == []

    @pytest.mark.asyncio
    async def test_recovery_ranking_by_speed(self, postgres_tier):
        """Test that recoveries are ranked by speed"""
        mock_cursor = Mock()

        # Two historical recoveries - different speeds
        record1 = {
            "recovery_actions": "[]",
            "recovery_ms": 1500.0,
            "execution_count": 5,
            "success_rate": 0.98,
        }
        record2 = {
            "recovery_actions": "[]",
            "recovery_ms": 3000.0,
            "execution_count": 3,
            "success_rate": 0.95,
        }

        mock_cursor.fetchall.return_value = [record1, record2]
        postgres_tier.conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        postgres_tier.conn.cursor.return_value.__exit__ = Mock(return_value=None)

        playbooks = await postgres_tier.retrieve_historical_recoveries(
            attack_family="pod_crash",
            limit=2,
        )

        # Fastest should be first
        assert playbooks[0].avg_recovery_time_ms == 1500.0
