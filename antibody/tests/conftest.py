"""
Shared test fixtures and configuration
"""

import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_k8s_api():
    """Mock Kubernetes API client"""
    from unittest.mock import Mock

    api = Mock()
    api.list_namespaced_pod = Mock()
    api.delete_namespaced_pod = Mock()
    api.patch_namespaced_deployment_scale = Mock()
    return api


@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    from unittest.mock import Mock

    redis = Mock()
    redis.get = Mock()
    redis.setex = Mock()
    redis.delete = Mock()
    redis.keys = Mock()
    redis.ping = Mock(return_value=True)
    return redis


@pytest.fixture
def mock_postgres():
    """Mock PostgreSQL connection"""
    from unittest.mock import Mock

    conn = Mock()
    conn.cursor = Mock()
    conn.commit = Mock()
    conn.rollback = Mock()
    return conn


@pytest.fixture
def mock_neo4j():
    """Mock Neo4j driver"""
    from unittest.mock import Mock

    driver = Mock()
    driver.session = Mock()
    driver.close = Mock()
    return driver


@pytest.fixture
def mock_nats():
    """Mock NATS client"""
    from unittest.mock import Mock, AsyncMock

    client = Mock()
    client.connect = AsyncMock(return_value=None)
    client.close = AsyncMock(return_value=None)
    client.subscribe = AsyncMock(return_value=Mock())
    client.publish = AsyncMock(return_value=None)
    return client
