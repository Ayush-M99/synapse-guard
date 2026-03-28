"""
DARWIN Recovery Engine
Executes autonomous recovery actions against the patient Kubernetes workload.

Recovery tiers:
  Tier 1 (KNOWN / T-cell hit)   → immediate playbook from Redis, ~2s
  Tier 2 (PROBABLE)             → Neo4j graph query, compose playbook, ~8s
  Tier 3 (UNKNOWN)              → honeypot observation + Gemini LLM synthesis, ~20s

All outcomes written to Redis + PostgreSQL DNA store.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from . import k8s_client   as k8s
from . import redis_client as redis_store
from . import prometheus_client as prom

logger = logging.getLogger(__name__)

PATIENT_NS      = os.getenv("PATIENT_NAMESPACE",    "patient")
NEO4J_URI       = os.getenv("NEO4J_URI",            "bolt://localhost:7687")
NEO4J_USER      = os.getenv("NEO4J_USER",           "neo4j")
NEO4J_PASS      = os.getenv("NEO4J_PASS",           "chaospassword")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY",       "")

# ─── Playbook actions → K8s operations ───────────────────────────────────────

ACTION_HANDLERS = {}


def _action(name):
    def _dec(fn):
        ACTION_HANDLERS[name] = fn
        return fn
    return _dec


@_action("restart_pod")
def _restart_pod(service: str, params: dict) -> dict:
    result = k8s.restart_deployment(service, PATIENT_NS)
    return result


@_action("scale_hpa")
def _scale_hpa(service: str, params: dict) -> dict:
    replicas = params.get("replicas", 3)
    result   = k8s.scale_deployment(service, replicas, PATIENT_NS)
    return result


@_action("scale_down_restore")
def _scale_restore(service: str, params: dict) -> dict:
    """Restore replicas after a scale_down fault."""
    saved = redis_store.get_key(f"pre_fault_replicas:{service}")
    replicas = (saved or {}).get("replicas", 2)
    return k8s.scale_deployment(service, replicas, PATIENT_NS)


@_action("flush_cache")
def _flush_cache(service: str, params: dict) -> dict:
    """Flush service-specific Redis keys (for inventory cache corruption)."""
    try:
        import redis as rlib
        r = rlib.from_url("redis://localhost:6379", decode_responses=True)
        keys = r.keys(f"{service}:*")
        if keys:
            r.delete(*keys)
        return {"success": True, "flushed_keys": len(keys)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@_action("reroute_traffic")
def _reroute_traffic(service: str, params: dict) -> dict:
    """Remove Istio network fault VirtualService (restores normal routing)."""
    import subprocess
    proc = subprocess.run(
        ["kubectl", "delete", "virtualservice", f"darwin-chaos-{service}",
         "-n", PATIENT_NS, "--ignore-not-found"],
        capture_output=True, text=True,
    )
    return {"success": proc.returncode == 0, "output": proc.stdout.strip()}


@_action("alert_brain")
def _alert_brain(service: str, params: dict) -> dict:
    """Log event to Redis for dashboard pickup."""
    redis_store.set_key(f"brain_alert:{service}", {
        "service": service, "at": time.time(), "action": "alert_brain"
    })
    return {"success": True}


@_action("increase_resources")
def _increase_resources(service: str, params: dict) -> dict:
    cpu = params.get("cpu", "500m")
    mem = params.get("memory", "512Mi")
    return k8s.patch_resource_limits(service, service, cpu, mem, PATIENT_NS)


# ─── Recovery Engine ──────────────────────────────────────────────────────────

class RecoveryEngine:
    """
    Autonomous recovery orchestrator.
    Uses Redis (T-cell) → Neo4j (graph) → Gemini LLM (synthesis) cascade.
    """

    def __init__(self):
        self._neo4j_driver = None
        self._neo4j_ok     = False
        self._gemini_ok    = bool(GEMINI_API_KEY)
        self._init_neo4j()

    def _init_neo4j(self):
        try:
            from neo4j import GraphDatabase
            self._neo4j_driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS)
            )
            self._neo4j_driver.verify_connectivity()
            self._neo4j_ok = True
            logger.info("✅ Neo4j connected")
        except Exception as e:
            logger.warning(f"⚠️  Neo4j unavailable: {e} — using rule-based fallback")

    # ─── Public API ──────────────────────────────────────────────────────────

    def recover(
        self,
        service:        str,
        strand_id:      str,
        attack_family:  str,
        rf_confidence:  float,
        anomaly_score:  float,
        metrics:        dict = None,
    ) -> dict:
        """
        Main recovery entry point.
        Determines recovery path (Tier 1/2/3) and executes.
        """
        recovery_id = str(uuid.uuid4())[:8]
        start_ms    = time.time() * 1000
        metrics     = metrics or {}

        logger.info(
            f"💉 Recovery started: {service} | strand={strand_id} "
            f"family={attack_family} confidence={rf_confidence:.2f}"
        )

        # ── Tier 1: T-cell memory (O(1) Redis lookup) ─────────────────────
        cached = redis_store.check_immunity(strand_id)
        if cached:
            playbook = cached
            tier     = 1
            logger.info(f"⚡ T-CELL HIT: {strand_id} → instant recovery")
        elif rf_confidence >= 0.60 and self._neo4j_ok:
            # ── Tier 2: Neo4j knowledge graph ─────────────────────────────
            playbook = self._query_neo4j_playbook(attack_family, service)
            tier     = 2
        else:
            # ── Tier 3: Rule-based / Gemini LLM synthesis ─────────────────
            playbook = self._synthesize_playbook(strand_id, attack_family, metrics)
            tier     = 3

        # Execute playbook
        results = self._execute_playbook(service, playbook)

        # Validate recovery
        recovered = self._validate_recovery(service)

        elapsed_ms = time.time() * 1000 - start_ms

        # Write to Redis
        redis_store.log_recovery(
            service=service,
            strand_id=strand_id,
            playbook_id=playbook.get("id", f"auto_{recovery_id}"),
            actions=playbook.get("actions", []),
            recovery_time_ms=elapsed_ms,
            success=recovered,
        )

        # Update T-cell memory if Tier 2/3 succeeded
        if recovered and tier > 1:
            redis_store.update_immunity(strand_id, playbook)
            # Update Neo4j recovery time (best-effort)
            self._update_neo4j_recovery_time(strand_id, elapsed_ms)

        # Update health score in Redis
        redis_store.update_health_score(
            service, 1.0 if recovered else 0.2,
            "healthy" if recovered else "degraded"
        )

        outcome = {
            "recovery_id":      recovery_id,
            "service":          service,
            "strand_id":        strand_id,
            "tier":             tier,
            "tier_label":       {1: "T-CELL", 2: "NEO4J", 3: "LLM/RULE"}[tier],
            "playbook":         playbook,
            "action_results":   results,
            "recovery_time_ms": round(elapsed_ms, 1),
            "success":          recovered,
            "t_cell_updated":   recovered and tier > 1,
        }
        logger.info(
            f"{'✅' if recovered else '❌'} Recovery {recovery_id}: "
            f"{elapsed_ms:.0f}ms (Tier {tier})"
        )
        return outcome

    # ─── Tier 2: Neo4j playbook lookup ───────────────────────────────────────

    def _query_neo4j_playbook(self, attack_family: str, service: str) -> dict:
        """Fast graph lookup: Signature → Recovery node."""
        try:
            with self._neo4j_driver.session() as session:
                result = session.run("""
                    MATCH (sig:Signature {rf_label: $label})
                        -[:TRIGGERS]->(rec:Recovery)
                    RETURN rec.id AS id,
                           rec.actions AS actions,
                           rec.priority_order AS priority_order,
                           rec.estimated_time_ms AS estimated_ms
                    ORDER BY rec.estimated_time_ms ASC
                    LIMIT 1
                """, label=attack_family)
                row = result.single()
                if row:
                    return {
                        "id":       row["id"],
                        "actions":  list(row["actions"] or ["restart_pod"]),
                        "priority": list(row["priority_order"] or [1]),
                        "source":   "neo4j",
                    }
        except Exception as e:
            logger.warning(f"Neo4j playbook query failed: {e}")

        # Fallback to rule-based
        return self._rule_based_playbook(attack_family)

    # ─── Tier 3: Gemini LLM synthesis ────────────────────────────────────────

    def _synthesize_playbook(
        self, strand_id: str, attack_family: str, metrics: dict
    ) -> dict:
        """Synthesize playbook using Gemini 1.5 Flash for unknown attacks."""
        if self._gemini_ok:
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"""
You are a Kubernetes self-healing autonomous decision engine for DARWIN platform.

