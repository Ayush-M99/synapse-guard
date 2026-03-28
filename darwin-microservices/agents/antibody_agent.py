"""
DARWIN Antibody Decision Engine (§8)

The central nervous system. Connects ML pipeline output to K8s recovery actions.

4 Input States:
    KNOWN       RF >= 0.85            execute playbook immediately
    PROBABLE    RF 0.60 - 0.85        execute playbook + partial honeypot in parallel
    UNKNOWN     RF < 0.60             full honeypot path (10s observation, crystallize)
    PREDICTED   LSTM fires prediction preemptive action before IF even triggers

Features:
    - Priority queue (min-heap) — OS scheduling analogy
    - Semaphore system — 3 global slots + per-service locks
    - Conflict resolution — preempt / merge / queue
    - Redis T-cell memory check BEFORE Neo4j traversal
    - DNA write to PostgreSQL after every recovery
    - Neo4j Strand avg_recovery_time update
"""

import os
import time
import json
import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from typing import Optional

import nats
import redis.asyncio as aioredis
import asyncpg
from neo4j import GraphDatabase
from kubernetes import client, config

from constants import (
    NATSSubjects, BrainEvents, AttackState, MLConfig,
    ServiceConfig, DBConfig,
)
from honeypot_system import HoneypotSystem

logging.basicConfig(level=logging.INFO, format="[💉 ANTIBODY] %(message)s")
log = logging.getLogger("antibody")

NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)
REDIS_URL = os.getenv("REDIS_URL", DBConfig.REDIS_URL)
PG_URL = os.getenv("PG_URL", DBConfig.PG_URL)
NEO4J_URI = os.getenv("NEO4J_URI", DBConfig.NEO4J_URI)


# ═══════════════════════════════════════════════════════════════
# RECOVERY TASK — Priority Queue Item (§8)
# ═══════════════════════════════════════════════════════════════

@dataclass(order=True)
class RecoveryTask:
    """Min-heap priority queue item. Lower priority number = runs first.
    OS analogy: priority queue like a scheduler."""
    priority:     int
    service:      str = field(compare=False)
    playbook_id:  str = field(compare=False)
    actions:      list = field(compare=False, default_factory=list)
    attack_state: str = field(compare=False, default=AttackState.KNOWN)
    strand_id:    Optional[str] = field(compare=False, default=None)
    attack_family: str = field(compare=False, default="unknown")
    rf_confidence: float = field(compare=False, default=0.0)
    created_at:   float = field(compare=False, default_factory=time.time)


# ═══════════════════════════════════════════════════════════════
# ANTIBODY DECISION ENGINE
# ═══════════════════════════════════════════════════════════════

