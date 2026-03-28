"""
Tier 3: PostgreSQL DNA Store Connector
Historical archive and learning (18s recovery + optional LLM)
"""

import logging
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from ..models import RecoveryPlaybook, RecoveryAction, RecoveryActionType, RAGTier, DNARecord

logger = logging.getLogger(__name__)


class PostgresDBTier:
    """PostgreSQL Tier 3 for DNA store (historical data)"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "darwin_dna",
        user: str = "darwin",
        password: str = "darwin123",
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=5,
            )
            self.connected = True
            logger.info(f"✅ Connected to PostgreSQL at {self.host}:{self.port}/{self.database}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from PostgreSQL"""
        if self.conn:
            self.conn.close()
            self.connected = False
            logger.info("Disconnected from PostgreSQL")

    async def retrieve_historical_recoveries(
        self, attack_family: str, limit: int = 10
    ) -> List[RecoveryPlaybook]:
        """
        Query DNA store for historical successful recoveries (Tier 3 fallback)

        Used when Redis misses AND Neo4j has no similar attacks

        Query:
            SELECT recovery_actions, success_rate, recovery_ms
            FROM generations
            WHERE strand_family = 'pod_crash'
              AND success = TRUE
              AND recovery_ts IS NOT NULL
            ORDER BY recovery_ms ASC
            LIMIT 10

        Args:
            attack_family: Type of attack to look up
            limit: Max records to return

        Returns:
            List of RecoveryPlaybook from historical data

        Example:
            playbooks = await postgres_tier.retrieve_historical_recoveries(
                attack_family="pod_crash",
                limit=10
            )
            if playbooks:
                print(f"Found {len(playbooks)} historical recoveries")
                playbook = playbooks[0]
                # Use based on historical success
        """
        if not self.connected:
            logger.warning("PostgreSQL not connected")
            return []

        try:
            query = """
            SELECT recovery_actions, recovery_ms,
                   COUNT(*) as execution_count,
                   SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
            FROM generations
            WHERE strand_family = %s
              AND recovery_ts IS NOT NULL
            GROUP BY recovery_actions, recovery_ms
            ORDER BY recovery_ms ASC
            LIMIT %s
            """

            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (attack_family, limit))
                records = cursor.fetchall()

                if not records:
                    logger.info(f"❄️  PostgreSQL: No historical recoveries for {attack_family}")
                    return []

                playbooks = []
                for idx, record in enumerate(records):
                    # Create playbook from historical data
                    playbook = RecoveryPlaybook(
                        playbook_id=f"dna-{attack_family}-{idx}",
                        actions=self._parse_actions(record["recovery_actions"]),
                        attack_family=attack_family,
                        success_rate=float(record["success_rate"]),
                        avg_recovery_time_ms=float(record["recovery_ms"]),
                        execution_count=int(record["execution_count"]),
                        rag_tier=RAGTier.POSTGRES,
                    )
                    playbooks.append(playbook)

                logger.info(
                    f"🔥 PostgreSQL HIT: Found {len(playbooks)} historical recoveries for {attack_family}"
                )
                return playbooks

        except Exception as e:
            logger.error(f"Failed to retrieve historical recoveries: {e}")
            return []

    async def record_recovery_generation(self, dna_record: DNARecord) -> bool:
        """
        Write recovery record to DNA store (learning loop)

        Stores complete attack-recovery cycle for analysis:
        - Attack timing (injection, detection, recovery)
        - Recovery success/failure
        - ML pipeline metadata
        - RAG tier used
        - Recovery time for learning curve

        Args:
            dna_record: DNARecord with complete generation data

        Returns:
            True if recorded successfully

        Example:
            dna = DNARecord(
                virus_gen=1,
                antibody_gen=1,
                strand_id="pod_crash_A",
                strand_family="pod_crash",
                target_service="payment-service",
                injection_ts=start_time,
                detection_ts=detection_time,
                recovery_ts=recovery_time,
                recovery_ms=18000,
                recovery_actions=[...],
                success=True,
                cache_hit=False,
                rag_source="neo4j",
                rf_label="pod_crash",
                rf_confidence=0.91,
                detection_path="isolation_forest",
            )
            await postgres_tier.record_recovery_generation(dna)
        """
        if not self.connected:
            logger.warning("PostgreSQL not connected")
            return False

        try:
            insert_query = """
            INSERT INTO generations (
                virus_gen, antibody_gen, strand_id, strand_family,
                target_service, injection_ts, detection_ts, recovery_ts,
                recovery_ms, recovery_actions, success, cache_hit,
                rag_source, rf_label, rf_confidence, detection_path
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """

            import json

            values = (
                dna_record.virus_gen,
                dna_record.antibody_gen,
                dna_record.strand_id,
                dna_record.strand_family,
                dna_record.target_service,
                dna_record.injection_ts,
                dna_record.detection_ts,
                dna_record.recovery_ts,
                dna_record.recovery_ms,
                json.dumps(dna_record.recovery_actions),
                dna_record.success,
                dna_record.cache_hit,
                dna_record.rag_source,
                dna_record.rf_label,
                dna_record.rf_confidence,
                dna_record.detection_path,
            )

            with self.conn.cursor() as cursor:
                cursor.execute(insert_query, values)
                self.conn.commit()

            logger.info(f"💾 Recorded DNA generation: {dna_record.strand_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to record recovery generation: {e}")
            self.conn.rollback()
            return False

    def _parse_actions(self, actions_json) -> List[RecoveryAction]:
        """Parse recovery actions from JSON"""
        import json

        try:
            if isinstance(actions_json, str):
                actions_list = json.loads(actions_json)
            else:
                actions_list = actions_json

            actions = []
            for action_data in actions_list:
                action = RecoveryAction(
                    action_type=RecoveryActionType(action_data["type"]),
                    target_service=action_data.get("target", "unknown"),
                    parameters=action_data.get("parameters", {}),
                )
                actions.append(action)
            return actions

        except Exception as e:
            logger.error(f"Failed to parse actions: {e}")
            return []

    async def health_check(self) -> bool:
        """Health check for PostgreSQL"""
        if not self.connected:
            return False

        try:
            with self.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False
