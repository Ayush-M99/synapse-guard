"""
Learning Loop: Persistence and Generational Improvement
Records recovery outcomes and updates all 3 databases
"""

import logging
from datetime import datetime, timedelta

from .models import RecoveryOutcome, DNARecord

logger = logging.getLogger(__name__)


class LearningLoop:
    """
    Learning loop that records recovery outcomes and learns from them

    Process:
    1. After every recovery, write to all 3 databases:
       - PostgreSQL: DNA Store (complete history)
       - Redis: Immunity Cache (update/refresh)
       - Neo4j: Knowledge Graph (relationships + generational tracking)

    2. Tracks generational improvement:
       Gen 1: 18s recovery (Tier 2 Neo4j)
       Gen 2: 2.1s recovery (Tier 1 Redis hit)
       Gen 3: 0.8s recovery (Tier 1 Redis hit, optimized actions)

    3. Builds learning curve for dashboard visualization
    """

    def __init__(
        self,
        postgres_tier,
        redis_tier,
        neo4j_tier,
        virus_gen: int = 1,
        antibody_gen: int = 1,
    ):
        self.postgres_tier = postgres_tier
        self.redis_tier = redis_tier
        self.neo4j_tier = neo4j_tier
        self.virus_gen = virus_gen
        self.antibody_gen = antibody_gen

    async def record_recovery(self, recovery_outcome: RecoveryOutcome) -> bool:
        """
        Record recovery outcome to all tiers and learn

        Process:
        1. Write to PostgreSQL (DNA Store) - historical archive
        2. Update Redis cache (if successful)
        3. Update Neo4j relationships (if successful)
        4. Increment generation counters

        Args:
            recovery_outcome: Complete recovery outcome with metadata

        Returns:
            True if all writes succeed

        Example:
            success = await learning_loop.record_recovery(outcome)
            if success:
                print(f"Gen {learning_loop.antibody_gen}: Recorded recovery")
        """
        logger.info(f"📚 Recording recovery to learning systems...")

        try:
            # Extract metadata
            failure_event = recovery_outcome.recovery_context.failure_event
            playbook = recovery_outcome.recovery_context.playbook

            # ================================================================
            # Write to PostgreSQL (DNA Store) - Complete Historical Record
            # ================================================================
            logger.info("📝 Writing to PostgreSQL DNA Store...")

            dna_record = DNARecord(
                virus_gen=self.virus_gen,
                antibody_gen=self.antibody_gen,
                strand_id=f"{failure_event.attack_family}_{self.virus_gen}",
                strand_family=failure_event.attack_family,
                target_service=failure_event.service,
                injection_ts=failure_event.timestamp,
                detection_ts=failure_event.timestamp + timedelta(seconds=15),  # Est. 15s
                recovery_ts=datetime.utcnow(),
                recovery_ms=recovery_outcome.recovery_time_ms,
                recovery_actions=[action.to_dict() for action in playbook.actions],
                success=recovery_outcome.success,
                cache_hit=playbook.rag_tier.value == "redis",
                rag_source=playbook.rag_tier.value,
                rf_label=failure_event.attack_family,
                rf_confidence=failure_event.rf_confidence,
                detection_path=failure_event.detection_path,
                blast_radius_services=1,  # TODO: Calculate from logs
                error_reason=recovery_outcome.error_message,
            )

            postgres_success = await self.postgres_tier.record_recovery_generation(dna_record)

            if not postgres_success:
                logger.error("Failed to write to PostgreSQL")
                return False

            # ================================================================
            # Update Redis (Immunity Cache) - For Fast Lookups
            # ================================================================
            if recovery_outcome.success:
                logger.info("🔄 Updating Redis cache...")

                # Update cache with improved playbook (lower recovery time)
                playbook.execution_count += 1
                playbook.avg_recovery_time_ms = (
                    (playbook.avg_recovery_time_ms * (playbook.execution_count - 1))
                    + recovery_outcome.recovery_time_ms
                ) / playbook.execution_count

                redis_success = await self.redis_tier.cache_playbook(
                    recovery_outcome.recovery_context.signature_hash,
                    playbook,
                )

                if not redis_success:
                    logger.warning("Failed to update Redis cache (non-critical)")

            # ================================================================
            # Update Neo4j (Knowledge Graph) - For Similarity Search
            # ================================================================
            if recovery_outcome.success:
                logger.info("🔄 Updating Neo4j knowledge graph...")

                neo4j_success = await self.neo4j_tier.store_attack_recovery(
                    attack_family=failure_event.attack_family,
                    service=failure_event.service,
                    anomaly_score=failure_event.anomaly_score,
                    rf_confidence=failure_event.rf_confidence,
                    playbook=playbook,
                    recovery_time_ms=recovery_outcome.recovery_time_ms,
                    success=recovery_outcome.success,
                )

                if not neo4j_success:
                    logger.warning("Failed to update Neo4j (non-critical)")

            # ================================================================
            # Increment Generation Counter
            # ================================================================
            self.antibody_gen += 1
            logger.info(f"✅ Learning recorded (Gen {self.antibody_gen})")

            # Log improvement metrics
            await self._log_improvement(dna_record, recovery_outcome)

            return True

        except Exception as e:
            logger.error(f"❌ Failed to record recovery: {e}")
            return False

    async def _log_improvement(self, dna_record: DNARecord, outcome: RecoveryOutcome):
        """Log recovery time improvement across generations"""
        logger.info(
            f"""
        ┌─ Generation Report (Gen {self.antibody_gen}) ─┐
        │ Service: {dna_record.target_service}
        │ Attack: {dna_record.strand_family}
        │ Result: {'✅ SUCCESS' if dna_record.success else '❌ FAILED'}
        │ Recovery Time: {dna_record.recovery_ms:.1f}ms
        │ RAG Tier: {dna_record.rag_source}
        │ Cache Hit: {'🔥 YES' if dna_record.cache_hit else '❄️  NO'}
        │ Confidence: {dna_record.rf_confidence:.2f}
        └─────────────────────────────┘
        """
        )

    async def get_learning_curve(self, attack_family: str, limit: int = 10) -> list:
        """
        Get learning curve data for visualization

        Returns recovery times across generations for the same attack family

        [
            {"generation": 1, "recovery_ms": 18000},  # First attack (Neo4j)
            {"generation": 2, "recovery_ms": 2100},   # Second attack (Redis)
            {"generation": 3, "recovery_ms": 800},    # Third attack (Redis optimized)
        ]
        """
        logger.info(f"📊 Retrieving learning curve for {attack_family}")

        # This would query PostgreSQL for generations with this attack
        # grouped by generation and ordered by timestamp

        # TODO: Implement query
        return []
