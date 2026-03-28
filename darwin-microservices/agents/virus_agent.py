"""
DARWIN Virus Agent — Full Attack Library (§9)

The Virus Agent is three things:
1. Attack Library     → the actual chaos injection functions (18 strands, 5 families)
2. Virus Brain        → decides what to inject, when, how to mutate
3. Generation Tracker → knows when antibody has adapted, triggers mutation

Mutation Trigger Logic:
    avg_recovery_time_ms < 3000  →  escalate_same_family
    avg_recovery_time_ms < 1000  →  switch_family
    honeypot_deployed == True    →  camouflage_mode
    preemptive_action == True    →  timing_attack
    unknown_strand_rate == 0.0   →  combo_attack
"""

import os
import time
import random
import json
import asyncio
import logging
from typing import Optional

import nats
from kubernetes import client, config

from constants import (
    NATSSubjects, BrainEvents, ServiceConfig,
    STRANDS, MUTATION_TRIGGERS, DBConfig,
)
from istio_client import IstioClient

logging.basicConfig(level=logging.INFO, format="[🦠 VIRUS] %(message)s")
log = logging.getLogger("virus_agent")

NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)


# ═══════════════════════════════════════════════════════════════
# ATTACK LIBRARY — 18 Strands, 5 Families (§9)
# ═══════════════════════════════════════════════════════════════

