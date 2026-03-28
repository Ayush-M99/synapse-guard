"""
DARWIN Control Plane — Redis Client
Real connection to Redis at localhost:6379
(port-forwarded from minikube: kubectl port-forward svc/redis 6379:6379 -n darwin)

Stores:
  - Anomaly events      →  Key: anomaly:{service}:{timestamp}
  - Recovery actions    →  Key: recovery:{service}:{timestamp}
  - T-cell immunity     →  Key: immunity:{strand_id}
  - Service health      →  Key: health:{service}   (latest score)
"""

import json
import logging
import os
import time
from typing import Optional

import redis

logger = logging.getLogger(__name__)

REDIS_URL    = os.getenv("REDIS_URL",  "redis://localhost:6379")
REDIS_PREFIX = os.getenv("REDIS_PREFIX", "darwin")
ANOMALY_TTL  = int(os.getenv("ANOMALY_TTL_SECONDS", "3600"))   # 1 hour
IMMUNITY_TTL = int(os.getenv("IMMUNITY_TTL_SECONDS", "86400"))  # 24 hours


def _get_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def ping() -> bool:
    """Check Redis connectivity."""
    try:
        r = _get_client()
        return r.ping()
    except Exception:
        return False


# ─── Anomaly Logging ──────────────────────────────────────────────────────────

def log_anomaly(
    service: str,
    anomaly_score: float,
    rf_label: str,
    rf_confidence: float,
    attack_state: str,
    strand_id: Optional[str] = None,
) -> str:
    """Store anomaly event in Redis. Returns key."""
    ts = int(time.time() * 1000)
    key = f"{REDIS_PREFIX}:anomaly:{service}:{ts}"
    data = {
        "service":       service,
        "anomaly_score": anomaly_score,
        "rf_label":      rf_label,
        "rf_confidence": rf_confidence,
        "attack_state":  attack_state,
        "strand_id":     strand_id or "",
        "timestamp":     ts,
    }
    try:
        r = _get_client()
        r.setex(key, ANOMALY_TTL, json.dumps(data))
        # Also push to list for quick recent-events lookup
        r.lpush(f"{REDIS_PREFIX}:anomaly:recent", json.dumps(data))
        r.ltrim(f"{REDIS_PREFIX}:anomaly:recent", 0, 99)  # keep last 100
        logger.debug(f"Anomaly logged: {key}")
    except Exception as e:
        logger.error(f"Redis log_anomaly error: {e}")
    return key


def get_recent_anomalies(limit: int = 20) -> list[dict]:
    """Return the most recent anomaly events."""
    try:
        r = _get_client()
        raw = r.lrange(f"{REDIS_PREFIX}:anomaly:recent", 0, limit - 1)
        return [json.loads(x) for x in raw]
    except Exception as e:
        logger.error(f"get_recent_anomalies: {e}")
        return []


# ─── Recovery Action Logging ──────────────────────────────────────────────────

def log_recovery(
    service: str,
    strand_id: str,
    playbook_id: str,
    actions: list[str],
    recovery_time_ms: float,
    success: bool,
    virus_gen: int = 1,
    antibody_gen: int = 1,
) -> str:
    """Store recovery action in Redis. Returns key."""
    ts = int(time.time() * 1000)
    key = f"{REDIS_PREFIX}:recovery:{service}:{ts}"
    data = {
        "service":          service,
        "strand_id":        strand_id,
        "playbook_id":      playbook_id,
        "actions":          actions,
        "recovery_time_ms": recovery_time_ms,
        "success":          success,
        "virus_gen":        virus_gen,
        "antibody_gen":     antibody_gen,
        "timestamp":        ts,
    }
    try:
        r = _get_client()
        r.setex(key, ANOMALY_TTL, json.dumps(data))
        r.lpush(f"{REDIS_PREFIX}:recovery:recent", json.dumps(data))
        r.ltrim(f"{REDIS_PREFIX}:recovery:recent", 0, 49)  # keep last 50
    except Exception as e:
        logger.error(f"Redis log_recovery: {e}")
    return key


