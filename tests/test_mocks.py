"""
Unit tests for mock implementations
"""

import pytest
import asyncio

from tests.mocks import (
    MockKubernetesClient,
    MockMessageBus,
    MockCacheStore,
    MockKnowledgeGraph,
)


class TestMockKubernetesClient:
    """Test MockKubernetesClient"""

    @pytest.mark.asyncio
    async def test_delete_pod(self):
        """Test pod deletion"""
        k8s = MockKubernetesClient()

        # Get initial pod list
        pods_before = await k8s.list_pods("darwin-target")
        assert len(pods_before) > 0

        # Delete a pod
        pod_name = pods_before[0]["name"]
        result = await k8s.delete_pod("darwin-target", pod_name)

        assert result is True
        assert len(k8s.deleted_pods) == 1

        # Verify new pod was created (replacement)
        pods_after = await k8s.list_pods("darwin-target")
        assert len(pods_after) == len(pods_before)

    @pytest.mark.asyncio
    async def test_scale_deployment(self):
        """Test deployment scaling"""
        k8s = MockKubernetesClient()

        result = await k8s.scale_deployment("darwin-target", "payment-service", 5)

        assert result is True
        assert len(k8s.scaled_deployments) == 1
        assert k8s.scaled_deployments[0]["replicas"] == 5

    @pytest.mark.asyncio
    async def test_network_policy(self):
        """Test network policy creation and deletion"""
        k8s = MockKubernetesClient()

        # Create policy
        result = await k8s.create_network_policy(
            "darwin-target", "block-payment", {"ingress": []}
        )
        assert result is True
        assert len(k8s.created_network_policies) == 1

        # Delete policy
        result = await k8s.delete_network_policy("darwin-target", "block-payment")
        assert result is True
        assert len(k8s.deleted_network_policies) == 1

    @pytest.mark.asyncio
    async def test_operations_history(self):
        """Test operations history tracking"""
        k8s = MockKubernetesClient()

        # Perform operations
        pods = await k8s.list_pods("darwin-target")
        await k8s.delete_pod("darwin-target", pods[0]["name"])
        await k8s.scale_deployment("darwin-target", "payment-service", 3)

        history = k8s.get_operations_history()
        assert len(history["deleted_pods"]) == 1
        assert len(history["scaled_deployments"]) == 1