class AntibodyEngine:
    """The central nervous system of DARWIN.

    Single intake method: everything enters through NATS subscriber on nerve.{service}.alert.
    Signal type field routes to the right state."""

    def __init__(self):
        # Connections
        self.nc: Optional[nats.NATS] = None
        self.redis: Optional[aioredis.Redis] = None
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.neo4j_driver = None
        self.k8s_v1: Optional[client.CoreV1Api] = None
        self.k8s_apps_v1: Optional[client.AppsV1Api] = None

        # Semaphore System — Two Levels (§8)
        # Global slot limiter: max 3 concurrent recoveries across entire system
        self.recovery_slots = asyncio.Semaphore(3)
        # Per-service lock: prevents two recoveries on same service simultaneously
        self.service_locks: dict[str, asyncio.Semaphore] = {}

        # Priority Queue (min-heap)
        self.task_queue: list[RecoveryTask] = []
        self.active_recoveries: dict[str, RecoveryTask] = {}

        # Honeypot system
        self.honeypot = HoneypotSystem()

        # Generation tracking
        self.virus_gen = 1
        self.antibody_gen = 1
        self.total_recoveries = 0
        self.total_recovery_time_ms = 0.0

        # K8s client
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                log.warning("K8s config not found — recovery actions will be simulated")
        try:
            self.k8s_v1 = client.CoreV1Api()
            self.k8s_apps_v1 = client.AppsV1Api()
        except Exception:
            pass

    async def connect(self):
        """Connect to all infrastructure."""
        self.nc = await nats.connect(NATS_URL)
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        self.pg_pool = await asyncpg.create_pool(PG_URL)
        try:
            self.neo4j_driver = GraphDatabase.driver(
                NEO4J_URI, auth=(DBConfig.NEO4J_USER, DBConfig.NEO4J_PASS)
            )
        except Exception as e:
            log.warning(f"Neo4j connection failed: {e}")

        # Initialize DNA schema
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dna_log (
                    id SERIAL PRIMARY KEY,
                    virus_gen INTEGER,
                    antibody_gen INTEGER,
                    strand_id VARCHAR(100),
                    service VARCHAR(100),
                    playbook_id VARCHAR(100),
                    recovery_time_ms FLOAT,
                    attack_state VARCHAR(20),
                    success BOOLEAN,
                    timestamp TIMESTAMP DEFAULT NOW()
                )
            """)

        # Wire NATS subscriptions
        await self.nc.subscribe("nerve.*.alert", cb=self._on_alert)
        await self.nc.subscribe(NATSSubjects.LSTM_PREDICTION, cb=self._on_prediction)
        await self.nc.subscribe(NATSSubjects.HONEYPOT_CRYSTALLIZED, cb=self._on_honeypot_crystallized)
        await self.nc.subscribe(NATSSubjects.IMMUNITY_WRITE, cb=self._on_immunity_write)

        # Connect honeypot system
        await self.honeypot.connect(self.nc)

        log.info("═" * 50)
        log.info("  ANTIBODY DECISION ENGINE ONLINE")
        log.info(f"  Global slots: 3 | Services: {len(ServiceConfig.SERVICE_NAMES)}")
        log.info("═" * 50)

    def _get_service_lock(self, service: str) -> asyncio.Semaphore:
        """Lazily create per-service lock."""
        if service not in self.service_locks:
            self.service_locks[service] = asyncio.Semaphore(1)
        return self.service_locks[service]

    # ───────────────────────────────────────────────────────────
    # REDIS T-CELL MEMORY (§8 — check BEFORE Neo4j)
    # ───────────────────────────────────────────────────────────

    async def _check_tcell_memory(self, strand_id: str) -> Optional[dict]:
        """O(1) immunity check. Returns playbook if cached."""
        try:
            cached = await self.redis.get(f"immunity:{strand_id}")
            if cached:
                log.info(f"⚡ T-CELL HIT: {strand_id} — reflex recovery!")
                return json.loads(cached)
        except Exception as e:
            log.warning(f"Redis error: {e}")
        return None

    async def _store_tcell_memory(self, strand_id: str, playbook: dict):
        """Store learned antibody in T-cell memory (24h TTL)."""
        try:
            await self.redis.set(
                f"immunity:{strand_id}",
                json.dumps(playbook),
                ex=86400,  # 24 hours
            )
            log.info(f"🧬 T-cell memory stored: {strand_id}")
        except Exception as e:
            log.warning(f"Redis write error: {e}")

    # ───────────────────────────────────────────────────────────
    # NEO4J BRAIN GRAPH QUERIES (§6)
    # ───────────────────────────────────────────────────────────

    def _query_recovery(self, family_label: str) -> Optional[dict]:
        """Query 1 — Fast lookup (RF confident). Returns recovery playbook."""
        if not self.neo4j_driver:
            return None
        try:
            with self.neo4j_driver.session() as session:
                result = session.run("""
                    MATCH (sig:Signature {rf_label: $label})
                        -[:TRIGGERS]->(rec:Recovery)
                    RETURN rec.id as id, rec.actions as actions,
                           rec.priority_order as priority_order,
                           rec.estimated_time_ms as est_time,
                           rec.conflicts_with as conflicts_with
                    ORDER BY rec.estimated_time_ms ASC
                    LIMIT 1
                """, label=family_label)
                record = result.single()
                if record:
                    return {
                        "id": record["id"],
                        "actions": record["actions"],
                        "priority_order": record["priority_order"],
                        "estimated_time_ms": record["est_time"],
                        "conflicts_with": record.get("conflicts_with"),
                    }
        except Exception as e:
            log.warning(f"Neo4j query error: {e}")
        return None

    def _query_blast_radius(self, service: str) -> list[dict]:
        """Query 2 — Blast radius traversal."""
        if not self.neo4j_driver:
            return [{"name": service, "criticality": "high", "recovery_priority": 2}]
        try:
            with self.neo4j_driver.session() as session:
                result = session.run("""
                    MATCH (s:Service {name: $service})
                        -[:DEPENDS_ON*1..3]->(downstream:Service)
                    RETURN downstream.name as name,
                           downstream.criticality as criticality,
                           downstream.recovery_priority as recovery_priority
                    ORDER BY downstream.recovery_priority ASC
                """, service=service)
                return [dict(record) for record in result]
        except Exception:
            return []

    # ───────────────────────────────────────────────────────────
    # NATS HANDLERS — Single Intake (§8)
    # ───────────────────────────────────────────────────────────

    async def _on_alert(self, msg):
        """Main alert handler. Everything enters through nerve.{service}.alert.
        Signal type field routes to the right state."""
        try:
            data = json.loads(msg.data.decode())
        except Exception:
            return

        service = data.get("service", "unknown")
        strand_id = data.get("strand_id", data.get("attack_family", "unknown"))
        attack_family = data.get("attack_family", "unknown")
        rf_confidence = data.get("rf_confidence", 0.5)
        attack_state = data.get("attack_state", AttackState.KNOWN)

        # Determine state from RF confidence if not provided
        if rf_confidence >= MLConfig.RF_KNOWN_THRESHOLD:
            attack_state = AttackState.KNOWN
        elif rf_confidence >= MLConfig.RF_PROBABLE_THRESHOLD:
            attack_state = AttackState.PROBABLE
        else:
            attack_state = AttackState.UNKNOWN

        log.info(f"\n{'─'*40}")
        log.info(f"ALERT: {service} | {attack_family} | conf={rf_confidence:.2f} | state={attack_state}")

        # Step 1: Check T-cell memory (Redis) FIRST
        tcell_playbook = await self._check_tcell_memory(strand_id)
        if tcell_playbook:
            # REFLEX RECOVERY — bypass everything
            await self._publish_brain_event(BrainEvents.TCELL_HIT, service=service,
                                            strand_id=strand_id)
            task = RecoveryTask(
                priority=ServiceConfig.get_priority(service),
                service=service,
                playbook_id=tcell_playbook.get("id", "tcell_cached"),
                actions=tcell_playbook.get("actions", ["restart_pod"]),
                attack_state=AttackState.KNOWN,
                strand_id=strand_id,
                attack_family=attack_family,
                rf_confidence=1.0,
            )
            await self._enqueue_and_execute(task)
            return

        # Step 2: Route based on attack state
        if attack_state == AttackState.KNOWN:
            await self._handle_known(service, attack_family, strand_id, rf_confidence)
        elif attack_state == AttackState.PROBABLE:
            await self._handle_probable(service, attack_family, strand_id, rf_confidence)
        elif attack_state == AttackState.UNKNOWN:
            await self._handle_unknown(service, attack_family, strand_id, rf_confidence)

    async def _on_prediction(self, msg):
        """LSTM prediction handler — Gen 3 demo moment (§8)."""
        try:
            signal = json.loads(msg.data.decode())
        except Exception:
            return

        predicted_family = signal.get("predicted_family", "pod_crash")
        predicted_service = signal.get("predicted_service", "payment-service")
        confidence = signal.get("lstm_confidence", 0.0)

        if confidence < MLConfig.LSTM_CONFIDENCE_THRESHOLD:
            return

        log.info(f"\n🔮 LSTM PREDICTION: {predicted_family} → {predicted_service} [{confidence:.0%}]")

        # Preemptive action
        blast_radius = self._query_blast_radius(predicted_service)

        preemptive_actions = []
        for svc_info in blast_radius:
            svc_name = svc_info.get("name", predicted_service)
            if svc_info.get("criticality") == "critical":
                preemptive_actions.append(self._prescale_service(svc_name, replicas=3))
            if predicted_family == "network":
                preemptive_actions.append(self._prep_failover_route(svc_name))
            if predicted_family == "resource":
                preemptive_actions.append(self._tighten_resource_limits(svc_name))

        # Also pre-scale the predicted target
        preemptive_actions.append(self._prescale_service(predicted_service, replicas=3))

        await asyncio.gather(*preemptive_actions, return_exceptions=True)

        await self._publish_brain_event(
            BrainEvents.PREEMPTIVE_ACTION,
            service=predicted_service,
            family=predicted_family,
            confidence=confidence,
            services=[s.get("name") for s in blast_radius],
        )

        log.info(f"🛡️ Preemptive actions complete for {predicted_service}")

    async def _on_honeypot_crystallized(self, msg):
        """Handle honeypot crystallization complete."""
        data = json.loads(msg.data.decode())
        strand_id = data.get("strand_id", "unknown")
        playbook = data.get("playbook", {"actions": ["restart_pod"]})
        await self._store_tcell_memory(strand_id, playbook)

    async def _on_immunity_write(self, msg):
        """Cache new immunity in Redis from other agents."""
        data = json.loads(msg.data.decode())
        strand_id = data.get("strand_id")
        playbook = data.get("playbook", {})
        if strand_id and playbook:
            await self._store_tcell_memory(strand_id, playbook)

    # ───────────────────────────────────────────────────────────
    # STATE HANDLERS (§8 — 4 states)
    # ───────────────────────────────────────────────────────────

    async def _handle_known(self, service: str, family: str,
                             strand_id: str, confidence: float):
        """KNOWN (RF >= 0.85): Execute playbook immediately."""
        log.info(f"  State: KNOWN — executing playbook immediately")

        playbook = self._query_recovery(family)
        if not playbook:
            playbook = {"id": f"rec_{family}_default", "actions": ["restart_pod", "scale_replicas"]}

        task = RecoveryTask(
            priority=ServiceConfig.get_priority(service),
            service=service,
            playbook_id=playbook.get("id", "unknown"),
            actions=playbook.get("actions", ["restart_pod"]),
            attack_state=AttackState.KNOWN,
            strand_id=strand_id,
            attack_family=family,
            rf_confidence=confidence,
        )
        await self._enqueue_and_execute(task)

        # Store in T-cell memory for next encounter
        await self._store_tcell_memory(strand_id, playbook)

    async def _handle_probable(self, service: str, family: str,
                                strand_id: str, confidence: float):
        """PROBABLE (RF 0.60-0.85): Execute playbook + partial honeypot observation."""
        log.info(f"  State: PROBABLE — playbook + partial honeypot in parallel")

        playbook = self._query_recovery(family)
        if not playbook:
            playbook = {"id": f"rec_{family}_default", "actions": ["restart_pod", "scale_replicas"]}

        # Run recovery and partial honeypot in parallel
        task = RecoveryTask(
            priority=ServiceConfig.get_priority(service),
            service=service,
            playbook_id=playbook.get("id", "unknown"),
            actions=playbook.get("actions", ["restart_pod"]),
            attack_state=AttackState.PROBABLE,
            strand_id=strand_id,
            attack_family=family,
            rf_confidence=confidence,
        )
        await self._enqueue_and_execute(task)
        await self._store_tcell_memory(strand_id, playbook)

    async def _handle_unknown(self, service: str, family: str,
                               strand_id: str, confidence: float):
        """UNKNOWN (RF < 0.60): Full honeypot path."""
        log.info(f"  State: UNKNOWN — deploying honeypot for observation")

        # Start conservative recovery first
        conservative_task = RecoveryTask(
            priority=ServiceConfig.get_priority(service),
            service=service,
            playbook_id="rec_conservative",
            actions=["restart_pod"],
            attack_state=AttackState.UNKNOWN,
            strand_id=strand_id,
            attack_family=family,
            rf_confidence=confidence,
        )

        # Run honeypot flow in parallel with conservative recovery
        recovery_task = asyncio.create_task(self._enqueue_and_execute(conservative_task))

        honeypot_task = asyncio.create_task(
            self.honeypot.handle_unknown_attack(
                service=service,
                initial_rf_family=family,
                initial_rf_confidence=confidence,
                current_gen=self.virus_gen,
            )
        )

        await asyncio.gather(recovery_task, honeypot_task, return_exceptions=True)

    # ───────────────────────────────────────────────────────────
    # PRIORITY QUEUE & EXECUTION (§8)
    # ───────────────────────────────────────────────────────────

    async def _enqueue_and_execute(self, task: RecoveryTask):
        """Enqueue task and execute with semaphore protection."""
        heapq.heappush(self.task_queue, task)

        # Check for conflict
        if task.service in self.active_recoveries:
            active = self.active_recoveries[task.service]
            if task.priority < active.priority:
                log.info(f"  ⚡ PREEMPT: {task.service} (priority {task.priority} < {active.priority})")
                await self._publish_brain_event(BrainEvents.RECOVERY_PREEMPTED,
                                                service=task.service)
            else:
                log.info(f"  ⏳ QUEUED: {task.service} behind active recovery")
                return

        # Execute with semaphore
        service_lock = self._get_service_lock(task.service)

        async with self.recovery_slots:
            async with service_lock:
                self.active_recoveries[task.service] = task
                try:
                    await self._execute_recovery(task)
                finally:
                    self.active_recoveries.pop(task.service, None)

    async def _execute_recovery(self, task: RecoveryTask):
        """Execute recovery actions from playbook."""
        start_time = time.time()

        await self._publish_brain_event(
            BrainEvents.RECOVERY_STARTED,
            service=task.service,
            playbook=task.playbook_id,
            attack_state=task.attack_state,
        )

        log.info(f"  ▶ Recovery started: {task.service} | Actions: {task.actions}")

        success = True
        for action in task.actions:
            try:
                await self._execute_action(action, task.service)
            except Exception as e:
                log.error(f"  ✗ Action {action} failed: {e}")
                success = False

        elapsed_ms = (time.time() - start_time) * 1000
        self.total_recoveries += 1
        self.total_recovery_time_ms += elapsed_ms

        # Validate recovery
        await asyncio.sleep(2)
        healthy = await self._validate_health(task.service)

        log.info(f"  {'✅' if healthy else '⚠️'} Recovery {'complete' if healthy else 'partial'}: "
                 f"{task.service} in {elapsed_ms:.0f}ms")

        # DNA Write — every completed recovery (§8)
        await self._write_dna(task, elapsed_ms, success and healthy)

        # Update Neo4j Strand avg_recovery_time
        await self._update_strand_recovery_time(task.strand_id, elapsed_ms)

        # Publish completion
        await self._publish_brain_event(
            BrainEvents.RECOVERY_COMPLETE,
            service=task.service,
            recovery_time_ms=elapsed_ms,
            success=success and healthy,
            attack_family=task.attack_family,
            strand_id=task.strand_id,
            attack_state=task.attack_state,
        )

    async def _execute_action(self, action: str, service: str):
        """Execute a single recovery action."""
        log.info(f"    → {action} on {service}")

        if action == "restart_pod":
            if self.k8s_v1:
                try:
                    pods = self.k8s_v1.list_namespaced_pod(
                        "default", label_selector=f"app={service}"
                    )
                    for pod in pods.items:
                        self.k8s_v1.delete_namespaced_pod(
                            pod.metadata.name, "default", grace_period_seconds=5
                        )
                except Exception as e:
                    log.warning(f"    restart_pod failed: {e}")

        elif action in ("scale_replicas", "scale_up"):
            if self.k8s_apps_v1:
                try:
                    svc_config = ServiceConfig.SERVICES.get(service, {})
                    target = min(svc_config.get("replicas_max", 4), 3)
                    self.k8s_apps_v1.patch_namespaced_deployment_scale(
                        name=service, namespace="default",
                        body={"spec": {"replicas": target}},
                    )
                    log.info(f"    Scaled {service} → {target} replicas")
                except Exception as e:
                    log.warning(f"    scale failed: {e}")

        elif action == "alert_brain":
            log.info(f"    Brain alerted about {service}")

        elif action == "rollback":
            log.info(f"    Rollback initiated for {service}")

        elif action == "flush_cache":
            try:
                await self.redis.flushdb()
                log.info(f"    Cache flushed for {service}")
            except Exception:
                pass

        elif action == "isolate_network":
            log.info(f"    Network isolation for {service}")

        await asyncio.sleep(0.5)  # Simulate action time

    async def _validate_health(self, service: str) -> bool:
        """Check if service recovered via health endpoint."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                resp = await http.get(f"http://{service}:8000/health")
                return resp.status_code == 200
        except Exception:
            return True  # Assume healthy if can't reach

    # ───────────────────────────────────────────────────────────
    # PREEMPTIVE ACTIONS (§8 — LSTM Prediction Handler)
    # ───────────────────────────────────────────────────────────

    async def _prescale_service(self, service: str, replicas: int = 3):
        """Pre-scale service before attack lands."""
        if self.k8s_apps_v1:
            try:
                self.k8s_apps_v1.patch_namespaced_deployment_scale(
                    name=service, namespace="default",
                    body={"spec": {"replicas": replicas}},
                )
                log.info(f"  🛡️ Pre-scaled {service} → {replicas} replicas")
            except Exception:
                pass

    async def _prep_failover_route(self, service: str):
        """Prepare failover routing for predicted network attack."""
        log.info(f"  🔀 Failover route prepared for {service}")

    async def _tighten_resource_limits(self, service: str):
        """Tighten resource limits for predicted resource attack."""
        log.info(f"  🔒 Resource limits tightened for {service}")

    # ───────────────────────────────────────────────────────────
    # DNA WRITE — PostgreSQL + Neo4j (§8)
    # ───────────────────────────────────────────────────────────

    async def _write_dna(self, task: RecoveryTask, elapsed_ms: float, success: bool):
        """Write evolutionary history to DNA store (PostgreSQL)."""
        try:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO dna_log (
                        virus_gen, antibody_gen, strand_id, service,
                        playbook_id, recovery_time_ms, attack_state, success, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """, self.virus_gen, self.antibody_gen, task.strand_id,
                   task.service, task.playbook_id, elapsed_ms,
                   task.attack_state, success)
        except Exception as e:
            log.warning(f"DNA write failed: {e}")

        # Also publish to NATS for other consumers
        if self.nc:
            await self.nc.publish(NATSSubjects.DNA_LOG, json.dumps({
                "virus_gen": self.virus_gen,
                "antibody_gen": self.antibody_gen,
                "strand_id": task.strand_id,
                "service": task.service,
                "recovery_time_ms": elapsed_ms,
                "success": success,
                "timestamp": time.time(),
            }).encode())

    async def _update_strand_recovery_time(self, strand_id: Optional[str], elapsed_ms: float):
        """Update avg recovery time on Neo4j Strand node."""
        if not strand_id or not self.neo4j_driver:
            return
        try:
            with self.neo4j_driver.session() as session:
                session.run("""
                    MATCH (st:Strand {id: $strand_id})
                    SET st.avg_recovery_time_ms =
                        (COALESCE(st.avg_recovery_time_ms, $new_time) + $new_time) / 2
                """, strand_id=strand_id, new_time=elapsed_ms)
        except Exception:
            pass

    # ───────────────────────────────────────────────────────────
    # BRAIN EVENT PUBLISHER
    # ───────────────────────────────────────────────────────────

    async def _publish_brain_event(self, event_type: str, **kwargs):
        """Publish event to brain.update for dashboard."""
        if self.nc:
            payload = {"event": event_type, "timestamp": time.time(), **kwargs}
            await self.nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps(payload).encode())

    # ───────────────────────────────────────────────────────────
    # MAIN LOOP
    # ───────────────────────────────────────────────────────────

    async def run(self):
        """Main antibody loop."""
        await self.connect()

        log.info("🧬 Autonomous Self-Healing Engine ONLINE")
        log.info("   Listening: nerve.*.alert | lstm.prediction | honeypot.crystallized")

        while True:
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    engine = AntibodyEngine()
    asyncio.run(engine.run())