def get_recent_recoveries(limit: int = 10) -> list[dict]:
    """Return the most recent recovery events."""
    try:
        r = _get_client()
        raw = r.lrange(f"{REDIS_PREFIX}:recovery:recent", 0, limit - 1)
        return [json.loads(x) for x in raw]
    except Exception as e:
        logger.error(f"get_recent_recoveries: {e}")
        return []


# ─── T-Cell Immunity Memory ───────────────────────────────────────────────────

def check_immunity(strand_id: str) -> Optional[dict]:
    """
    T-Cell Memory hit — O(1) lookup for known attack signatures.
    Returns playbook dict or None (cache miss → Neo4j graph traversal).
    """
    try:
        r = _get_client()
        cached = r.get(f"{REDIS_PREFIX}:immunity:{strand_id}")
        if cached:
            logger.info(f"⚡ T-CELL HIT: {strand_id}")
            return json.loads(cached)
        logger.info(f"T-cell miss: {strand_id} → falling back to knowledge graph")
        return None
    except Exception as e:
        logger.error(f"check_immunity: {e}")
        return None


def update_immunity(strand_id: str, playbook: dict, ttl: int = IMMUNITY_TTL) -> bool:
    """Store a playbook in T-cell memory (Redis). Expires after ttl seconds."""
    try:
        r = _get_client()
        r.setex(
            f"{REDIS_PREFIX}:immunity:{strand_id}",
            ttl,
            json.dumps(playbook),
        )
        logger.info(f"🧬 T-cell updated: {strand_id}")
        return True
    except Exception as e:
        logger.error(f"update_immunity: {e}")
        return False


def get_all_immunity_keys() -> list[str]:
    """List all strand IDs currently in T-cell memory."""
    try:
        r = _get_client()
        keys = r.keys(f"{REDIS_PREFIX}:immunity:*")
        return [k.replace(f"{REDIS_PREFIX}:immunity:", "") for k in keys]
    except Exception:
        return []


# ─── Service Health Score ─────────────────────────────────────────────────────

def update_health_score(service: str, score: float, state: str):
    """Store latest health score for a service (dashboard reads this)."""
    try:
        r = _get_client()
        r.set(
            f"{REDIS_PREFIX}:health:{service}",
            json.dumps({"score": score, "state": state, "ts": time.time()}),
            ex=60,  # expires after 60s (stale = unknown)
        )
    except Exception:
        pass


def get_health_scores() -> dict[str, dict]:
    """Return health scores for all services."""
    services = [
        "auth-service", "api-gateway", "order-service",
        "payment-service", "inventory-service", "notification-service",
    ]
    try:
        r = _get_client()
        result = {}
        for svc in services:
            raw = r.get(f"{REDIS_PREFIX}:health:{svc}")
            result[svc] = json.loads(raw) if raw else {"score": 1.0, "state": "unknown"}
        return result
    except Exception:
        return {}


# ─── General KV helpers ───────────────────────────────────────────────────────

def set_key(key: str, value, ttl: int = 3600) -> bool:
    try:
        r = _get_client()
        r.setex(f"{REDIS_PREFIX}:{key}", ttl, json.dumps(value))
        return True
    except Exception:
        return False


def get_key(key: str) -> Optional[dict]:
    try:
        r = _get_client()
        raw = r.get(f"{REDIS_PREFIX}:{key}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def info() -> dict:
    """Return Redis server info snippet."""
    try:
        r = _get_client()
        i = r.info("server")
        return {
            "version":     i.get("redis_version"),
            "uptime_days": i.get("uptime_in_days"),
            "used_memory": i.get("used_memory_human"),
            "connected":   True,
        }
    except Exception:
        return {"connected": False}