class TestMockMessageBus:
    """Test MockMessageBus"""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connection management"""
        bus = MockMessageBus()

        await bus.connect()
        assert bus.connected is True

        await bus.disconnect()
        assert bus.connected is False

    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        """Test pub/sub messaging"""
        bus = MockMessageBus()
        await bus.connect()

        received_messages = []

        async def callback(message):
            received_messages.append(message)

        # Subscribe to channel
        await bus.subscribe("darwin.test", callback)

        # Publish message
        test_message = {"type": "test", "value": 42}
        await bus.publish("darwin.test", test_message)

        # Verify message was received
        await asyncio.sleep(0.1)  # Give callback time to process
        assert len(received_messages) == 1
        assert received_messages[0] == test_message

    @pytest.mark.asyncio
    async def test_published_messages_tracking(self):
        """Test tracking of published messages"""
        bus = MockMessageBus()
        await bus.connect()

        # Publish multiple messages
        for i in range(3):
            await bus.publish("darwin.test", {"id": i})

        published = bus.get_published_messages("darwin.test")
        assert len(published) == 3

    @pytest.mark.asyncio
    async def test_wildcard_subscription(self):
        """Test subscribing to multiple channels"""
        bus = MockMessageBus()
        await bus.connect()

        messages = []

        async def callback(msg):
            messages.append(msg)

        # Subscribe to multiple channels
        await bus.subscribe("darwin.failure.detected", callback)
        await bus.subscribe("darwin.recovery.completed", callback)

        # Publish to both
        await bus.publish("darwin.failure.detected", {"event": "failure"})
        await bus.publish("darwin.recovery.completed", {"event": "recovery"})

        await asyncio.sleep(0.1)
        assert len(messages) == 2


class TestMockCacheStore:
    """Test MockCacheStore"""

    @pytest.mark.asyncio
    async def test_get_set(self):
        """Test basic get/set operations"""
        cache = MockCacheStore()

        # Set a value
        await cache.set("key1", {"data": "value1"})

        # Get it back
        result = await cache.get("key1")
        assert result == {"data": "value1"}

    @pytest.mark.asyncio
    async def test_key_expiration(self):
        """Test key TTL and expiration"""
        cache = MockCacheStore()

        # Set with short TTL
        await cache.set("temp_key", {"data": "temp"}, ttl_seconds=0.1)

        # Should exist initially
        result = await cache.get("temp_key")
        assert result is not None

        # Wait for expiration
        await asyncio.sleep(0.2)

        # Should be gone
        result = await cache.get("temp_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists_delete(self):
        """Test exists and delete operations"""
        cache = MockCacheStore()

        await cache.set("key1", {"data": "value"})
        assert await cache.exists("key1") is True

        await cache.delete("key1")
        assert await cache.exists("key1") is False

    @pytest.mark.asyncio
    async def test_increment_counter(self):
        """Test counter incrementing"""
        cache = MockCacheStore()

        # Increment non-existent key (should start at 0)
        result = await cache.increment("counter")
        assert result == 1

        # Increment again
        result = await cache.increment("counter")
        assert result == 2

    @pytest.mark.asyncio
    async def test_cache_statistics(self):
        """Test cache statistics tracking"""
        cache = MockCacheStore()

        await cache.set("key1", {"data": "value"})
        await cache.get("key1")
        await cache.get("nonexistent")

        stats = cache.get_cache_stats()
        assert stats["total_keys"] == 1
        assert stats["set_calls"] == 1
        assert stats["get_calls"] == 2


class TestMockKnowledgeGraph:
    """Test MockKnowledgeGraph"""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connection management"""
        graph = MockKnowledgeGraph()

        await graph.connect()
        assert graph.connected is True

        await graph.disconnect()
        assert graph.connected is False

    @pytest.mark.asyncio
    async def test_store_failure_recovery(self):
        """Test storing failure->recovery relationships"""
        graph = MockKnowledgeGraph()
        await graph.connect()

        failure = {"service": "payment", "anomaly_score": 0.85}
        recovery = {
            "actions": [{"type": "restart_pod"}],
            "success_rate": 0.95,
            "avg_recovery_time_seconds": 2.1,
        }

        recovery_id = await graph.store_failure_recovery(failure, recovery)

        assert recovery_id is not None
        assert len(graph.failures) == 1
        assert len(graph.recoveries) == 1
        assert len(graph.relationships) == 1

    @pytest.mark.asyncio
    async def test_retrieve_similar_failures(self):
        """Test retrieving similar failures"""
        graph = MockKnowledgeGraph()
        await graph.connect()

        # Store first failure
        failure1 = {"service": "payment", "anomaly_score": 0.85}
        recovery1 = {
            "actions": [{"type": "restart_pod"}],
            "success_rate": 0.95,
            "avg_recovery_time_seconds": 2.1,
        }
        await graph.store_failure_recovery(failure1, recovery1)

        # Store second failure (same service, similar score)
        failure2 = {"service": "payment", "anomaly_score": 0.87}
        recovery2 = {
            "actions": [{"type": "scale_replicas"}],
            "success_rate": 0.92,
            "avg_recovery_time_seconds": 1.8,
        }
        await graph.store_failure_recovery(failure2, recovery2)

        # Query for similar
        query = {"service": "payment", "anomaly_score": 0.84}
        results = await graph.retrieve_similar_failures(query, limit=5)

        # Should find similar failures
        assert len(results) > 0
        assert results[0]["signature"]["service"] == "payment"

    @pytest.mark.asyncio
    async def test_graph_statistics(self):
        """Test graph statistics"""
        graph = MockKnowledgeGraph()
        await graph.connect()

        failure = {"service": "payment", "anomaly_score": 0.85}
        recovery = {"actions": [], "success_rate": 0.95}
        await graph.store_failure_recovery(failure, recovery)

        stats = graph.get_graph_stats()
        assert stats["total_failures"] == 1
        assert stats["total_recoveries"] == 1
        assert stats["total_relationships"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
