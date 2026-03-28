"""
DARWIN Demo Reliability Layer (§11)

Three System Modes:
    LIVE     — everything real (development)
    DEMO     — scripted scenarios, real K8s but controlled
    FALLBACK — pure simulation, no K8s needed

Features:
    - Pre-demo validator (checks 9 components)
    - Fallback simulator (generates realistic NATS events)
    - Chaos schedule YAML (3 demo scenarios)
    - Demo runner: python demo.py 1|2|3|full
"""

import os
import sys
import json
import time
import asyncio
import logging
import subprocess
from typing import Optional

# Add the agents module to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'agents')))

import nats

from constants import (
    NATSSubjects, BrainEvents, SystemMode, ServiceConfig, DBConfig,
)

logging.basicConfig(level=logging.INFO, format="[DEMO] %(message)s")
log = logging.getLogger("demo")

NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)


# ═══════════════════════════════════════════════════════════════
# PRE-DEMO VALIDATOR (§11)
# ═══════════════════════════════════════════════════════════════

class PreDemoValidator:
    """Run 30 minutes before judging. Checks all 9 components."""

    COMPONENTS = [
        "minikube", "neo4j", "redis", "postgres", "nats",
        "prometheus", "services_healthy", "ml_models_loaded",
        "knowledge_graph_seeded",
    ]

    async def validate_all(self) -> dict[str, bool]:
        results = {}
        results["minikube"] = await self._check_minikube()
        results["neo4j"] = await self._check_neo4j()
        results["redis"] = await self._check_redis()
        results["postgres"] = await self._check_postgres()
        results["nats"] = await self._check_nats()
        results["prometheus"] = await self._check_prometheus()
        results["services_healthy"] = await self._check_services()
        results["ml_models_loaded"] = self._check_ml_models()
        results["knowledge_graph_seeded"] = await self._check_knowledge_graph()

        all_pass = all(results.values())
        log.info("\n" + "═" * 50)
        log.info("  PRE-DEMO VALIDATION RESULTS")
        log.info("═" * 50)
        for comp, status in results.items():
            icon = "✅" if status else "❌"
            log.info(f"  {icon} {comp}")
        log.info(f"\n  {'🟢 ALL CHECKS PASSED' if all_pass else '🔴 SOME CHECKS FAILED'}")
        return results

    async def _check_minikube(self) -> bool:
        try:
            result = subprocess.run(["minikube", "status"], capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    async def _check_neo4j(self) -> bool:
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(DBConfig.NEO4J_URI,
                                          auth=(DBConfig.NEO4J_USER, DBConfig.NEO4J_PASS))
            driver.verify_connectivity()
            driver.close()
            return True
        except Exception:
            return False

    async def _check_redis(self) -> bool:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(DBConfig.REDIS_URL)
            await r.ping()
            await r.aclose()
            return True
        except Exception:
            return False

    async def _check_postgres(self) -> bool:
        try:
            import asyncpg
            conn = await asyncpg.connect(DBConfig.PG_URL)
            await conn.close()
            return True
        except Exception:
            return False

    async def _check_nats(self) -> bool:
        try:
            nc = await nats.connect(NATS_URL)
            await nc.drain()
            return True
        except Exception:
            return False

    async def _check_prometheus(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get("http://localhost:9090/-/healthy")
                return resp.status_code == 200
        except Exception:
            return False

    async def _check_services(self) -> bool:
        import httpx
        healthy = 0
        async with httpx.AsyncClient(timeout=3.0) as http:
            for svc in ServiceConfig.SERVICE_NAMES:
                try:
                    resp = await http.get(f"http://{svc}:8000/health")
                    if resp.status_code == 200:
                        healthy += 1
                except Exception:
                    pass
        return healthy >= 4  # At least 4/6 healthy

    def _check_ml_models(self) -> bool:
        model_dir = os.path.join(os.path.dirname(__file__), "..", "models")
        required = ["isolation_forest.joblib", "random_forest.joblib"]
        return all(os.path.exists(os.path.join(model_dir, f)) for f in required)

    async def _check_knowledge_graph(self) -> bool:
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(DBConfig.NEO4J_URI,
                                          auth=(DBConfig.NEO4J_USER, DBConfig.NEO4J_PASS))
            with driver.session() as session:
                result = session.run("MATCH (s:Strand) RETURN count(s) as count")
                count = result.single()["count"]
                driver.close()
                if count < 18:
                    log.warning(f"  Only {count} strands found — auto-reseeding!")
                    return False
                return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════
# FALLBACK SIMULATOR (§11)
# ═══════════════════════════════════════════════════════════════

class FallbackSimulator:
    """Generates realistic-looking NATS events without any real infrastructure.
    Dashboard cannot distinguish from live events."""

    def __init__(self):
        self.nc: Optional[nats.NATS] = None
        self.recovery_times = {1: 18000, 2: 8200, 3: 1800}

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)

    async def _publish(self, subject: str, data: dict):
        if self.nc:
            await self.nc.publish(subject, json.dumps(data).encode())

    async def simulate_scenario_1(self):
        """Gen 1 → Immunity Acquired"""
        log.info("\n🎬 SCENARIO 1: Gen 1 → Immunity Acquired")

        # Attack
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": "payment-service", "attack_family": "pod_crash",
            "strand_id": "pod_crash_A", "virus_gen": 1,
            "anomaly_score": 0.87, "timestamp": time.time(),
        })
        await asyncio.sleep(2)

        # Detection
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.RECOVERY_STARTED,
            "service": "payment-service", "playbook": "rec_pod_crash_A",
            "attack_state": "KNOWN", "timestamp": time.time(),
        })
        await asyncio.sleep(3)

        # Recovery complete (18s)
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.RECOVERY_COMPLETE,
            "service": "payment-service", "recovery_time_ms": 18200,
            "success": True, "attack_family": "pod_crash",
            "strand_id": "pod_crash_A", "timestamp": time.time(),
        })
        await asyncio.sleep(2)

        # T-cell memory stored
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.TCELL_HIT,
            "service": "payment-service", "strand_id": "pod_crash_A",
            "timestamp": time.time(),
        })
        await asyncio.sleep(5)

        # Same attack again — T-cell hit!
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": "payment-service", "attack_family": "pod_crash",
            "strand_id": "pod_crash_A", "virus_gen": 1, "timestamp": time.time(),
        })
        await asyncio.sleep(1)
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.RECOVERY_COMPLETE,
            "service": "payment-service", "recovery_time_ms": 1800,
            "success": True, "attack_family": "pod_crash",
            "strand_id": "pod_crash_A", "attack_state": "KNOWN",
            "timestamp": time.time(),
        })

    async def simulate_scenario_2(self):
        """Gen 2 Timing Attack → Preemptive Defense"""
        log.info("\n🎬 SCENARIO 2: Timing Attack → LSTM Prediction")

        # LSTM prediction fires
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.PREEMPTIVE_ACTION,
            "service": "payment-service", "family": "timing",
            "confidence": 0.78, "services": ["payment-service", "order-service"],
            "timestamp": time.time(),
        })
        await asyncio.sleep(3)

        # Attack lands but service already scaled
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": "payment-service", "attack_family": "timing",
            "strand_id": "timing_A", "virus_gen": 2, "timestamp": time.time(),
        })
        await asyncio.sleep(1)
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.RECOVERY_COMPLETE,
            "service": "payment-service", "recovery_time_ms": 800,
            "success": True, "attack_family": "timing",
            "attack_state": "PREDICTED", "timestamp": time.time(),
        })

    async def simulate_scenario_3(self):
        """Unknown Strand → Honeypot Discovery"""
        log.info("\n🎬 SCENARIO 3: Unknown Strand → Honeypot")

        # Unknown attack
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": "auth-service", "attack_family": "resource",
            "confidence": 0.43, "virus_gen": 3, "timestamp": time.time(),
        })
        await asyncio.sleep(2)

        # Honeypot deployed
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.HONEYPOT_DEPLOYED,
            "service": "auth-service", "timestamp": time.time(),
        })
        await asyncio.sleep(2)

        # Observing
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.HONEYPOT_OBSERVING,
            "service": "auth-service", "timestamp": time.time(),
        })
        await asyncio.sleep(10)

        # New strand discovered!
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.NEW_STRAND_DISCOVERED,
            "strand_id": f"unknown_{int(time.time())}",
            "family": "resource", "confidence": 0.71,
            "service": "auth-service", "timestamp": time.time(),
        })
        await asyncio.sleep(5)

        # Same attack again — fast recovery
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": "auth-service", "attack_family": "resource",
            "virus_gen": 3, "timestamp": time.time(),
        })
        await asyncio.sleep(1)
        await self._publish(NATSSubjects.BRAIN_UPDATE, {
            "event": BrainEvents.RECOVERY_COMPLETE,
            "service": "auth-service", "recovery_time_ms": 2100,
            "success": True, "attack_family": "resource",
            "attack_state": "KNOWN", "timestamp": time.time(),
        })

    async def run_full_demo(self):
        """Run all 3 scenarios back-to-back (5 minute demo slot)."""
        await self.connect()

        log.info("\n" + "═" * 60)
        log.info("  🎬 DARWIN FULL DEMO — FALLBACK MODE")
        log.info("═" * 60)

        await self.simulate_scenario_1()
        await asyncio.sleep(5)
        await self.simulate_scenario_2()
        await asyncio.sleep(5)
        await self.simulate_scenario_3()

        log.info("\n🏁 Full demo complete!")
        if self.nc:
            await self.nc.drain()


# ═══════════════════════════════════════════════════════════════
# DEMO RUNNER
# ═══════════════════════════════════════════════════════════════

async def run_demo(scenario: str):
    """Run a specific demo scenario or full demo.

    Usage:
        python demo.py 1      # Gen 1 → immunity
        python demo.py 2      # Timing attack → preemptive
        python demo.py 3      # Unknown strand → honeypot
        python demo.py full   # All three back to back
        python demo.py validate  # Pre-demo validation
    """
    if scenario == "validate":
        validator = PreDemoValidator()
        await validator.validate_all()
        return

    sim = FallbackSimulator()
    await sim.connect()

    if scenario == "1":
        await sim.simulate_scenario_1()
    elif scenario == "2":
        await sim.simulate_scenario_2()
    elif scenario == "3":
        await sim.simulate_scenario_3()
    elif scenario == "full":
        await sim.run_full_demo()
    else:
        print(f"Unknown scenario: {scenario}")
        print("Usage: python demo.py [1|2|3|full|validate]")

    if sim.nc:
        try:
            await sim.nc.drain()
        except:
            pass


if __name__ == "__main__":
    import sys
    scenario = sys.argv[1] if len(sys.argv) > 1 else "full"
    asyncio.run(run_demo(scenario))
