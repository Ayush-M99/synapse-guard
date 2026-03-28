"""
DARWIN Honeypot System (§7)

When RF confidence < 0.60 (unknown attack), deploy a sacrificial replica pod.
Not a fake server — a real copy of the targeted service, instrumented for observation.

Full Flow:
    Unknown attack detected (RF < 0.60)
        ↓
    Spin up honeypot pod (copy of targeted service)
    Redirect 20% of attack traffic to honeypot via Istio VirtualService
        ↓
    Two things happen simultaneously:
      → Conservative recovery runs on real service (buys time)
      → HoneypotObserver watches metrics for 10 seconds (5 snapshots × 2s)
        ↓
    HoneypotObserver builds attack signature from 5 snapshots
    RF classifier runs again on richer signature
        ↓
    New Strand + Signature nodes created in Neo4j (crystallize)
    NATS publishes brain.update → new_strand_discovered
    Dashboard brain map animates new purple node
    Honeypot pod terminated | Signature cached in Redis
"""

import os
import time
import json
import asyncio
import logging
from typing import Optional

import httpx
import nats
from kubernetes import client, config
from neo4j import GraphDatabase

from constants import (
    NATSSubjects, BrainEvents, DBConfig, MLConfig,
)
from llm_rag import synthesize_playbook

logging.basicConfig(level=logging.INFO, format="[HONEYPOT] %(message)s")
log = logging.getLogger("honeypot")

try:
    from istio_client import IstioClient
except ImportError:
    IstioClient = None


# ═══════════════════════════════════════════════════════════════
# HONEYPOT POD DEPLOYER
# ═══════════════════════════════════════════════════════════════

class HoneypotDeployer:
    """Deploy and manage sacrificial honeypot pods."""

    def __init__(self):
        self.k8s_v1: Optional[client.CoreV1Api] = None
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                log.warning("K8s config not found — honeypot deployment will be simulated")

        try:
            self.k8s_v1 = client.CoreV1Api()
        except Exception:
            pass

    async def deploy_honeypot(self, targeted_service: str,
                               namespace: str = "default") -> str:
        """Spin up a sacrificial replica pod for observation.
        Returns the honeypot pod name."""
        pod_name = f"honeypot-{targeted_service}-{int(time.time())}"

        honeypot_manifest = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    "role": "honeypot",
                    "observing": targeted_service,
                    "app": targeted_service,  # Same label — receives attack traffic
                },
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="honeypot",
                        image=f"darwin/{targeted_service}:latest",
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "50m", "memory": "64Mi"},
                            limits={"cpu": "100m", "memory": "128Mi"},
                        ),
                        env=[
                            client.V1EnvVar(name="HONEYPOT_MODE", value="true"),
                        ],
                        ports=[client.V1ContainerPort(container_port=8000)],
                    )
                ],
                termination_grace_period_seconds=0,
            ),
        )

        if self.k8s_v1:
            try:
                self.k8s_v1.create_namespaced_pod(namespace, honeypot_manifest)
                log.info(f"🍯 Honeypot pod deployed: {pod_name}")
            except Exception as e:
                log.error(f"Failed to deploy honeypot: {e}")
                return f"simulated-{pod_name}"
        else:
            log.info(f"🍯 [SIM] Honeypot pod simulated: {pod_name}")

        return pod_name

    async def delete_honeypot(self, pod_name: str, namespace: str = "default"):
        """Terminate honeypot pod after observation."""
        if self.k8s_v1:
            try:
                self.k8s_v1.delete_namespaced_pod(
                    name=pod_name, namespace=namespace,
                    grace_period_seconds=0,
                )
                log.info(f"🗑️ Honeypot pod terminated: {pod_name}")
            except Exception as e:
                log.warning(f"Could not delete honeypot {pod_name}: {e}")
        else:
            log.info(f"🗑️ [SIM] Honeypot pod terminated: {pod_name}")


# ═══════════════════════════════════════════════════════════════
# HONEYPOT OBSERVER (§7 — 10-second observation window)
# ═══════════════════════════════════════════════════════════════

