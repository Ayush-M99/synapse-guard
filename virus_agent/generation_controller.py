"""
DARWIN Virus Agent — Generation Controller (VirusBrain)
Reads PostgreSQL DNA store, decides when to mutate, schedules attacks.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import asyncpg
import nats
import yaml

from .attack_library import dispatch, cleanup_network, cleanup_stress_pods

logger = logging.getLogger(__name__)

PG_URL    = os.getenv("PG_URL",   "postgres://chaos:chaospassword@localhost:5432/chaos_dna")
NATS_URL  = os.getenv("NATS_URL", "nats://localhost:4222")
NAMESPACE = os.getenv("PATIENT_NAMESPACE", "patient")

MUTATION_TRIGGERS = {
    3000: "escalate_same_family",
    1000: "switch_family",
}

SERVICES = [
    "auth-service", "api-gateway", "order-service",
    "payment-service", "inventory-service", "notification-service",
]


class VirusBrain:
    """
    Reads PostgreSQL DNA log to measure antibody speed.
    When antibody recovers too fast → mutate to harder strain.
    Publishes every attack to NATS virus.inject and brain.update.
    """

    def __init__(self):
        self.current_gen  = 1
        self.pg_pool      = None
        self.nc           = None
        self.running      = False
        self._schedule    = self._load_schedule()

    def _load_schedule(self) -> dict:
        schedule_path = Path(__file__).parent / "chaos_schedule.yaml"
        if schedule_path.exists():
            with open(schedule_path) as f:
                return yaml.safe_load(f) or {}
        return {}

    # ──────────────────────────────────────────────────────────────────────────

    async def start(self):
        logger.info("🧬 Virus Brain initializing...")
        self.nc      = await nats.connect(NATS_URL)
        self.pg_pool = await asyncpg.create_pool(PG_URL)
        self.running = True
        logger.info("✅ Virus Brain connected (NATS + PostgreSQL)")

    async def stop(self):
        self.running = False
        if self.nc:      await self.nc.drain()
        if self.pg_pool: await self.pg_pool.close()

    # ─── Generation sequences ─────────────────────────────────────────────────

    def _gen1_sequence(self) -> list:
        return [
            {"strand": "pod_crash_A", "target": "payment-service"},
            {"strand": "network_A",   "target": "api-gateway"},
            {"strand": "resource_A",  "target": "auth-service"},
            {"strand": "pod_crash_B", "target": "order-service"},
        ]

    def _gen2_sequence(self) -> list:
        return [
            {"strand": "timing_B",   "target": "payment-service"},
            {"strand": "timing_C",   "target": "order-service"},
            {"strand": "network_B",  "target": "api-gateway"},
        ]

    def _gen3_sequence(self) -> list:
        return [
            {"strand": "camouflage_B", "target": "auth-service"},
            {"strand": "timing_B",     "target": "payment-service"},
            {"strand": "pod_crash_A",  "target": "notification-service"},
        ]

    def _get_sequence(self) -> list:
        return {1: self._gen1_sequence, 2: self._gen2_sequence, 3: self._gen3_sequence}.get(
            self.current_gen, self._gen3_sequence
        )()

    # ─── Main runner ──────────────────────────────────────────────────────────

    async def run_generation(self, gen: int = None):
        """Run one full generation of attacks."""
        if gen:
            self.current_gen = gen

        seq = self._get_sequence()
        logger.info(f"🦠 Starting Gen {self.current_gen} with {len(seq)} attacks")
        await self._publish_brain("mutation", "system", {
            "virus_gen": self.current_gen,
            "sequence":  [s["strand"] for s in seq],
        })

        for step in seq:
            if not self.running:
                break
            strand  = step["strand"]
            target  = step["target"]
            logger.info(f"  💉 Injecting {strand} → {target}")
            await dispatch(strand, target, nc=self.nc)
            await asyncio.sleep(30)   # wait for antibody to respond before next attack

        # After sequence, read DNA & decide mutation
        await asyncio.sleep(15)
        await self._observe_and_decide()

    async def run_scenario(self, scenario_name: str):
        """Run a named scenario from chaos_schedule.yaml."""
        scenario = self._schedule.get("scenarios", {}).get(scenario_name)
        if not scenario:
            logger.error(f"Scenario not found: {scenario_name}")
            return

        logger.info(f"🎬 Running scenario: {scenario['name']}")

        for step in scenario.get("steps", []):
            t_delay = step.get("t", 0)
            await asyncio.sleep(t_delay if t_delay >= 0 else 0)

            strand = step.get("strand")
            target = step.get("target")

            if strand and target:
                await dispatch(strand, target, nc=self.nc)

            nested = step.get("run")
            if nested:
                await self.run_scenario(nested)

            wait = step.get("wait", 0)
            if wait:
                await asyncio.sleep(wait)

    # ─── Mutation logic ───────────────────────────────────────────────────────

    async def _observe_and_decide(self):
        """Read DNA store and mutate if antibody is too fast."""
        try:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT AVG(recovery_time_ms) AS avg_ms
                    FROM dna_log
                    WHERE virus_gen = $1
                    AND timestamp > NOW() - INTERVAL '10 minutes'
                """, self.current_gen)

            avg_ms = float(row["avg_ms"] or 18000)
            logger.info(f"📊 Gen {self.current_gen} avg recovery: {avg_ms/1000:.1f}s")

            if avg_ms < 1000:
                reason = "switch_family — antibody too fast"
                self.current_gen = min(self.current_gen + 1, 3)
            elif avg_ms < 3000:
                reason = "escalate_same_family"
                self.current_gen = min(self.current_gen + 1, 3)
            else:
                reason = "holding current generation"

            await self._publish_brain("mutation", "system", {
                "reason": reason, "virus_gen": self.current_gen, "avg_ms": avg_ms
            })
        except Exception as e:
            logger.error(f"DNA observe error: {e}")

    async def _publish_brain(self, event: str, service: str, extra: dict = None):
        msg = {"event": event, "service": service, **(extra or {})}
        try:
            await self.nc.publish("brain.update", json.dumps(msg).encode())
        except Exception:
            pass

    # ─── Health score reader (used by timing_A) ───────────────────────────────

    async def get_health_score(self, service: str) -> float:
        """Estimate health 0→1 from recent DNA log (higher = healthier)."""
        try:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT success FROM dna_log
                    WHERE service = $1
                    ORDER BY timestamp DESC LIMIT 1
                """, service)
            if row:
                return 1.0 if row["success"] else 0.2
        except Exception:
            pass
        return 1.0   # assume healthy if no data


async def main():
    brain = VirusBrain()
    await brain.start()
    try:
        while brain.running:
            await brain.run_generation()
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        await brain.stop()


if __name__ == "__main__":
    asyncio.run(main())
