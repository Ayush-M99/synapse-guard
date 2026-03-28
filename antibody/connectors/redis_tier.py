"""
Tier 1: Redis Immunity Cache Connector
Fast O(1) playbook lookups (5ms recovery)
"""

import json
import logging
from typing import Optional

import redis

from ..models import RecoveryPlaybook, RAGTier

logger = logging.getLogger(__name__)


class RedisCacheTier:
    """Redis Tier 1 cache for known attacks (immunity)"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str = "darwin123",
        db: int = 0,
        cache_ttl: int = 86400,  # 24 hours
    ):
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.cache_ttl = cache_ttl
        self.redis_client = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to Redis"""
        try:
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            self.redis_client.ping()
            self.connected = True
            logger.info(f"✅ Connected to Redis at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            self.redis_client.close()
            self.connected = False
            logger.info("Disconnected from Redis")

    async def get_cached_playbook(self, signature_hash: str) -> Optional[RecoveryPlaybook]:
        """
        Retrieve cached playbook from Redis (Tier 1 fast path)

        Key Pattern: immunity:{signature_hash}
        Value: JSON-serialized RecoveryPlaybook

        Args:
            signature_hash: SHA256 hash of failure signature

        Returns:
            RecoveryPlaybook if found, None if cache miss

        Example:
            hash = "abc123def456..."
            playbook = await redis_tier.get_cached_playbook(hash)
            if playbook:  # Cache hit
                print(f"Found cached recovery: {playbook.success_rate}")
            else:  # Cache miss - go to Tier 2
                print("Cache miss - query Neo4j")
        """
        if not self.connected:
            logger.warning("Redis not connected")
            return None

        try:
            cache_key = f"immunity:{signature_hash}"
            cached_data = self.redis_client.get(cache_key)

            if cached_data:
                logger.info(f"🔥 Redis HIT: {cache_key}")
                playbook_dict = json.loads(cached_data)
                playbook = RecoveryPlaybook.from_dict(playbook_dict)
                playbook.rag_tier = RAGTier.REDIS  # Mark as from cache
                return playbook
            else:
                logger.info(f"❄️  Redis MISS: {cache_key}")
                return None

        except Exception as e:
            logger.error(f"Failed to get cached playbook: {e}")
            return None

    async def cache_playbook(
        self, signature_hash: str, playbook: RecoveryPlaybook
    ) -> bool:
        """
        Cache playbook in Redis for future use (24 hour TTL)

        Called after successful recovery to enable cache hit on repeat attacks

        Args:
            signature_hash: SHA256 hash of failure signature
            playbook: RecoveryPlaybook to cache

        Returns:
            True if cached successfully, False otherwise

        Example:
            # After recovery succeeds:
            success = await redis_tier.cache_playbook(signature_hash, playbook)
            if success:
                print("Playbook cached for 24 hours")
        """
        if not self.connected:
            logger.warning("Redis not connected")
            return False

        try:
            cache_key = f"immunity:{signature_hash}"
            playbook_json = json.dumps(playbook.to_dict())

            # Set with TTL (24 hours = 86400 seconds)
            self.redis_client.setex(cache_key, self.cache_ttl, playbook_json)
            logger.info(f"💾 Cached playbook: {cache_key} (TTL: {self.cache_ttl}s)")
            return True

        except Exception as e:
            logger.error(f"Failed to cache playbook: {e}")
            return False

    async def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self.connected:
            return {"connected": False}

        try:
            info = self.redis_client.info()
            keys_matching = self.redis_client.keys("immunity:*")

            return {
                "connected": True,
                "cached_playbooks": len(keys_matching),
                "memory_used_mb": info.get("used_memory_mb", 0),
                "evicted_keys": info.get("evicted_keys", 0),
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

    async def clear_cache(self) -> bool:
        """Clear all immunity cache entries (testing only)"""
        if not self.connected:
            return False

        try:
            pattern = "immunity:*"
            keys = self.redis_client.keys(pattern)
            if keys:
                self.redis_client.delete(*keys)
                logger.warning(f"🗑️  Cleared {len(keys)} cache entries")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False

    async def health_check(self) -> bool:
        """Health check for Redis"""
        if not self.connected:
            return False

        try:
            self.redis_client.ping()
            return True
        except Exception:
            return False
