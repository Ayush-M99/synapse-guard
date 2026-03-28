"""
Unit tests for Antibody Agent - Redis Tier 1
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from antibody.models import RecoveryPlaybook, RecoveryAction, RecoveryActionType, RAGTier
from antibody.connectors.redis_tier import RedisCacheTier


@pytest.fixture
def redis_tier():
    """Create Redis tier instance for testing"""
    with patch('antibody.connectors.redis_tier.redis.Redis'):
        tier = RedisCacheTier(host="localhost", port=6379)
        tier.redis_client = Mock()
        tier.connected = True
        return tier


@pytest.fixture
def sample_playbook():
    """Sample recovery playbook for testing"""
    return RecoveryPlaybook(
        playbook_id="test-playbook-1",
        actions=[
            RecoveryAction(
                action_type=RecoveryActionType.RESTART_POD,
                target_service="payment-service",
                parameters={"grace_period": 5},
                priority=1,
            )
        ],
        attack_family="pod_crash",
        success_rate=0.98,
        avg_recovery_time_ms=1500.0,
        execution_count=5,
        rag_tier=RAGTier.REDIS,
    )


class TestRedisCacheTier:
    """Test cases for Redis Tier 1"""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful Redis connection"""
        with patch('antibody.connectors.redis_tier.redis.Redis') as mock_redis:
            mock_client = Mock()
            mock_redis.return_value = mock_client
            mock_client.ping.return_value = True

            tier = RedisCacheTier()
            result = await tier.connect()

            assert result is True
            assert tier.connected is True
            mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test failed Redis connection"""
        with patch('antibody.connectors.redis_tier.redis.Redis') as mock_redis:
            mock_redis.side_effect = Exception("Connection refused")

            tier = RedisCacheTier()
            result = await tier.connect()

            assert result is False
            assert tier.connected is False

    @pytest.mark.asyncio
    async def test_get_cached_playbook_hit(self, redis_tier, sample_playbook):
        """Test cache hit on playbook retrieval"""
        cache_key = "immunity:abc123def456"
        playbook_json = json.dumps(sample_playbook.to_dict())
        redis_tier.redis_client.get.return_value = playbook_json

        result = await redis_tier.get_cached_playbook("abc123def456")

        assert result is not None
        assert result.playbook_id == "test-playbook-1"
        assert result.rag_tier == RAGTier.REDIS
        redis_tier.redis_client.get.assert_called_once_with(cache_key)

    @pytest.mark.asyncio
    async def test_get_cached_playbook_miss(self, redis_tier):
        """Test cache miss on playbook retrieval"""
        redis_tier.redis_client.get.return_value = None

        result = await redis_tier.get_cached_playbook("abc123def456")

        assert result is None
        redis_tier.redis_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cached_playbook_not_connected(self):
        """Test cache retrieval when not connected"""
        tier = RedisCacheTier()
        tier.connected = False

        result = await tier.get_cached_playbook("abc123def456")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_playbook_success(self, redis_tier, sample_playbook):
        """Test successful playbook caching"""
        cache_key = "immunity:abc123def456"
        redis_tier.redis_client.setex.return_value = True

        result = await redis_tier.cache_playbook("abc123def456", sample_playbook)

        assert result is True
        redis_tier.redis_client.setex.assert_called_once()
        call_args = redis_tier.redis_client.setex.call_args
        assert call_args[0][0] == cache_key
        assert call_args[0][1] == redis_tier.cache_ttl

    @pytest.mark.asyncio
    async def test_cache_playbook_failure(self, redis_tier, sample_playbook):
        """Test playbook caching failure"""
        redis_tier.redis_client.setex.side_effect = Exception("Cache error")

        result = await redis_tier.cache_playbook("abc123def456", sample_playbook)

        assert result is False

    @pytest.mark.asyncio
    async def test_cache_ttl_24_hours(self, redis_tier, sample_playbook):
        """Test cache TTL is set to 24 hours"""
        redis_tier.redis_client.setex.return_value = True
        expected_ttl = 86400  # 24 hours in seconds

        await redis_tier.cache_playbook("abc123def456", sample_playbook)

        call_args = redis_tier.redis_client.setex.call_args
        assert call_args[0][1] == expected_ttl

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, redis_tier):
        """Test retrieval of cache statistics"""
        redis_tier.redis_client.info.return_value = {
            "used_memory_mb": 512,
            "evicted_keys": 5,
        }
        redis_tier.redis_client.keys.return_value = ["immunity:1", "immunity:2", "immunity:3"]

        stats = await redis_tier.get_cache_stats()

        assert stats["connected"] is True
        assert stats["cached_playbooks"] == 3
        assert stats["memory_used_mb"] == 512
        assert stats["evicted_keys"] == 5

    @pytest.mark.asyncio
    async def test_clear_cache(self, redis_tier):
        """Test clearing all cache entries"""
        redis_tier.redis_client.keys.return_value = ["immunity:1", "immunity:2"]
        redis_tier.redis_client.delete.return_value = 2

        result = await redis_tier.clear_cache()

        assert result is True
        redis_tier.redis_client.delete.assert_called_once()
        call_args = redis_tier.redis_client.delete.call_args
        assert len(call_args[0]) == 2  # Two keys deleted

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, redis_tier):
        """Test health check when Redis is healthy"""
        redis_tier.redis_client.ping.return_value = True

        result = await redis_tier.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, redis_tier):
        """Test health check when Redis is unhealthy"""
        redis_tier.redis_client.ping.side_effect = Exception("Connection lost")

        result = await redis_tier.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self, redis_tier):
        """Test Redis disconnection"""
        redis_tier.redis_client.close = Mock()

        await redis_tier.disconnect()

        assert redis_tier.connected is False
        redis_tier.redis_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_playbook_serialization_roundtrip(self, redis_tier, sample_playbook):
        """Test playbook serialization and deserialization"""
        redis_tier.redis_client.setex.return_value = True
        redis_tier.redis_client.get.return_value = json.dumps(sample_playbook.to_dict())

        # Cache it
        await redis_tier.cache_playbook("hash1", sample_playbook)

        # Retrieve it
        retrieved = await redis_tier.get_cached_playbook("hash1")

        assert retrieved.playbook_id == sample_playbook.playbook_id
        assert retrieved.attack_family == sample_playbook.attack_family
        assert retrieved.success_rate == sample_playbook.success_rate
        assert len(retrieved.actions) == len(sample_playbook.actions)