class AttackLibrary:
    """All 18 chaos injection functions organized by family."""

    def __init__(self):
        self.k8s_v1: Optional[client.CoreV1Api] = None
        self.k8s_apps_v1: Optional[client.AppsV1Api] = None
        self.istio = IstioClient()

        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                log.warning("K8s config not found — attacks will be simulated")

        try:
            self.k8s_v1 = client.CoreV1Api()
            self.k8s_apps_v1 = client.AppsV1Api()
        except Exception:
            pass

    def _get_pods(self, service: str, namespace: str = "default") -> list:
        """Get pods for a service."""
        if not self.k8s_v1:
            return []
        try:
            pods = self.k8s_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app={service}"
            )
            return pods.items
        except Exception:
            return []

    # ── Family 1: Pod Crash (Gen 1, 4 strands) ──────────────

    async def pod_crash_A(self, service: str) -> dict:
        """Single OOMKill on target service."""
        log.info(f"pod_crash_A: OOMKill on {service}")
        pods = self._get_pods(service)
        if pods:
            pod = random.choice(pods)
            try:
                self.k8s_v1.delete_namespaced_pod(
                    name=pod.metadata.name,
                    namespace="default",
                    grace_period_seconds=0,
                )
                return {"strand": "pod_crash_A", "service": service, "pod": pod.metadata.name, "success": True}
            except Exception as e:
                log.error(f"pod_crash_A failed: {e}")
        return {"strand": "pod_crash_A", "service": service, "success": False, "simulated": True}

    async def pod_crash_B(self, service: str) -> dict:
        """Cascade: kill primary, then downstream after 3s delay."""
        log.info(f"pod_crash_B: Cascade kill starting at {service}")
        result1 = await self.pod_crash_A(service)
        await asyncio.sleep(3)
        # Kill downstream (order-service if payment, notification if order)
        downstream_map = {
            "payment-service": "order-service",
            "order-service": "inventory-service",
            "auth-service": "api-gateway",
        }
        downstream = downstream_map.get(service, "notification-service")
        result2 = await self.pod_crash_A(downstream)
        return {"strand": "pod_crash_B", "service": service, "cascade": downstream,
                "results": [result1, result2], "success": True}

    async def pod_crash_C(self, service: str) -> dict:
        """Kill under load: generate traffic burst, kill at peak."""
        log.info(f"pod_crash_C: Kill under load on {service}")
        # Simulate high load by rapid requests
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                tasks = []
                for _ in range(50):
                    tasks.append(http.post(f"http://{service}:8000/process",
                                           json={"load": True}))
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        # Kill at peak
        result = await self.pod_crash_A(service)
        result["strand"] = "pod_crash_C"
        return result

    async def pod_crash_D(self, service: str) -> dict:
        """Kill + corrupt ConfigMap: set DB_HOST to invalid value."""
        log.info(f"pod_crash_D: Kill + ConfigMap corruption on {service}")
        await self.pod_crash_A(service)
        if self.k8s_v1:
            try:
                self.k8s_v1.patch_namespaced_config_map(
                    name="microservices-config",
                    namespace="default",
                    body={"data": {"DATABASE_URL": "postgresql://invalid:invalid@nowhere:5432/gone"}},
                )
                log.info("  ConfigMap corrupted → DB_HOST set to invalid")
            except Exception as e:
                log.warning(f"  ConfigMap patch failed: {e}")
        return {"strand": "pod_crash_D", "service": service, "success": True}

    # ── Family 2: Network Attacks (Gen 1, 4 strands, Istio-based) ──

    async def network_A(self, service: str) -> dict:
        """Inject 2000ms fixed latency via Istio fault injection."""
        log.info(f"network_A: 2000ms latency on {service}")
        await self.istio.inject_latency(service, delay_ms=2000)
        return {"strand": "network_A", "service": service, "delay_ms": 2000, "success": True}

    async def network_B(self, service: str) -> dict:
        """Inject 30% packet loss + 500ms latency."""
        log.info(f"network_B: 30% loss + 500ms latency on {service}")
        await self.istio.inject_packet_loss(service, loss_pct=30, delay_ms=500)
        return {"strand": "network_B", "service": service, "success": True}

    async def network_C(self, service: str) -> dict:
        """DNS poisoning simulation — extreme latency on discovery."""
        log.info(f"network_C: DNS poisoning sim on {service}")
        await self.istio.inject_latency(service, delay_ms=10000)
        return {"strand": "network_C", "service": service, "success": True}

    async def network_D(self, services: list[str]) -> dict:
        """Network partition: isolate services from each other."""
        log.info(f"network_D: Partition {services}")
        await self.istio.inject_network_partition(services)
        return {"strand": "network_D", "services": services, "success": True}

    # ── Family 3: Resource Pressure (Gen 1, 4 strands) ──────

    async def resource_A(self, service: str) -> dict:
        """Deploy CPU stress pod on same node as target."""
        log.info(f"resource_A: CPU stress on {service}")
        if self.k8s_v1:
            try:
                stress_pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name=f"stress-cpu-{service}-{int(time.time())}",
                        labels={"role": "chaos-stress", "target": service},
                    ),
                    spec=client.V1PodSpec(
                        containers=[client.V1Container(
                            name="stress",
                            image="polinux/stress",
                            command=["stress"],
                            args=["--cpu", "2", "--timeout", "60s"],
                            resources=client.V1ResourceRequirements(
                                limits={"cpu": "500m", "memory": "128Mi"},
                            ),
                        )],
                        restart_policy="Never",
                    ),
                )
                self.k8s_v1.create_namespaced_pod("default", stress_pod)
            except Exception as e:
                log.warning(f"Stress pod failed: {e}")
        return {"strand": "resource_A", "service": service, "success": True}

    async def resource_B(self, service: str) -> dict:
        """Memory leak simulation."""
        log.info(f"resource_B: Memory leak on {service}")
        if self.k8s_v1:
            try:
                stress_pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name=f"stress-mem-{service}-{int(time.time())}",
                        labels={"role": "chaos-stress", "target": service},
                    ),
                    spec=client.V1PodSpec(
                        containers=[client.V1Container(
                            name="stress",
                            image="polinux/stress",
                            command=["stress"],
                            args=["--vm", "1", "--vm-bytes", "50M", "--vm-hang", "0", "--timeout", "60s"],
                            resources=client.V1ResourceRequirements(
                                limits={"cpu": "200m", "memory": "128Mi"},
                            ),
                        )],
                        restart_policy="Never",
                    ),
                )
                self.k8s_v1.create_namespaced_pod("default", stress_pod)
            except Exception as e:
                log.warning(f"Memory stress pod failed: {e}")
        return {"strand": "resource_B", "service": service, "success": True}

    async def resource_C(self, service: str) -> dict:
        """Disk fill to 95%."""
        log.info(f"resource_C: Disk fill on {service}")
        if self.k8s_v1:
            try:
                fill_pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        name=f"stress-disk-{service}-{int(time.time())}",
                        labels={"role": "chaos-stress", "target": service},
                    ),
                    spec=client.V1PodSpec(
                        containers=[client.V1Container(
                            name="fill",
                            image="busybox",
                            command=["/bin/sh", "-c",
                                     "dd if=/dev/zero of=/tmp/fill bs=1M count=100 && sleep 60"],
                            resources=client.V1ResourceRequirements(
                                limits={"cpu": "100m", "memory": "64Mi"},
                            ),
                        )],
                        restart_policy="Never",
                    ),
                )
                self.k8s_v1.create_namespaced_pod("default", fill_pod)
            except Exception as e:
                log.warning(f"Disk fill pod failed: {e}")
        return {"strand": "resource_C", "service": service, "success": True}

    async def resource_D(self, service: str) -> dict:
        """Combo: CPU + memory + resource exhaustion simultaneously."""
        log.info(f"resource_D: Combo attack on {service}")
        results = await asyncio.gather(
            self.resource_A(service),
            self.resource_B(service),
            return_exceptions=True,
        )
        return {"strand": "resource_D", "service": service, "results": str(results), "success": True}

    # ── Family 4: Timing Attacks (Gen 2, 3 strands) ─────────

    async def timing_A(self, service: str, nc: nats.NATS) -> dict:
        """Wait for 50% recovery, then strike during recovery window."""
        log.info(f"timing_A: Watching for recovery window on {service}...")

        recovery_midpoint_event = asyncio.Event()

        async def on_recovery(msg):
            data = json.loads(msg.data.decode())
            if (data.get("event") == BrainEvents.RECOVERY_STARTED and
                    data.get("service") == service):
                # Wait for midpoint
                await asyncio.sleep(5)  # Approximate midpoint wait
                recovery_midpoint_event.set()

        sub = await nc.subscribe(NATSSubjects.BRAIN_UPDATE, cb=on_recovery)

        # First, trigger an initial attack to cause recovery
        await self.pod_crash_A(service)

        # Wait for recovery midpoint (timeout 30s)
        try:
            await asyncio.wait_for(recovery_midpoint_event.wait(), timeout=30)
            log.info(f"  Recovery midpoint detected — STRIKING NOW!")
            result = await self.pod_crash_A(service)
            result["strand"] = "timing_A"
        except asyncio.TimeoutError:
            log.info(f"  Recovery midpoint timeout — striking anyway")
            result = await self.pod_crash_A(service)
            result["strand"] = "timing_A"

        await sub.unsubscribe()
        return result

    async def timing_B(self, service: str, nc: nats.NATS) -> dict:
        """Watch which failover route antibody uses, attack that instead."""
        log.info(f"timing_B: Watching failover routes for {service}...")
        failover_target = None
        found = asyncio.Event()

        async def on_failover(msg):
            nonlocal failover_target
            data = json.loads(msg.data.decode())
            if data.get("event") == BrainEvents.RECOVERY_STARTED:
                # The antibody might failover to another service
                failover_target = data.get("failover_to", "order-service")
                found.set()

        sub = await nc.subscribe(NATSSubjects.BRAIN_UPDATE, cb=on_failover)
        await self.pod_crash_A(service)

        try:
            await asyncio.wait_for(found.wait(), timeout=20)
            if failover_target:
                log.info(f"  Failover detected → {failover_target}. Attacking THAT!")
                result = await self.pod_crash_A(failover_target)
                result["strand"] = "timing_B"
                result["original_target"] = service
                await sub.unsubscribe()
                return result
        except asyncio.TimeoutError:
            pass

        await sub.unsubscribe()
        return {"strand": "timing_B", "service": service, "success": False}

    async def timing_C(self, service: str, nc: nats.NATS) -> dict:
        """Slow burn: blind monitoring first, then attack real target."""
        log.info(f"timing_C: Blinding monitoring, then attacking {service}...")
        # First, degrade monitoring service
        await self.istio.inject_latency("notification-service", delay_ms=5000)
        await asyncio.sleep(3)
        # Now attack real target while monitoring is blind
        result = await self.pod_crash_A(service)
        result["strand"] = "timing_C"
        # Clean up monitoring degradation
        await self.istio.remove_chaos("notification-service")
        return result

    # ── Family 5: Camouflage / Cost (Gen 3, 3 strands) ──────

    async def camouflage_A(self, service: str) -> dict:
        """Slow burn: degrade performance 2% every 5 minutes.
        Stays under IF threshold each step. Only CUSUM catches this."""
        log.info(f"camouflage_A: Slow burn on {service}...")
        degradation_pct = 0.02
        current_cpu_limit = 1000  # millicores
        steps = 5  # 5 degradation steps for demo speed

        for step in range(steps):
            current_cpu_limit = int(current_cpu_limit * (1 - degradation_pct))
            if self.k8s_apps_v1:
                try:
                    self.k8s_apps_v1.patch_namespaced_deployment(
                        name=service,
                        namespace="default",
                        body={
                            "spec": {
                                "template": {
                                    "spec": {
                                        "containers": [{
                                            "name": service,
                                            "resources": {
                                                "limits": {"cpu": f"{current_cpu_limit}m"}
                                            },
                                        }]
                                    }
                                }
                            }
                        },
                    )
                    log.info(f"  Step {step+1}/{steps}: CPU limit → {current_cpu_limit}m")
                except Exception as e:
                    log.warning(f"  Degradation step failed: {e}")
            await asyncio.sleep(10)  # Compressed for demo (spec says 300s)

        return {"strand": "camouflage_A", "service": service, "final_cpu": current_cpu_limit, "success": True}

    async def cost_A(self, service: str) -> dict:
        """Resource waste via unnecessary scaling."""
        log.info(f"cost_A: Wasteful scaling on {service}")
        if self.k8s_apps_v1:
            try:
                self.k8s_apps_v1.patch_namespaced_deployment_scale(
                    name=service, namespace="default",
                    body={"spec": {"replicas": 6}},
                )
            except Exception as e:
                log.warning(f"Scale failed: {e}")
        return {"strand": "cost_A", "service": service, "success": True}

    async def cost_B(self, service: str) -> dict:
        """Trigger excessive logging by causing error cascades."""
        log.info(f"cost_B: Error cascade on {service}")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                for _ in range(100):
                    await http.get(f"http://{service}:8000/nonexistent-endpoint")
        except Exception:
            pass
        return {"strand": "cost_B", "service": service, "success": True}

    # ── Cleanup ──────────────────────────────────────────────

    async def cleanup_all(self):
        """Remove all chaos artifacts."""
        for service in ServiceConfig.SERVICE_NAMES:
            await self.istio.remove_chaos(service)
        # Delete stress pods
        if self.k8s_v1:
            try:
                pods = self.k8s_v1.list_namespaced_pod(
                    "default", label_selector="role=chaos-stress"
                )
                for pod in pods.items:
                    self.k8s_v1.delete_namespaced_pod(
                        pod.metadata.name, "default", grace_period_seconds=0
                    )
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# VIRUS BRAIN — Generation Controller (§9)
# ═══════════════════════════════════════════════════════════════

