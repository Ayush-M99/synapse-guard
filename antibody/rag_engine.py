"""
RAG Engine: Retrieval-Augmented Generation
Coordinates 3-tier recovery playbook retrieval
"""

import logging
import uuid
from typing import Optional

from .models import FailureEvent, RecoveryPlaybook, RecoveryAction, RecoveryActionType, RAGTier

logger = logging.getLogger(__name__)


class RAGRecoveryEngine:
    """
    Retrieval-Augmented Generation for Recovery

    3-Tier Fallback Chain:
    1. Tier 1 (Redis): O(1) cache lookup - 0.8s recovery
    2. Tier 2 (Neo4j): Similarity search - 2s recovery
    3. Tier 3 (PostgreSQL): Historical + LLM - 18s recovery
    4. Emergency: Hardcoded fallback - always works
    """

    def __init__(
        self,
        redis_tier,  # Injected RedisCacheTier
        neo4j_tier,  # Injected Neo4jGraphTier
        postgres_tier,  # Injected PostgresDBTier
    ):
        self.redis_tier = redis_tier
        self.neo4j_tier = neo4j_tier
        self.postgres_tier = postgres_tier

    async def retrieve_recovery_playbook(
        self,
        failure_event: FailureEvent,
        signature_hash: str,
    ) -> Optional[RecoveryPlaybook]:
        """
        Retrieve recovery playbook through 3-tier RAG system

        Flow:
        1. Try Redis (cache) - fastest
        2. Try Neo4j (graph) - smart
        3. Try PostgreSQL (DNA) - learning
        4. Fall back to hardcoded emergency recovery

        Args:
            failure_event: Failure from ML Pipeline
            signature_hash: SHA256 hash of failure signature

        Returns:
            RecoveryPlaybook ready to execute, or None if all tiers fail

        Example:
            playbook = await rag_engine.retrieve_recovery_playbook(
                failure_event=failure_event,
                signature_hash="abc123def456..."
            )
            if playbook:
                print(f"Retrieved via {playbook.rag_tier.value}")
        """

        logger.info("🔍 Starting 3-tier RAG retrieval...")

        # ====================================================================
        # TIER 1: REDIS (Cache) - O(1), ~5ms
        # ====================================================================
        logger.info("📦 Tier 1: Checking Redis cache...")
        playbook = await self.redis_tier.get_cached_playbook(signature_hash)

        if playbook:
            logger.info(f"✅ Tier 1 HIT in {playbook.rag_tier.value}")
            playbook.rag_tier = RAGTier.REDIS
            return playbook

        logger.info("❄️  Tier 1 MISS - proceeding to Tier 2")

        # ====================================================================
        # TIER 2: NEO4J (Graph) - Similarity search, ~2s
        # ====================================================================
        logger.info("📊 Tier 2: Querying Neo4j knowledge graph...")
        playbooks = await self.neo4j_tier.retrieve_similar_playbooks(
            attack_family=failure_event.attack_family,
            service=failure_event.service,
            anomaly_score=failure_event.anomaly_score,
            rf_confidence=failure_event.rf_confidence,
            limit=5,
        )

        if playbooks:
            playbook = playbooks[0]  # Sorted by similarity + success rate
            logger.info(f"✅ Tier 2 HIT: {len(playbooks)} similar playbooks found")
            playbook.rag_tier = RAGTier.NEO4J

            # Cache for future use (Tier 1)
            await self.redis_tier.cache_playbook(signature_hash, playbook)
            logger.info("💾 Cached playbook in Redis")

            return playbook

        logger.info("❄️  Tier 2 MISS - proceeding to Tier 3")

        # ====================================================================
        # TIER 3: POSTGRESQL (DNA Store) - Historical + Optional LLM, ~18s
        # ====================================================================
        logger.info("🧬 Tier 3: Querying PostgreSQL DNA store...")
        playbooks = await self.postgres_tier.retrieve_historical_recoveries(
            attack_family=failure_event.attack_family,
            limit=10,
        )

        if playbooks:
            playbook = playbooks[0]  # Best historical recovery
            logger.info(f"✅ Tier 3 HIT: {len(playbooks)} historical playbooks found")
            playbook.rag_tier = RAGTier.POSTGRES

            # Cache for future use
            await self.redis_tier.cache_playbook(signature_hash, playbook)
            logger.info("💾 Cached playbook in Redis")

            return playbook

        logger.info("❄️  Tier 3 MISS - using emergency fallback")

        # ====================================================================
        # EMERGENCY FALLBACK: Hardcoded recovery (always works)
        # ====================================================================
        logger.warning(
            f"⚠️  No recovery found in any tier for {failure_event.attack_family}"
        )
        playbook = self._create_emergency_recovery(failure_event)

        # Cache emergency recovery for quick access next time
        await self.redis_tier.cache_playbook(signature_hash, playbook)

        return playbook

    def _create_emergency_recovery(self, failure_event: FailureEvent) -> RecoveryPlaybook:
        """
        Create hardcoded emergency recovery (last resort)

        Always works - guaranteed to have some mitigating effect:
        1. Restart the affected service pod
        2. Scale to 2 replicas for redundancy
        3. (Optional) Apply rate limiting to reduce load

        Args:
            failure_event: Failure event

        Returns:
            RecoveryPlaybook with emergency actions
        """
        logger.warning(f"⚠️  Creating emergency recovery for {failure_event.attack_family}")

        actions = [
            RecoveryAction(
                action_type=RecoveryActionType.RESTART_POD,
                target_service=failure_event.service,
                parameters={"grace_period": 5},
                priority=1,
                rollback_on_failure=False,
            ),
            RecoveryAction(
                action_type=RecoveryActionType.SCALE_REPLICAS,
                target_service=failure_event.service,
                parameters={"replicas": 2},
                priority=1,
                rollback_on_failure=False,
            ),
        ]

        playbook = RecoveryPlaybook(
            playbook_id=f"emergency-{failure_event.service}-{uuid.uuid4().hex[:8]}",
            actions=actions,
            attack_family=failure_event.attack_family,
            success_rate=0.5,  # Low confidence on untested strategy
            avg_recovery_time_ms=15000,
            execution_count=0,
            generation=0,
            rag_tier=RAGTier.EMERGENCY,
            confidence=0.3,
        )

        return playbook