Unknown attack strand "{strand_id}" (family guess: {attack_family}) captured.
Telemetry:
  CPU:        {metrics.get('cpu_usage_pct', 0):.1f}%
  Memory:     {metrics.get('memory_usage_pct', 0):.1f}%
  Error rate: {metrics.get('http_error_rate_5xx', 0):.3f}
  Latency P99:{metrics.get('request_latency_p99', 0):.3f}s
  Restarts:   {metrics.get('pod_restart_count_delta', 0):.0f}

Choose recovery actions from: restart_pod, scale_hpa, reroute_traffic, flush_cache, increase_resources, alert_brain

Return ONLY valid JSON: {{"actions": ["...", "..."], "reason": "...", "confidence": 0.8}}
"""
                resp   = model.generate_content(prompt)
                text   = resp.text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                return {
                    "id":       f"gemini_{strand_id}",
                    "actions":  parsed.get("actions", ["restart_pod"]),
                    "reason":   parsed.get("reason", ""),
                    "source":   "gemini_llm",
                    "confidence": parsed.get("confidence", 0.7),
                }
            except Exception as e:
                logger.warning(f"Gemini synthesis failed: {e}")

        return self._rule_based_playbook(attack_family, metrics)

    # ─── Rule-based fallback ──────────────────────────────────────────────────

    @staticmethod
    def _rule_based_playbook(attack_family: str, metrics: dict = None) -> dict:
        metrics = metrics or {}
        cpu  = metrics.get("cpu_usage_pct", 0)
        mem  = metrics.get("memory_usage_pct", 0)
        err  = metrics.get("http_error_rate_5xx", 0)

        if attack_family == "pod_crash" or metrics.get("pod_restart_count_delta", 0) > 0:
            actions = ["restart_pod", "scale_hpa", "alert_brain"]
        elif attack_family == "network" or err > 0.3:
            actions = ["reroute_traffic", "restart_pod", "alert_brain"]
        elif attack_family == "resource" or cpu > 80 or mem > 85:
            actions = ["scale_hpa", "increase_resources", "alert_brain"]
        elif attack_family in ("timing", "camouflage"):
            actions = ["scale_hpa", "restart_pod", "alert_brain"]
        else:
            actions = ["restart_pod", "alert_brain"]

        return {
            "id":      f"rule_{attack_family}",
            "actions": actions,
            "source":  "rule_based",
        }

    # ─── Playbook executor ────────────────────────────────────────────────────

    def _execute_playbook(self, service: str, playbook: dict) -> list[dict]:
        actions = playbook.get("actions", ["restart_pod"])
        results = []
        for action in actions:
            handler = ACTION_HANDLERS.get(action)
            if handler is None:
                results.append({"action": action, "success": False, "error": "unknown action"})
                continue
            try:
                result = handler(service, playbook.get("params", {}))
                results.append({"action": action, **result})
                logger.info(f"  ↳ {action}: {'OK' if result.get('success') else 'FAIL'}")
            except Exception as e:
                logger.error(f"  ↳ {action} error: {e}")
                results.append({"action": action, "success": False, "error": str(e)})
                # DO NOT stop — continue through all actions
        return results

    # ─── Recovery validation ──────────────────────────────────────────────────

    def _validate_recovery(self, service: str, timeout: int = 15) -> bool:
        """
        Wait up to `timeout` seconds for at least 1 ready pod for service.
        Polls via K8s API.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            pods = k8s.list_pods(PATIENT_NS)
            svc_pods = [
                p for p in pods
                if p["labels"].get("app") == service and p["ready"]
            ]
            if svc_pods:
                return True
            time.sleep(2)
        return False

    # ─── Neo4j learning write ─────────────────────────────────────────────────

    def _update_neo4j_recovery_time(self, strand_id: str, elapsed_ms: float):
        """Update avg_recovery_time_ms on the Strand node after a successful recovery."""
        if not self._neo4j_ok or not self._neo4j_driver:
            return
        try:
            with self._neo4j_driver.session() as session:
                session.run("""
                    MATCH (st:Strand {id: $strand_id})
                    SET st.avg_recovery_time_ms =
                        (coalesce(st.avg_recovery_time_ms, $new_ms) + $new_ms) / 2
                """, strand_id=strand_id, new_ms=elapsed_ms)
        except Exception as e:
            logger.debug(f"Neo4j update recovery time: {e}")


# ─── Module-level singleton ───────────────────────────────────────────────────
engine = RecoveryEngine()