class HoneypotObserver:
    """Watches honeypot metrics for 10 seconds (5 snapshots × 2s intervals).
    Builds attack signature from observations."""

    def __init__(self, honeypot_pod: str, targeted_service: str):
        self.pod = honeypot_pod
        self.service = targeted_service
        self.observations: list[dict] = []
        self.sample_interval = 2     # seconds between samples
        self.observation_window = 10  # total observation time

    async def observe(self, prometheus_url: str = "http://localhost:9090") -> dict:
        """Run 10-second observation loop, return built signature."""
        log.info(f"👁️ Observing {self.pod} for {self.observation_window}s...")

        for tick in range(self.observation_window // self.sample_interval):
            snapshot = await self._capture_metrics_snapshot(prometheus_url)
            self.observations.append(snapshot)
            log.info(f"  Snapshot {tick+1}/5: cpu={snapshot.get('cpu_delta', 0):.2f} "
                     f"mem={snapshot.get('memory_delta', 0):.2f} "
                     f"err={snapshot.get('error_rate_delta', 0):.2f}")
            await asyncio.sleep(self.sample_interval)

        signature = self._build_signature()
        log.info(f"📋 Signature built: {json.dumps(signature, indent=2)}")
        return signature

    async def _capture_metrics_snapshot(self, prometheus_url: str) -> dict:
        """Capture current metrics snapshot from Prometheus."""
        queries = {
            "cpu_delta": f'sum(rate(container_cpu_usage_seconds_total{{pod=~"{self.service}-.*"}}[30s])) * 100',
            "memory_delta": f'sum(container_memory_usage_bytes{{pod=~"{self.service}-.*"}}) / (256*1024*1024) * 100',
            "error_rate_delta": f'sum(rate(http_errors_total{{service="{self.service}"}}[30s])) / clamp_min(sum(rate(http_requests_total{{service="{self.service}"}}[30s])), 0.001)',
            "restart_count_delta": f'sum(increase(kube_pod_container_status_restarts_total{{pod=~"{self.service}-.*"}}[1m]))',
            "latency_delta": f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{self.service}"}}[30s])) by (le))',
        }

        result = {}
        async with httpx.AsyncClient(timeout=3.0) as http:
            for name, query in queries.items():
                try:
                    resp = await http.get(
                        f"{prometheus_url}/api/v1/query",
                        params={"query": query}
                    )
                    data = resp.json()
                    if data.get("data", {}).get("result"):
                        val = float(data["data"]["result"][0]["value"][1])
                        import math
                        if math.isnan(val) or math.isinf(val):
                            val = 0.0
                    else:
                        val = 0.0
                except Exception:
                    val = 0.0
                result[name] = val

        return result

    def _build_signature(self) -> dict:
        """Build attack signature from collected observations."""
        return {
            "cpu_delta": self._classify_magnitude("cpu_delta"),
            "memory_delta": self._classify_magnitude("memory_delta"),
            "error_rate_delta": self._classify_magnitude("error_rate_delta"),
            "restart_delta": self._classify_magnitude("restart_count_delta"),
            "latency_delta": self._classify_magnitude("latency_delta"),
            "pattern": self._detect_pattern(),
            "affected_services": self._check_blast_radius(),
        }

    def _classify_magnitude(self, metric: str) -> str:
        """Bucket metric values: low / medium / high / spike."""
        values = [o.get(metric, 0) for o in self.observations]
        if not values:
            return "low"
        avg = sum(values) / len(values)
        if avg < 0.2:
            return "low"
        if avg < 0.6:
            return "medium"
        if avg < 0.85:
            return "high"
        return "spike"

    def _detect_pattern(self) -> str:
        """Detect attack pattern from CPU observations."""
        cpu_values = [o.get("cpu_delta", 0) for o in self.observations]
        if not cpu_values or len(cpu_values) < 2:
            return "unknown"
        if max(cpu_values) - min(cpu_values) > 0.7:
            return "spike"
        if cpu_values[-1] > cpu_values[0] + 0.3:
            return "gradual"
        return "oscillating"

    def _check_blast_radius(self) -> list[str]:
        """Check which other services are affected (stub — would query Prometheus)."""
        return [self.service]


# ═══════════════════════════════════════════════════════════════
# CRYSTALLIZER — Write new strand to Neo4j (§7)
# ═══════════════════════════════════════════════════════════════

class StrandCrystallizer:
    """Crystallize newly discovered attack strands into the knowledge graph."""

    def __init__(self):
        self.neo4j_driver = None
        try:
            self.neo4j_driver = GraphDatabase.driver(
                os.getenv("NEO4J_URI", DBConfig.NEO4J_URI),
                auth=(DBConfig.NEO4J_USER, DBConfig.NEO4J_PASS),
            )
        except Exception as e:
            log.warning(f"Neo4j not available: {e}")

    async def crystallize_new_strand(
        self,
        signature: dict,
        recovery_used: str,
        recovery_time_ms: float,
        family_guess: str,
        confidence: float,
        current_gen: int,
        nc: Optional[nats.NATS] = None,
    ) -> str:
        """Create new Strand + Signature + Recovery nodes in Neo4j.
        Returns the new strand_id."""
        strand_id = f"unknown_{int(time.time())}"
        is_camouflage = signature.get("pattern") == "gradual"

        if self.neo4j_driver:
            try:
                with self.neo4j_driver.session() as session:
                    session.run("""
                        CREATE (st:Strand {
                            id: $strand_id,
                            description: "discovered via honeypot",
                            generation: $current_gen,
                            camouflage: $is_camouflage,
                            avg_recovery_time_ms: $recovery_time,
                            discovered_at: datetime()
                        })
                        WITH st
                        MATCH (f:AttackFamily {name: $family})
                        CREATE (st)-[:BELONGS_TO]->(f)
                        WITH st
                        CREATE (sig:Signature {
                            id: 'sig_' + $strand_id,
                            rf_label: $family,
                            cpu_delta: $cpu_delta,
                            memory_delta: $memory_delta,
                            error_rate_delta: $error_rate_delta,
                            pattern: $pattern
                        })
                        CREATE (st)-[:HAS_SIGNATURE]->(sig)
                        WITH st
                        MATCH (rec:Recovery {id: $recovery_id})
                        CREATE (st)-[:COUNTERED_BY]->(rec)
                    """,
                        strand_id=strand_id,
                        current_gen=current_gen,
                        is_camouflage=is_camouflage,
                        recovery_time=recovery_time_ms,
                        family=family_guess,
                        cpu_delta=signature.get("cpu_delta", "low"),
                        memory_delta=signature.get("memory_delta", "low"),
                        error_rate_delta=signature.get("error_rate_delta", "low"),
                        pattern=signature.get("pattern", "unknown"),
                        recovery_id=recovery_used,
                    )
                    log.info(f"💎 Crystallized new strand: {strand_id} → {family_guess}")
            except Exception as e:
                log.error(f"Neo4j crystallize failed: {e}")
        else:
            log.info(f"💎 [SIM] Crystallized: {strand_id} → {family_guess}")

        # Publish discovery event to dashboard
        if nc:
            await nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps({
                "event": BrainEvents.NEW_STRAND_DISCOVERED,
                "strand_id": strand_id,
                "family": family_guess,
                "confidence": confidence,
                "signature": signature,
                "timestamp": time.time(),
            }).encode())

        return strand_id


