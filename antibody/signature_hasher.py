"""
Failure Signature Hashing for Cache & Learning
"""

import hashlib
import json
from typing import Dict
from .models import FailureEvent


class SignatureHasher:
    """Create deterministic hashes of failure signatures"""

    @staticmethod
    def create_signature_hash(failure_event: FailureEvent) -> str:
        """
        Create SHA256 hash of failure signature for cache key

        Hash is deterministic - same attack will always produce same hash
        This enables cache hit/miss for identical failure patterns

        Args:
            failure_event: Failure event from ML Pipeline

        Returns:
            SHA256 hash hex string (64 characters)

        Example:
            hash1 = create_signature_hash(pod_crash_event_1)
            hash2 = create_signature_hash(pod_crash_event_2)
            if hash1 == hash2:
                print("Same attack pattern - use cached playbook")
        """
        # Create signature dict with key fields (order matters for hashing)
        signature_dict = {
            "attack_family": failure_event.attack_family,
            "service": failure_event.service,
            "rf_confidence_bucket": SignatureHasher._bucket_confidence(
                failure_event.rf_confidence
            ),
            "anomaly_score_bucket": SignatureHasher._bucket_anomaly(
                failure_event.anomaly_score
            ),
        }

        # Create deterministic JSON (sorted keys, no spaces)
        signature_json = json.dumps(signature_dict, sort_keys=True, separators=(",", ":"))

        # Compute SHA256 hash
        hash_obj = hashlib.sha256(signature_json.encode())
        return hash_obj.hexdigest()

    @staticmethod
    def _bucket_confidence(confidence: float) -> str:
        """Bucket confidence score to handle floating point precision"""
        # Round to 2 decimal places (e.g., 0.91, 0.88, 0.82)
        return f"{confidence:.2f}"

    @staticmethod
    def _bucket_anomaly(anomaly_score: float) -> str:
        """Bucket anomaly score to handle floating point precision"""
        return f"{anomaly_score:.2f}"

    @staticmethod
    def create_extended_signature(failure_event: FailureEvent) -> Dict:
        """
        Create extended signature with full details for Neo4j/PostgreSQL

        Used for similarity search and learning
        """
        return {
            "service": failure_event.service,
            "attack_family": failure_event.attack_family,
            "rf_confidence": failure_event.rf_confidence,
            "anomaly_score": failure_event.anomaly_score,
            "detection_path": failure_event.detection_path,
            "timestamp": failure_event.timestamp.isoformat(),
        }