class VirusBrain:
    """Decides attack sequences per generation and triggers mutations."""

    def __init__(self):
        self.attacks = AttackLibrary()
        self.nc: Optional[nats.NATS] = None
        self.gen = 1
        self.antibody_gen = 1
        self.attack_log: list[dict] = []

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        log.info(f"Connected to NATS at {NATS_URL}")

        # Listen for recovery events to track antibody performance
        async def on_brain_update(msg):
            data = json.loads(msg.data.decode())
            if data.get("event") == BrainEvents.RECOVERY_COMPLETE:
                self.attack_log.append(data)

        await self.nc.subscribe(NATSSubjects.BRAIN_UPDATE, cb=on_brain_update)

    def _build_gen1_sequence(self) -> list[dict]:
        """Gen 1: Basic attacks — test fundamental defenses."""
        return [
            {"strand": "pod_crash_A", "target": "payment-service"},
            {"strand": "network_A",   "target": "api-gateway"},
            {"strand": "resource_A",  "target": "auth-service"},
            {"strand": "pod_crash_B", "target": "order-service"},
        ]

    def _build_gen2_sequence(self) -> list[dict]:
        """Gen 2: Timing attacks — exploit recovery windows."""
        return [
            {"strand": "timing_A",  "target": "payment-service"},
            {"strand": "timing_B",  "target": "order-service"},
            {"strand": "network_D", "targets": ["payment-service", "inventory-service"]},
        ]

    def _build_gen3_sequence(self) -> list[dict]:
        """Gen 3: Camouflage — stay below IF thresholds."""
        return [
            {"strand": "camouflage_A", "target": "auth-service"},
            {"strand": "timing_A",     "target": "payment-service"},
            {"strand": "pod_crash_A",  "target": "notification-service"},
        ]

    async def _execute_strand(self, strand_id: str,
                               target: str = None,
                               targets: list[str] = None) -> dict:
        """Execute a single attack strand."""
        # Publish virus.inject event
        if self.nc:
            await self.nc.publish(NATSSubjects.VIRUS_INJECT, json.dumps({
                "strand": strand_id,
                "target": target or targets,
                "generation": self.gen,
                "timestamp": time.time(),
            }).encode())

            await self.nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps({
                "event": BrainEvents.ATTACK_DETECTED,
                "strand_id": strand_id,
                "service": target or (targets[0] if targets else "unknown"),
                "virus_gen": self.gen,
                "attack_family": STRANDS.get(strand_id, {}).get("family", "unknown"),
                "timestamp": time.time(),
            }).encode())

        # Execute the attack
        attack_map = {
            "pod_crash_A": lambda: self.attacks.pod_crash_A(target),
            "pod_crash_B": lambda: self.attacks.pod_crash_B(target),
            "pod_crash_C": lambda: self.attacks.pod_crash_C(target),
            "pod_crash_D": lambda: self.attacks.pod_crash_D(target),
            "network_A":   lambda: self.attacks.network_A(target),
            "network_B":   lambda: self.attacks.network_B(target),
            "network_C":   lambda: self.attacks.network_C(target),
            "network_D":   lambda: self.attacks.network_D(targets or [target]),
            "resource_A":  lambda: self.attacks.resource_A(target),
            "resource_B":  lambda: self.attacks.resource_B(target),
            "resource_C":  lambda: self.attacks.resource_C(target),
            "resource_D":  lambda: self.attacks.resource_D(target),
            "timing_A":    lambda: self.attacks.timing_A(target, self.nc),
            "timing_B":    lambda: self.attacks.timing_B(target, self.nc),
            "timing_C":    lambda: self.attacks.timing_C(target, self.nc),
            "camouflage_A": lambda: self.attacks.camouflage_A(target),
            "cost_A":      lambda: self.attacks.cost_A(target),
            "cost_B":      lambda: self.attacks.cost_B(target),
        }

        executor = attack_map.get(strand_id)
        if executor:
            return await executor()
        return {"strand": strand_id, "error": "Unknown strand", "success": False}

    async def _observe_and_decide(self):
        """Read DNA store to detect when antibody has adapted — trigger mutation."""
        recent_recoveries = [
            log_entry for log_entry in self.attack_log[-10:]
            if log_entry.get("recovery_time_ms", 99999) > 0
        ]

        if not recent_recoveries:
            return

        avg_recovery = sum(
            r.get("recovery_time_ms", 20000) for r in recent_recoveries
        ) / len(recent_recoveries)

        honeypot_deployed = any(
            r.get("event") == BrainEvents.HONEYPOT_DEPLOYED for r in self.attack_log[-5:]
        )
        preemptive_action = any(
            r.get("event") == BrainEvents.PREEMPTIVE_ACTION for r in self.attack_log[-5:]
        )

        if avg_recovery < 1000:
            log.info(f"⚡ Antibody ultra-fast ({avg_recovery:.0f}ms) — SWITCHING FAMILY")
            self.gen += 1
        elif avg_recovery < 3000:
            log.info(f"🔄 Antibody fast ({avg_recovery:.0f}ms) — ESCALATING in family")
            self.gen += 1
        elif honeypot_deployed:
            log.info("🎭 Honeypot detected — switching to CAMOUFLAGE")
            self.gen = 3
        elif preemptive_action:
            log.info("🎯 Preemptive detected — switching to TIMING ATTACK")
            self.gen = max(self.gen, 2)

    async def run_generation(self, gen: int):
        """Execute a complete generation's attack sequence."""
        sequence_builders = {
            1: self._build_gen1_sequence,
            2: self._build_gen2_sequence,
            3: self._build_gen3_sequence,
        }
        builder = sequence_builders.get(min(gen, 3), self._build_gen1_sequence)
        sequence = builder()

        log.info(f"\n{'═'*50}")
        log.info(f"  VIRUS GENERATION {gen} — {len(sequence)} strands")
        log.info(f"{'═'*50}")

        # Publish generation event
        if self.nc:
            await self.nc.publish(NATSSubjects.VIRUS_GENERATION_EVENT, json.dumps({
                "virus_gen": gen,
                "strands": [s["strand"] for s in sequence],
                "timestamp": time.time(),
            }).encode())

        for i, attack in enumerate(sequence):
            log.info(f"\n--- Strand {i+1}/{len(sequence)}: {attack['strand']} ---")
            result = await self._execute_strand(
                strand_id=attack["strand"],
                target=attack.get("target"),
                targets=attack.get("targets"),
            )
            log.info(f"Result: {json.dumps(result, default=str)}")

            # Wait between attacks (30s for demo pacing)
            if i < len(sequence) - 1:
                wait_time = 30
                log.info(f"⏳ Waiting {wait_time}s before next strand...")
                await asyncio.sleep(wait_time)

    async def run_evolution_loop(self, max_gen: int = 3):
        """Main evolution loop: attack → adapt → mutate → repeat."""
        await self.connect()

        log.info("\n" + "═" * 60)
        log.info("  🦠 DARWIN AUTONOMOUS VIRUS — EVOLUTION ENGINE ONLINE")
        log.info(f"  Max Generations: {max_gen} | Interval: 30s between strands")
        log.info("═" * 60)

        while self.gen <= max_gen:
            await self.run_generation(self.gen)

            # Observe antibody performance and decide mutation
            await asyncio.sleep(10)  # Let recoveries complete
            await self._observe_and_decide()

            if self.gen <= max_gen:
                log.info(f"\n🧬 MUTATION: Evolving to Generation {self.gen}")
                await asyncio.sleep(5)

        log.info("\n" + "═" * 60)
        log.info(f"  🦠 EVOLUTION COMPLETE — Reached Gen {self.gen}")
        log.info("═" * 60)

        # Cleanup
        await self.attacks.cleanup_all()


# ═══════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    virus = VirusBrain()
    asyncio.run(virus.run_evolution_loop(max_gen=3))
