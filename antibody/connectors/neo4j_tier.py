"""
Tier 2: Neo4j Knowledge Graph Connector
Similarity search for analogous attacks (2s recovery)
"""

import logging
from typing import List, Optional

from neo4j import GraphDatabase, Session

from ..models import RecoveryPlaybook, RAGTier

logger = logging.getLogger(__name__)


class Neo4jGraphTier:
    """Neo4j Tier 2 for similarity-based recovery retrieval"""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "darwin123",
    ):
        self.uri = uri
        self.username = username
        self.password = password
        self.driver = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to Neo4j"""
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            self.connected = True
            logger.info(f"✅ Connected to Neo4j at {self.uri}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from Neo4j"""
        if self.driver:
            self.driver.close()
            self.connected = False
            logger.info("Disconnected from Neo4j")

    async def retrieve_similar_playbooks(
        self,
        attack_family: str,
        service: str,
        anomaly_score: float,
        rf_confidence: float,
        limit: int = 5,
    ) -> List[RecoveryPlaybook]:
        """
        Query Neo4j for similar past attacks and their recovery playbooks

        Uses similarity scoring on failure signatures to find analogous attacks

        Cypher Query:
            MATCH (attack:Attack {family: 'pod_crash'})
                  -[:RECOVERED_BY]->(playbook:Playbook)
            WHERE abs(attack.anomaly_score - 0.92) < 0.1
              AND playbook.success_rate > 0.80
            RETURN playbook, similarity_distance
            ORDER BY similarity_distance ASC, playbook.success_rate DESC
            LIMIT 5

        Args:
            attack_family: Attack type (e.g., "pod_crash")
            service: Target service name
            anomaly_score: Current anomaly score (0.0-1.0)
            rf_confidence: Current RF confidence (0.0-1.0)
            limit: Max playbooks to return (default 5)

        Returns:
            List of RecoveryPlaybook sorted by (similarity, success_rate)

        Example:
            playbooks = await neo4j_tier.retrieve_similar_playbooks(
                attack_family="pod_crash",
                service="payment-service",
                anomaly_score=0.92,
                rf_confidence=0.88,
                limit=5
            )
            if playbooks:
                best = playbooks[0]
                print(f"Found {len(playbooks)} similar attacks")
                print(f"Best playbook: success_rate={best.success_rate}")
        """
        if not self.connected:
            logger.warning("Neo4j not connected")
            return []

        try:
            cypher_query = """
            MATCH (attack:Attack {family: $family})
                  -[:RECOVERED_BY]->(playbook:Playbook)
            WHERE abs(attack.anomaly_score - $anomaly_score) < 0.15
              AND abs(attack.rf_confidence - $rf_confidence) < 0.15
              AND attack.service = $service
              AND playbook.success_rate > 0.75
            WITH playbook,
                 abs(attack.anomaly_score - $anomaly_score) +
                 abs(attack.rf_confidence - $rf_confidence) AS distance
            RETURN playbook
            ORDER BY distance ASC, playbook.success_rate DESC
            LIMIT $limit
            """

            params = {
                "family": attack_family,
                "service": service,
                "anomaly_score": anomaly_score,
                "rf_confidence": rf_confidence,
                "limit": limit,
            }

            with self.driver.session() as session:
                results = session.run(cypher_query, params)
                records = results.data()

                if not records:
                    logger.info(f"❄️  Neo4j: No similar attacks found for {attack_family}")
                    return []

                playbooks = []
                for record in records:
                    playbook_data = record["playbook"]
                    # Convert Neo4j node to RecoveryPlaybook
                    playbook = self._node_to_playbook(playbook_data)
                    playbook.rag_tier = RAGTier.NEO4J
                    playbooks.append(playbook)

                logger.info(f"🔥 Neo4j HIT: Found {len(playbooks)} similar playbooks")
                return playbooks

        except Exception as e:
            logger.error(f"Failed to retrieve similar playbooks: {e}")
            return []

    async def store_attack_recovery(
        self,
        attack_family: str,
        service: str,
        anomaly_score: float,
        rf_confidence: float,
        playbook: RecoveryPlaybook,
        recovery_time_ms: float,
        success: bool,
    ) -> bool:
        """
        Store new attack-recovery relationship in Neo4j (learning loop)

        Creates/updates nodes:
        - (attack:Attack) - This specific attack instance
        - (playbook:Playbook) - Recovery playbook used

        And relationships:
        - (attack)-[:RECOVERED_BY]->(playbook)
        - (playbook)-[:NEXT_GENERATION]->(improved_playbook)

        Args:
            attack_family: Type of attack
            service: Affected service
            anomaly_score: Anomaly score captured
            rf_confidence: RF classification confidence
            playbook: Recovery playbook used
            recovery_time_ms: How long recovery took
            success: Whether recovery succeeded

        Returns:
            True if stored successfully
        """
        if not self.connected:
            logger.warning("Neo4j not connected")
            return False

        try:
            cypher_query = """
            MERGE (attack:Attack {
                family: $family,
                service: $service,
                timestamp: datetime()
            })
            SET attack.anomaly_score = $anomaly_score,
                attack.rf_confidence = $rf_confidence,
                attack.success = $success

            MERGE (playbook:Playbook {id: $playbook_id})
            SET playbook.actions = $actions,
                playbook.success_rate = $success_rate,
                playbook.recovery_time = $recovery_time_ms,
                playbook.execution_count = coalesce(playbook.execution_count, 0) + 1

            MERGE (attack)-[:RECOVERED_BY {recovery_time_ms: $recovery_time_ms}]->(playbook)
            """

            params = {
                "family": attack_family,
                "service": service,
                "anomaly_score": anomaly_score,
                "rf_confidence": rf_confidence,
                "playbook_id": playbook.playbook_id,
                "actions": [action.to_dict() for action in playbook.actions],
                "success_rate": playbook.success_rate,
                "recovery_time_ms": recovery_time_ms,
                "success": success,
            }

            with self.driver.session() as session:
                session.run(cypher_query, params)
                logger.info(f"💾 Stored attack-recovery in Neo4j")
                return True

        except Exception as e:
            logger.error(f"Failed to store attack-recovery: {e}")
            return False

    def _node_to_playbook(self, node) -> RecoveryPlaybook:
        """Convert Neo4j node to RecoveryPlaybook"""
        # Neo4j returns nodes as dicts
        return RecoveryPlaybook(
            playbook_id=node.get("id", "unknown"),
            actions=node.get("actions", []),
            attack_family=node.get("family", "unknown"),
            success_rate=node.get("success_rate", 0.0),
            avg_recovery_time_ms=node.get("recovery_time", 0.0),
            execution_count=node.get("execution_count", 0),
            generation=node.get("generation", 1),
        )

    async def health_check(self) -> bool:
        """Health check for Neo4j"""
        if not self.connected:
            return False

        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False
