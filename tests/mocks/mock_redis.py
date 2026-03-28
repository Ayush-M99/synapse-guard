"""
Mock Redis Cache for testing
In-memory key-value store without real Redis
"""

from typing import Optional, Dict, Any
from core.interfaces import ICacheStore
import time


class MockCacheStore(ICacheStore):
    """Mock implementation of Redis cache for testing"""

    def __init__(self):
        self.data = {}  # key -> (value, expiry_time)
        self.get_calls = []
        self.set_calls = []

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get value from cache"""
        self.get_calls.append({"key": key, "timestamp": str(__import__("datetime").datetime.utcnow())})

        if key not in self.data:
            return None

        value, expiry_time = self.data[key]

        # Check if expired
        if expiry_time and time.time() > expiry_time:
            del self.data[key]
            return None

        return value

    async def set(
        self, key: str, value: Dict[str, Any], ttl_seconds: int = 86400
    ) -> bool:
        """Set value in cache with TTL"""
        self.set_calls.append(
            {
                "key": key,
                "value": value,
                "ttl_seconds": ttl_seconds,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )

        expiry_time = time.time() + ttl_seconds if ttl_seconds else None
        self.data[key] = (value, expiry_time)
        return True

    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if key in self.data:
            del self.data[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if key not in self.data:
            return False

        value, expiry_time = self.data[key]

        # Check if expired
        if expiry_time and time.time() > expiry_time:
            del self.data[key]
            return False

        return True

    async def increment(self, key: str, delta: int = 1) -> int:
        """Increment counter"""
        if key not in self.data:
            self.data[key] = (delta, None)
            return delta

        value, expiry_time = self.data[key]
        new_value = (value or 0) + delta
        self.data[key] = (new_value, expiry_time)
        return new_value

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for testing"""
        return {
            "total_keys": len(self.data),
            "get_calls": len(self.get_calls),
            "set_calls": len(self.set_calls),
            "data": self.data,
        }

    def reset(self):
        """Reset mock state"""
        self.data = {}
        self.get_calls = []
        self.set_calls = []
