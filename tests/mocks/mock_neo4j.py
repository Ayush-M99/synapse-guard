"""
Mock Neo4j Knowledge Graph for testing
In-memory graph without real Neo4j
"""

from typing import Dict, Any, List, Optional
from core.interfaces import IKnowledgeGraph
import uuid
import json


class MockKnowledgeGraph(IKnowledgeGraph):
    """Mock implementation of Neo4j knowledge graph for testing"""

    def __init__(self):
        self.failures = {}  # signature_hash -> failure_node
        self.recoveries = {}  # recovery_id -> recovery_node
        self.relationships = []  # failure -> recovery edges
        self.connected = False

    async def connect(self) -> None:
        """Connect to Neo4j (mock)"""
        self.connected = True
        print("[MockKnowledgeGraph] Connected")

    async def disconnect(self) -> None:
        """Disconnect from Neo4j (mock)"""
        self.connected = False
        print("[MockKnowledgeGraph] Disconnected")

    async def store_failure_recovery(
        self, failure_signature: Dict[str, Any], recovery: Dict[str, Any]
    ) -> str:
        """Store failure->recovery relationship"""
        if not self.connected:
            raise Exception("Not connected to knowledge graph")

        # Create failure node
        failure_hash = str(hash(json.dumps(failure_signature, sort_keys=True, default=str)))
        self.failures[failure_hash] = {
            "failure_id": failure_hash,
            "signature": failure_signature,
            "timestamp": str(__import__("datetime").datetime.utcnow()),
        }

        # Create recovery node
        recovery_id = str(uuid.uuid4())
        self.recoveries[recovery_id] = {
            "recovery_id": recovery_id,
            "actions": recovery.get("actions", []),
            "success_rate": recovery.get("success_rate", 0),
            "recovery_time": recovery.get("avg_recovery_time_seconds", 0),
            "timestamp": str(__import__("datetime").datetime.utcnow()),
        }

        # Create relationship
        self.relationships.append(
            {
                "failure_id": failure_hash,
                "recovery_id": recovery_id,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )

        return recovery_id

    async def retrieve_similar_failures(
        self, failure_signature: Dict[str, Any], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Find similar past failures using similarity metrics"""
        if not self.connected:
            raise Exception("Not connected to knowledge graph")

        results = []

        # Simple similarity: find failures with same service
        target_service = failure_signature.get("service")
        target_score = failure_signature.get("anomaly_score", 0)

        for failure_hash, failure_node in self.failures.items():
            sig = failure_node["signature"]

            # Check if same service
            if sig.get("service") != target_service:
                continue

            # Calculate simple distance
            distance = abs(sig.get("anomaly_score", 0) - target_score)

            # Find recovery for this failure
            related_recovery = None
            for rel in self.relationships:
                if rel["failure_id"] == failure_hash:
                    recovery_id = rel["recovery_id"]
                    if recovery_id in self.recoveries:
                        related_recovery = self.recoveries[recovery_id]
                    break

            if related_recovery:
                results.append(
                    {
                        "failure_id": failure_hash,
                        "signature": sig,
                        "recovery": related_recovery,
                        "distance": distance,
                    }
                )

        # Sort by distance (similarity) and return top N
        results.sort(key=lambda x: x["distance"])
        return results[:limit]

    async def get_failure_recovery_count(self) -> int:
        """Get total failure->recovery relationships"""
        return len(self.relationships)

    def get_graph_stats(self) -> Dict[str, Any]:
        """Get graph statistics for testing"""
        return {
            "total_failures": len(self.failures),
            "total_recoveries": len(self.recoveries),
            "total_relationships": len(self.relationships),
        }

    def reset(self):
        """Reset mock state"""
        self.failures = {}
        self.recoveries = {}
        self.relationships = []
        self.connected = False