# ═══════════════════════════════════════════════════════════════
# HONEYPOT ORCHESTRATOR — Full Flow (§7)
# ═══════════════════════════════════════════════════════════════

class HoneypotSystem:
    """Orchestrates the complete honeypot flow:
    deploy → observe → crystallize → cleanup."""

    def __init__(self):
        self.deployer = HoneypotDeployer()
        self.crystallizer = StrandCrystallizer()
        self.istio = IstioClient() if IstioClient else None
        self.nc: Optional[nats.NATS] = None

    async def connect(self, nc: nats.NATS):
        self.nc = nc

    async def handle_unknown_attack(
        self,
        service: str,
        initial_rf_family: str,
        initial_rf_confidence: float,
        current_gen: int,
        recovery_used: str = "rec_default",
        recovery_time_ms: float = 0.0,
    ) -> str:
        """Complete honeypot flow for an unknown attack (RF < 0.60).

        Returns the new strand_id."""
        log.info(f"═" * 50)
        log.info(f"HONEYPOT FLOW TRIGGERED for {service}")
        log.info(f"RF confidence: {initial_rf_confidence:.2f} (< 0.60 = UNKNOWN)")
        log.info(f"═" * 50)

        # 1. Publish honeypot_deployed event
        if self.nc:
            await self.nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps({
                "event": BrainEvents.HONEYPOT_DEPLOYED,
                "service": service,
                "timestamp": time.time(),
            }).encode())

        # 2. Deploy honeypot pod
        honeypot_pod = await self.deployer.deploy_honeypot(service)

        # 3. Split traffic 80/20 via Istio
        if self.istio:
            await self.istio.split_traffic_to_honeypot(service, honeypot_weight=20)

        # 4. Publish observing event
        if self.nc:
            await self.nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps({
                "event": BrainEvents.HONEYPOT_OBSERVING,
                "service": service,
                "honeypot_pod": honeypot_pod,
                "timestamp": time.time(),
            }).encode())

        # 5. Run 10-second observation
        observer = HoneypotObserver(honeypot_pod, service)
        signature = await observer.observe()

        # 6. Crystallize new strand in Neo4j
        strand_id = await self.crystallizer.crystallize_new_strand(
            signature=signature,
            recovery_used=recovery_used,
            recovery_time_ms=recovery_time_ms,
            family_guess=initial_rf_family,
            confidence=initial_rf_confidence,
            current_gen=current_gen,
            nc=self.nc,
        )

        # 6.5 Synthesize dynamic playbook using Gemini RAG
        dynamic_playbook = await synthesize_playbook(strand_id, service, signature)

        # 7. Cache in Redis immunity memory with AI-generated playbook
        if self.nc:
            await self.nc.publish(NATSSubjects.IMMUNITY_WRITE, json.dumps({
                "strand_id": strand_id,
                "playbook": dynamic_playbook,
            }).encode())

        # 8. Cleanup
        if self.istio:
            await self.istio.remove_honeypot_split(service)
        await self.deployer.delete_honeypot(honeypot_pod)

        log.info(f"✅ Honeypot flow complete. New strand: {strand_id}")
        return strand_id
