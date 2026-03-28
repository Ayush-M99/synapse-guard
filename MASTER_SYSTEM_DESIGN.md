# Autonomous Chaos Engineering & Self-Healing Platform — Master Design Document

> **Context**: This document captures everything discussed for PS1 from Manipal Institute of Technology Bengaluru. The problem statement: *"Build an autonomous chaos engineering and self-healing platform that runs against a real locally-deployed microservice application on Kubernetes, detects failures using ML on live telemetry, and recovers without human intervention."*

---

## Table of Contents

1. [Problem Statement Full Text](#1-problem-statement-full-text)
2. [Core Concept — The Biological Framing](#2-core-concept--the-biological-framing)
3. [Full Tech Stack](#3-full-tech-stack)
4. [The 6 Microservices — The Patient](#4-the-6-microservices--the-patient)
5. [ML Pipeline](#5-ml-pipeline)
6. [Knowledge Graph Schema](#6-knowledge-graph-schema)
7. [Honeypot System](#7-honeypot-system)
8. [Antibody Decision Engine](#8-antibody-decision-engine)
9. [K8s Attack Implementation — Virus Agent](#9-k8s-attack-implementation--virus-agent)
10. [Istio Service Mesh](#10-istio-service-mesh)
11. [Demo Reliability Layer](#11-demo-reliability-layer)
12. [Dashboard](#12-dashboard)
13. [NATS Subject Map](#13-nats-subject-map)
14. [Hour-by-Hour Build Plan](#14-hour-by-hour-build-plan)
15. [Demo Script](#15-demo-script)
16. [Remaining Gaps Before Hackathon](#16-remaining-gaps-before-hackathon)
17. [Key Decisions Made](#17-key-decisions-made)

---

## 1. Problem Statement Full Text

Deploy a production-style microservices application on Kubernetes with at least five services communicating via HTTP/gRPC and backed by databases like PostgreSQL and Redis. The platform programmatically injects Kubernetes-native failures — pod crashes, resource pressure, network partitions, and latency — to simulate real outages. Telemetry from Prometheus and Loki feeds an ML-based anomaly detector (LSTM or Isolation Forest). When anomalies are detected, an autonomous decision engine triggers recovery actions via the Kubernetes API, including pod restarts, HPA scaling, traffic rerouting, and cache recovery. The system showcases a full closed loop — inject → detect → decide → recover — demonstrated through multiple live failure scenarios with a real-time dashboard displaying anomaly scores and recovery timelines.

---

## 2. Core Concept — The Biological Framing

The system is framed as an immune system. This framing is memorable, maps cleanly onto chaos engineering primitives, and gives a compelling demo arc.

```
Virus Agent       → chaos injector (attacks the system)
Antibody Agent    → recovery engine (heals the system)
DNA Store         → PostgreSQL (evolutionary history of every generation)
T-cell Memory     → Redis (O(1) lookup for known attack signatures)
Brain             → Neo4j knowledge graph (vulnerability relationships)
Nerve Endings     → lightweight Python sidecars on each pod
Neural Bus        → NATS (message passing between all components)
```

The closed loop is:
```
inject → detect → decide → recover → evolve → inject again (mutated)
```

The virus evolves across generations. When the antibody adapts too fast, the virus mutates to a harder strain. This evolutionary feedback loop is the core demo arc and what differentiates this from every other team.

---

## 3. Full Tech Stack

### Languages
- Python — virus agent, antibody agent, ML models, nerve endings, all backend services
- Go — NATS message consumers (fast, concurrent, lightweight)
- TypeScript/React — dashboard frontend
- Cypher — Neo4j knowledge graph queries

### Infrastructure
```
Kubernetes (minikube locally)   orchestrates everything
Docker                          containers for each service
Helm                            package manager for K8s deployments
NATS                            neural message bus (chosen over Kafka for this scale)
Istio (minimal profile)         service mesh for traffic splitting, latency injection, failover
```

### Observability Stack
```
Prometheus     scrapes metrics from every pod every 5 seconds
Loki           aggregates logs from all services
Jaeger         distributed tracing across service calls
```

**Decision made**: Prometheus feeds ML pipeline via direct HTTP poll (Option A) — ML pipeline queries Prometheus API every 5 seconds. Alertmanager path (Option B) was considered but rejected for hackathon — adds 3-4 hours setup, 4 failure points, and the latency difference is invisible to judges given the 15 second minimum detection window anyway.

### Databases
```
Neo4j          the brain — vulnerability knowledge graph
PostgreSQL     DNA store — evolutionary history of every generation
Redis          immunity memory cache — O(1) lookup for known strands
```

### ML Models
```
Isolation Forest    anomaly detection on Prometheus metrics (scikit-learn)
Random Forest       attack family classification (scikit-learn, replaces second LSTM)
LSTM                temporal prediction — predicts next attack from sequence history (PyTorch)
CUSUM               slow drift detection — catches camouflage attacks IF misses
```

### Hardware
- Laptop: 32GB RAM — sufficient to run everything inside minikube together, no need to split

---

## 4. The 6 Microservices — The Patient

A simple e-commerce application. These are the attack targets.

| Service | Language | DB | What it does |
|---|---|---|---|
| auth-service | FastAPI | PostgreSQL | JWT login/signup |
| api-gateway | FastAPI | — | Routes all external traffic |
| order-service | FastAPI | PostgreSQL | Creates/tracks orders |
| payment-service | FastAPI | PostgreSQL | Processes payments |
| inventory-service | FastAPI | Redis | Stock levels |
| notification-service | FastAPI | — | Sends alerts |

Each service must expose:
```python
@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/process")
async def process(request: Request):
    # Must do something CPU/memory intensive enough to show in Prometheus
    await asyncio.sleep(random.uniform(0.01, 0.05))
    return {"processed": True}
```

Services must be realistic enough that CPU stress and pod crash attacks register meaningfully in Prometheus telemetry. If services are too simple, IF detector fires on nothing.

---

## 5. ML Pipeline

### The Core Problem with Original Plan

The original plan had LSTM + Isolation Forest both doing anomaly detection — two detectors doing the same job. That is redundancy, not an ensemble. A real ensemble has each model doing a different job.

### The Three-Layer Ensemble

```
Layer 1: DETECT     is something wrong?         → CUSUM + Isolation Forest
Layer 2: CLASSIFY   what kind of attack?        → Random Forest
Layer 3: PREDICT    what will happen next?      → LSTM
```

### Layer 0 — CUSUM (Pre-filter, classical statistics)

Catches slow-burn camouflage attacks that Isolation Forest misses because each individual reading looks normal. 15 lines of code.

```python
def cusum(values, threshold=5, drift=0.5):
    s_pos, s_neg = 0, 0
    for v in values:
        s_pos = max(0, s_pos + v - drift)
        s_neg = max(0, s_neg - v - drift)
        if s_pos > threshold or s_neg > threshold:
            return True  # drift detected
    return False
```

Runs on a rolling window of each metric per service. Fires independently of IF.

### Layer 1 — Isolation Forest (Detection)

Fast, unsupervised, no labels needed. Runs every 5 seconds on this feature vector per service:

```python
features = [
    cpu_usage_pct,
    memory_usage_pct,
    http_error_rate_5xx,
    request_latency_p99,
    pod_restart_count_delta,
    network_rx_bytes_delta,
    network_tx_bytes_delta,
]
```

Outputs a continuous anomaly score 0→1. Threshold: score > 0.65, sustained for 3 consecutive scrapes (15 seconds minimum) before firing. This guard prevents false positives during demo.

### Layer 2 — Random Forest Classifier (Classification)

Replaced the second LSTM. Takes the anomaly signal and classifies which attack family it belongs to.

Reasons for RF over LSTM here:
- Training data is controlled (we inject the attacks ourselves, so we generate labeled samples)
- RF handles tabular features well, trains in seconds, is explainable to judges
- LSTM needs sequence history to warm up — not available at hackathon start

Feature vector for RF (same 7 metrics but windowed):
```python
features = [
    *current_metrics,           # same 7 features as IF
    *metrics_delta_30s,         # change over last 30 seconds
    *metrics_delta_60s,         # change over last 60 seconds
    service_dependency_affected # bool — are downstream services also anomalous?
]
```

Output: attack family label + confidence score. Feeds directly into Neo4j query.

### Layer 3 — LSTM (Prediction, not Detection)

Does something neither IF nor RF can do: temporal pattern recognition across the evolutionary timeline.

Input sequence:
```python
sequence = [
    (gen_1_attack_family, recovery_time, success),
    (gen_2_attack_family, recovery_time, success),
    (gen_2_retry_attack,  recovery_time, success),
    ...
]
```

Output: predicted next attack family + estimated time to impact.

This is what enables the antibody to pre-scale before the strike lands — the Gen 3 demo moment. Replaces the RL agent (PPO) from the original plan. More explainable to judges, no live training required.

Architecture: ~2 layers, lightweight PyTorch. Pre-trained on synthetic sequences generated from known attack order patterns.

### Ensemble Decision Logic

```
CUSUM fires (slow drift detected)
        OR
IF fires (anomaly score > 0.65, 3 sustained scrapes)
        ↓
RF Classifier runs → "network_partition, 91% confidence"
        ↓
LSTM checks sequence history → "timing attack incoming, 78% probability"
        ↓
Decision Engine:
    IF RF confidence >= 0.85  → execute known playbook immediately       (KNOWN)
    IF RF confidence 0.60-0.85 → execute playbook + partial honeypot     (PROBABLE)
    IF RF confidence < 0.60   → full honeypot path                       (UNKNOWN)
    IF LSTM prediction live   → pre-scale NOW before IF even triggers    (PREDICTED)
```

### Pre-Training Strategy

Cannot train on live data during the hackathon. Do this the night before:

1. Write a script that runs each attack strand 50 times against local cluster
2. Capture Prometheus metrics at T+0, T+5s, T+10s, T+30s per attack
3. Dump to labeled CSV (strand_id, family, all 7 features + deltas)
4. Train RF classifier — takes ~4 minutes
5. Serialize with joblib
6. Generate synthetic LSTM sequences from known attack order
7. Train LSTM offline, save weights
8. Load both at hackathon start

This script (generate_training_data.py) is the most urgent pre-hackathon task — it cannot be done during the event.

---

## 6. Knowledge Graph Schema

The brain of the entire system. Everything queries it. Designed before writing any attack code because everything else depends on it.

### 6 Node Types

#### AttackFamily
```cypher
(:AttackFamily {
    name: "pod_crash",      // pod_crash | network | resource | timing | cost
    generation: 1,          // which virus gen introduced this family
    danger_level: "high"    // low | medium | high | critical
})
```

#### Strand
```cypher
(:Strand {
    id: "pod_crash_A",
    description: "single pod OOMKill",
    generation: 1,
    mutation_of: null,          // parent strand id if this is a mutation
    camouflage: false,          // does it mimic normal traffic?
    timing_dependent: false,    // does it attack during recovery window?
    blast_radius: ["payment"],  // which services it directly hits
    avg_detection_time_ms: 2000,
    avg_recovery_time_ms: 18000
})
```

#### Signature
```cypher
(:Signature {
    id: "sig_001",
    feature_pattern: {
        cpu_delta: "low",
        memory_delta: "spike",
        error_rate_delta: "high",
        restart_count_delta: "high",
        latency_delta: "medium"
    },
    rf_label: "pod_crash",
    rf_confidence_threshold: 0.85
})
```

Feature magnitudes are bucketed: low / medium / high / spike.

#### Recovery
```cypher
(:Recovery {
    id: "rec_pod_crash_A",
    actions: ["restart_pod", "scale_replicas", "alert_brain"],
    priority_order: [1, 2, 3],
    estimated_time_ms: 8000,
    conflicts_with: ["rec_hpa_scale"],  // cannot run simultaneously
    requires_services: ["k8s_api"]
})
```

`conflicts_with` directly feeds the decision engine conflict resolution.

#### Service
```cypher
(:Service {
    name: "payment-service",
    criticality: "critical",    // critical | high | medium | low
    replicas_min: 2,
    replicas_max: 6,
    dependencies: ["postgres", "redis"],
    recovery_priority: 1        // lower = gets healed first
})
```

Criticality and recovery_priority mapping:
- payment-service: critical, priority 1
- auth-service: critical, priority 1
- api-gateway: high, priority 2
- order-service: high, priority 2
- inventory-service: medium, priority 3
- notification-service: low, priority 4

#### Generation
```cypher
(:Generation {
    virus_gen: 1,
    antibody_gen: 1,
    avg_recovery_time_ms: 18000,
    unknown_strand_rate: 0.0,
    resilience_score: 340,
    timestamp: datetime()
})
```

Snapshot node. Powers the evolutionary timeline chart. Written after each generation completes.

### 10 Relationship Types

```cypher
(Strand)-[:BELONGS_TO]      → (AttackFamily)
(Strand)-[:MUTATED_FROM]    → (Strand)           // evolution tracking
(Strand)-[:HAS_SIGNATURE]   → (Signature)
(Signature)-[:TRIGGERS]     → (Recovery)
(Strand)-[:COUNTERED_BY]    → (Recovery)
(Service)-[:DEPENDS_ON]     → (Service)           // blast radius traversal
(Service)-[:TARGETED_BY]    → (Strand)
(Recovery)-[:APPLIES_TO]    → (Service)
(Generation)-[:INTRODUCED]  → (Strand)
(Generation)-[:DEVELOPED]   → (Recovery)
(Strand)-[:DEFEATED_IN]     → (Generation)
```

### 3 Core Queries

**Query 1 — Fast lookup (RF confident)**
```cypher
MATCH (sig:Signature {rf_label: $label})
    -[:TRIGGERS]->(rec:Recovery)
RETURN rec.actions, rec.priority_order, rec.conflicts_with
ORDER BY rec.estimated_time_ms ASC
LIMIT 1
```

**Query 2 — Blast radius traversal**
```cypher
MATCH (s:Service {name: $attacked_service})
    -[:DEPENDS_ON*1..3]->(downstream:Service)
RETURN downstream.name, downstream.criticality,
       downstream.recovery_priority
ORDER BY downstream.recovery_priority ASC
```

**Query 3 — Evolutionary intelligence**
```cypher
MATCH (strand:Strand {id: $strand_id})
    -[:DEFEATED_IN]->(gen:Generation)
MATCH (gen)-[:DEVELOPED]->(rec:Recovery)
RETURN rec, gen.avg_recovery_time_ms, gen.virus_gen
ORDER BY gen.virus_gen DESC
LIMIT 1
```

### Seed Script

Pre-load all 18 strands before the hackathon. Run once.

```python
def seed_knowledge_graph(driver):
    with driver.session() as session:
        families = ["pod_crash", "network", "resource", "timing", "cost"]
        for f in families:
            session.run("MERGE (:AttackFamily {name: $name, generation: 1})", name=f)

        strands = [
            {"id": "pod_crash_A", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_B", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_C", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_D", "family": "pod_crash", "gen": 1},
            {"id": "network_A",   "family": "network",   "gen": 1},
            {"id": "network_B",   "family": "network",   "gen": 1},
            {"id": "network_C",   "family": "network",   "gen": 1},
            {"id": "network_D",   "family": "network",   "gen": 1},
            {"id": "resource_A",  "family": "resource",  "gen": 1},
            {"id": "resource_B",  "family": "resource",  "gen": 1},
            {"id": "resource_C",  "family": "resource",  "gen": 1},
            {"id": "resource_D",  "family": "resource",  "gen": 1},
            {"id": "timing_A",    "family": "timing",    "gen": 2},
            {"id": "timing_B",    "family": "timing",    "gen": 2},
            {"id": "timing_C",    "family": "timing",    "gen": 2},
            {"id": "cost_A",      "family": "cost",      "gen": 1},
            {"id": "cost_B",      "family": "cost",      "gen": 1},
            {"id": "camouflage_A","family": "resource",  "gen": 3},
        ]
        for s in strands:
            session.run("""
                MERGE (st:Strand {id: $id})
                SET st += $props
                WITH st
                MATCH (f:AttackFamily {name: $family})
                MERGE (st)-[:BELONGS_TO]->(f)
            """, id=s["id"], props=s, family=s["family"])
```

---

## 7. Honeypot System

### Decision Made

When RF confidence < 0.60 (unknown attack), deploy a honeypot. Chosen over conservative-recovery-only because:
- Creates the "unknown strand discovery" demo moment
- New node animates onto brain map in real time — judges lean forward
- More defensible to judges — system learns, not just reacts

### What the Honeypot Is

Not a fake server in the traditional security sense. A **sacrificial replica pod** that gets spun up specifically to let the unknown attack exhaust itself against something disposable, while the observation layer fingerprints exactly what it's doing.

### Full Flow

```
Unknown attack detected (RF < 0.60)
            ↓
Spin up honeypot pod (copy of targeted service)
Redirect 20% of attack traffic to honeypot via Istio VirtualService weight
            ↓
Two things happen simultaneously:
  → Conservative recovery runs on real service (buys time)
  → Observation layer watches honeypot metrics for 10 seconds (5 snapshots, 2s each)
            ↓
HoneypotObserver builds signature from 5 snapshots
RF classifier runs again on richer honeypot signature
            ↓
New Strand node created in Neo4j
New Signature node linked to Strand
Strand linked to best-guess AttackFamily
Strand linked to Recovery that worked
            ↓
NATS publishes brain.update → new_strand_discovered
Dashboard brain map animates new purple node
Honeypot pod terminated (grace_period=0)
Signature stored in Redis immunity memory
```

### Honeypot Pod Spec

```python
def deploy_honeypot(targeted_service: str, namespace: str = "default"):
    honeypot_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"honeypot-{targeted_service}-{int(time.time())}",
            "namespace": namespace,
            "labels": {
                "role": "honeypot",
                "observing": targeted_service,
                "app": targeted_service        # same label — receives attack traffic
            }
        },
        "spec": {
            "containers": [{
                "name": "honeypot",
                "image": f"your-registry/{targeted_service}:latest",
                "resources": {
                    "requests": {"cpu": "50m",  "memory": "64Mi"},
                    "limits":   {"cpu": "100m", "memory": "128Mi"}
                },
                "env": [{"name": "HONEYPOT_MODE", "value": "true"}]
            }],
            "terminationGracePeriodSeconds": 0
        }
    }
    k8s_client.create_namespaced_pod(namespace, honeypot_manifest)
```

### HoneypotObserver

```python
class HoneypotObserver:
    def __init__(self, honeypot_pod: str, targeted_service: str):
        self.pod = honeypot_pod
        self.service = targeted_service
        self.observations = []
        self.sample_interval = 2
        self.observation_window = 10

    async def observe(self) -> dict:
        for tick in range(self.observation_window // self.sample_interval):
            snapshot = await self._capture_metrics_snapshot()
            self.observations.append(snapshot)
            await asyncio.sleep(self.sample_interval)
        return self._build_signature()

    def _build_signature(self) -> dict:
        return {
            "cpu_delta":        self._classify_magnitude("cpu_delta"),
            "memory_delta":     self._classify_magnitude("memory_delta"),
            "error_rate_delta": self._classify_magnitude("error_rate_delta"),
            "restart_delta":    self._classify_magnitude("restart_count_delta"),
            "latency_delta":    self._classify_magnitude("latency_delta"),
            "pattern":          self._detect_pattern(),
            "affected_services": self._check_blast_radius()
        }

    def _classify_magnitude(self, metric: str) -> str:
        values = [o[metric] for o in self.observations]
        avg = sum(values) / len(values)
        if avg < 0.2:  return "low"
        if avg < 0.6:  return "medium"
        if avg < 0.85: return "high"
        return "spike"

    def _detect_pattern(self) -> str:
        cpu_values = [o["cpu_delta"] for o in self.observations]
        if max(cpu_values) - min(cpu_values) > 0.7: return "spike"
        if cpu_values[-1] > cpu_values[0] + 0.3:   return "gradual"
        return "oscillating"
```

### Crystallize New Strand to Neo4j

```python
async def crystallize_new_strand(signature, recovery_used, recovery_time_ms, honeypot_pod):
    family_guess, confidence = rf_classifier.predict(signature)
    strand_id = f"unknown_{int(time.time())}"

    with neo4j_driver.session() as session:
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
            CREATE (sig:Signature $signature_props)
            CREATE (st)-[:HAS_SIGNATURE]->(sig)
            WITH st
            MATCH (rec:Recovery {id: $recovery_id})
            CREATE (st)-[:COUNTERED_BY]->(rec)
        """,
            strand_id=strand_id,
            current_gen=virus_gen_tracker.current,
            is_camouflage=signature["pattern"] == "gradual",
            recovery_time=recovery_time_ms,
            family=family_guess,
            signature_props=signature,
            recovery_id=recovery_used
        )

    await nats_client.publish("brain.update", {
        "event": "new_strand_discovered",
        "strand_id": strand_id,
        "family": family_guess,
        "confidence": confidence
    })

    k8s_client.delete_namespaced_pod(honeypot_pod, "default")
    return strand_id
```

---

## 8. Antibody Decision Engine

The central nervous system. Connects ML pipeline output to K8s recovery actions.

### 4 Input States

```
KNOWN       RF >= 0.85              execute playbook immediately
PROBABLE    RF 0.60 - 0.85          execute playbook + partial honeypot observation in parallel
UNKNOWN     RF < 0.60               full honeypot path (10s observation, crystallize new strand)
PREDICTED   LSTM fires prediction   preemptive action before IF even triggers
```

### Single Intake Method

Everything enters through one NATS subscriber on `nerve.{service}.alert`. Signal type field routes to the right state. No spaghetti.

### Priority Queue — OS Scheduling Analogy

Min-heap of RecoveryTask objects. Lower number = runs first.

```python
@dataclass(order=True)
class RecoveryTask:
    priority:     int              # lower = runs first
    service:      str = field(compare=False)
    playbook_id:  str = field(compare=False)
    attack_state: AttackState = field(compare=False)
    strand_id:    Optional[str] = field(compare=False, default=None)
    created_at:   float = field(compare=False, default=0.0)

# Priority mapping
CRITICAL  = 1   # payment-service, auth-service
HIGH      = 2   # api-gateway, order-service
MEDIUM    = 3   # inventory-service
LOW       = 4   # notification-service
```

### Semaphore System — Two Levels

```python
# Global slot limiter — max 3 concurrent recoveries across entire system
self.recovery_slots = asyncio.Semaphore(3)

# Per-service lock — prevents two recoveries on same service simultaneously
self.service_locks: dict[str, asyncio.Semaphore] = {}
# One Semaphore(1) per service, created lazily
```

OS analogy for judges: global slots = CPU cores, per-service locks = mutex protecting shared resource.

### Conflict Resolution — 3 Strategies

Conflict detection checks two conditions:
1. Same service already being recovered
2. Incoming playbook is listed in active playbook's `conflicts_with` field (from Neo4j Recovery node)

Resolution strategies:
- Incoming priority higher than active → **preempt**: pause existing, re-queue both, publish `recovery_preempted` event to dashboard
- Same priority → **merge**: run non-conflicting actions together; queue behind if merge impossible
- Incoming priority lower → **queue normally**: existing finishes first

### LSTM Prediction Handler — Gen 3 Demo Moment

Fires independently of IF/CUSUM. If LSTM confidence >= 0.70, immediately runs preemptive actions against predicted blast radius before attack lands.

```python
async def _handle_prediction(self, signal: dict):
    predicted_family  = signal["predicted_family"]
    predicted_service = signal["predicted_service"]
    confidence        = signal["lstm_confidence"]

    if confidence < 0.70:
        self.pending_predictions[predicted_service] = signal
        return

    blast_radius = await self._get_blast_radius(predicted_service, predicted_family)

    preemptive_actions = []
    for service in blast_radius:
        if service["criticality"] == "critical":
            preemptive_actions.append(self._prescale_service(service["name"], replicas=3))
        if predicted_family == "network":
            preemptive_actions.append(self._prep_failover_route(service["name"]))
        if predicted_family == "resource":
            preemptive_actions.append(self._tighten_resource_limits(service["name"]))

    await asyncio.gather(*preemptive_actions)

    await self.nats.publish("brain.update", {
        "event":      "preemptive_action",
        "family":     predicted_family,
        "services":   [s["name"] for s in blast_radius],
        "confidence": confidence
    })
```

Dashboard shows orange "PREDICTED" alert. Services pre-scale before IF triggers. Recovery time effectively zero.

### Recovery Executor

Iterates through playbook actions sequentially. Individual action failure does not crash the recovery — escalates to next action and continues. After all actions run, validates recovery via health check. If validation fails, escalates to next playbook variant.

### DNA Write — Every Completed Recovery

```python
async def _write_to_dna(self, task: RecoveryTask, elapsed_ms: float):
    # PostgreSQL
    await db.execute("""
        INSERT INTO dna_log (
            virus_gen, antibody_gen, strand_id, service,
            playbook_id, recovery_time_ms, attack_state, success, timestamp
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    """, ...)

    # Update avg recovery time on Neo4j Strand node
    with self.neo4j.session() as session:
        session.run("""
            MATCH (st:Strand {id: $strand_id})
            SET st.avg_recovery_time_ms =
                (st.avg_recovery_time_ms + $new_time) / 2
        """, strand_id=task.strand_id, new_time=elapsed_ms)
```

### Redis T-Cell Memory Check

Before any graph traversal, antibody checks Redis:

```python
cached = redis.get(f"immunity:{anomaly_signal.strand_id}")
if cached:
    execute_recovery(cached.playbook, speed="reflex")
    return
# Only if cache miss → do Neo4j graph traversal
```

This is the T-cell memory hit — second encounter with same strand resolves in ~2 seconds instead of 18 seconds.

### 3 Demo Moments Fully Wired

1. **Simultaneous failure** — trigger payment + order crash simultaneously, watch priority queue put payment first, conflict resolution visible on dashboard
2. **Preemptive action** — LSTM fires, dashboard shows orange "PREDICTED", services pre-scale before IF triggers, recovery time ~0
3. **Unknown strand** — honeypot spins up, 10s observation, new purple node animates onto brain map, next encounter resolves in 2s

---

## 9. K8s Attack Implementation — Virus Agent

### Virus Agent Is Three Things

```
1. Attack Library       → the actual chaos injection functions
2. Virus Brain          → decides what to inject, when, how to mutate
3. Generation Tracker   → knows when antibody has adapted, triggers mutation
```

### Mutation Trigger Logic

```python
MUTATION_TRIGGERS = {
    "avg_recovery_time_ms < 3000": "escalate_same_family",
    "avg_recovery_time_ms < 1000": "switch_family",
    "honeypot_deployed == True":   "camouflage_mode",
    "preemptive_action == True":   "timing_attack",
    "unknown_strand_rate == 0.0":  "combo_attack"
}
```

Virus reads DNA store (PostgreSQL) continuously. When antibody recovers too fast → virus mutates.

### Complete Attack Library — 18 Strands, 5 Families

#### Family 1 — Pod Crash (Gen 1, 4 strands)

- **pod_crash_A**: Single OOMKill on payment-service. Uses `k8s_client.delete_namespaced_pod(grace_period_seconds=0)`
- **pod_crash_B**: Cascade — kill payment then downstream order-service after 3 second delay
- **pod_crash_C**: Kill under load — generate 500 rps traffic for 10s, kill at peak (race condition)
- **pod_crash_D**: Kill + corrupt ConfigMap (set DB_HOST to invalid value) — data corruption variant

All use `kubernetes` Python SDK `delete_namespaced_pod`.

#### Family 2 — Network Attacks (Gen 1, 4 strands)

Implemented via Istio VirtualService objects. Replaces tc netem privileged pods from original plan.

- **network_A**: Inject 2000ms fixed latency on all traffic to payment-service via Istio fault injection
- **network_B**: Inject packet loss 30% + latency 500ms (combined VirtualService fault)
- **network_C**: DNS poisoning simulation — extreme latency on service discovery
- **network_D**: Network partition — isolate payment + inventory from each other (block all ingress/egress)

```python
async def network_latency_A(service: str, istio_client: IstioClient):
    await istio_client.inject_latency(service, delay_ms=2000)
    return {"strand": "network_A", "service": service}

async def network_partition_D(services: list, istio_client: IstioClient):
    for service in services:
        await istio_client.inject_latency(service, delay_ms=99999)
    return {"strand": "network_D", "partitioned": services}
```

Cleanup always paired with attack:
```python
async def cleanup_network_attack(service: str, istio_client: IstioClient):
    await istio_client.remove_chaos(service)
```

#### Family 3 — Resource Pressure (Gen 1, 4 strands)

- **resource_A**: Deploy stress pod on same node as target service. Uses `polinux/stress` image, `--cpu 2 --timeout 60s`
- **resource_B**: Memory leak simulation — `--vm 1 --vm-bytes 50M --vm-hang 0`
- **resource_C**: Disk fill — fill to 95% capacity
- **resource_D**: Combo — CPU stress + memory leak + file descriptor exhaustion simultaneously

#### Family 4 — Timing Attacks (Gen 2, 3 strands)

Virus watches antibody recovery state via NATS subscription. Attacks at most vulnerable moment.

- **timing_A**: Wait for 50% recovery (health score 0.4-0.6), strike during recovery window
- **timing_B**: Watch which failover route antibody uses → attack the failover target instead
- **timing_C**: Slow burn variant — detect recovery window probe, attack the monitoring service first

```python
class TimingAttackAgent:
    async def watch_and_strike(self, service: str, k8s_client):
        async def on_recovery_event(msg):
            event = json.loads(msg.data)
            if event["event"] != "recovery_started": return
            if event["service"] != service: return
            await self._wait_for_recovery_midpoint(service)
            await pod_crash_A(service, k8s_client)

        await self.nats.subscribe("brain.update", on_recovery_event)

    async def _wait_for_recovery_midpoint(self, service: str):
        while True:
            health_score = await self._get_health_score(service)
            if 0.4 <= health_score <= 0.6:
                return
            await asyncio.sleep(1)
```

#### Family 5 — Camouflage Attacks (Gen 3, 3 strands)

Hardest to detect. Individual readings stay below IF threshold. Only CUSUM catches these.

- **camouflage_A**: Slow burn — degrade performance 2% every 5 minutes by patching CPU limits down. Stays under IF threshold each step.
- **camouflage_B**: Gradually increase latency from 100ms to 3000ms over 10 minutes via Istio
- **camouflage_C**: Attack monitoring service first to blind antibody, then attack real target

```python
async def slow_burn_A(service: str, k8s_client, prometheus_client):
    degradation_pct = 0.02
    interval_seconds = 300
    current_cpu_limit = 1000  # millicores

    while True:
        current_cpu_limit = int(current_cpu_limit * (1 - degradation_pct))
        patch = {"spec": {"containers": [{"name": service,
            "resources": {"limits": {"cpu": f"{current_cpu_limit}m"}}}]}}
        k8s_client.patch_namespaced_pod(name=pod_name, namespace="default", body=patch)

        caught = await prometheus_client.query(
            f'anomaly_cusum_triggered{{service="{service}"}}'
        )
        if caught: break
        await asyncio.sleep(interval_seconds)
```

### Virus Brain — Generation Controller

```python
class VirusBrain:
    def _build_gen1_sequence(self) -> list:
        return [
            {"strand": "pod_crash_A", "target": "payment-service"},
            {"strand": "network_A",   "target": "api-gateway"},
            {"strand": "resource_A",  "target": "auth-service"},
            {"strand": "pod_crash_B", "target": "order-service"},
        ]

    def _build_gen2_sequence(self) -> list:
        return [
            {"strand": "timing_A",  "target": "payment-service"},
            {"strand": "timing_B",  "target": "order-service"},
            {"strand": "network_D", "targets": ["payment-service", "inventory-service"]},
        ]

    def _build_gen3_sequence(self) -> list:
        return [
            {"strand": "camouflage_A", "target": "auth-service"},
            {"strand": "timing_A",     "target": "payment-service"},
            {"strand": "pod_crash_A",  "target": "notification-service"},
        ]

    async def _observe_and_decide(self):
        recent = await self.db.fetch("""
            SELECT AVG(recovery_time_ms) FROM dna_log
            WHERE virus_gen = $1
            AND timestamp > NOW() - INTERVAL '10 minutes'
        """, self.gen)

        avg_recovery = recent["avg"]
        if avg_recovery < 3000: await self._mutate("escalate_same_family")
        elif avg_recovery < 1000: await self._mutate("switch_family")
```

### Chaos Schedule YAML — Demo Reliability

```yaml
scenarios:

  demo_scenario_1:
    name: "Gen 1 → Immunity Acquired"
    steps:
      - t: 0s
        inject: pod_crash_A
        target: payment-service
      - t: 20s
        inject: pod_crash_A
        target: payment-service
        expect: fast_recovery    # T-cell memory hit — should be <2s

  demo_scenario_2:
    name: "Gen 2 Timing Attack → Antibody Adapts"
    steps:
      - t: 0s
        inject: pod_crash_A
        target: payment-service
      - t: 8s
        inject: timing_A
        target: payment-service
        expect: preemptive_block

  demo_scenario_3:
    name: "Unknown Strand → Honeypot Discovery"
    steps:
      - t: 0s
        inject: camouflage_A
        target: auth-service
        expect: honeypot_deployed
      - t: 15s
        expect: new_node_on_brain_map
      - t: 30s
        inject: camouflage_A
        target: auth-service
        expect: fast_recovery
```

---

## 10. Istio Service Mesh

### Decision Made

Use Istio. It handles:
1. Traffic splitting to honeypot (80/20 VirtualService weights)
2. Traffic rerouting during recovery (DestinationRule failover)
3. Latency injection — **replaces tc netem privileged pods entirely**
4. Circuit breaking (DestinationRule outlier detection)

### Setup on minikube

```bash
minikube addons enable ingress
minikube addons enable metrics-server

curl -L https://istio.io/downloadIstio | sh -
cd istio-1.x.x
export PATH=$PWD/bin:$PATH

istioctl install --set profile=minimal -y

# Enable auto sidecar injection for default namespace
kubectl label namespace default istio-injection=enabled
```

Minimal profile gives: istiod (control plane) + istio-proxy (sidecar) + istio-ingressgateway. That's all that's needed.

### IstioClient — Python Runtime Interface

```python
class IstioClient:

    async def split_traffic_to_honeypot(self, service: str, honeypot_weight: int = 20):
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"{service}-honeypot-split"},
            "spec": {
                "hosts": [service],
                "http": [{"route": [
                    {"destination": {"host": service, "subset": "real"},
                     "weight": 100 - honeypot_weight},
                    {"destination": {"host": service, "subset": "honeypot"},
                     "weight": honeypot_weight}
                ]}]
            }
        }
        await self._kubectl_apply(vs_manifest)

    async def inject_latency(self, service: str, delay_ms: int):
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"chaos-latency-{service}"},
            "spec": {
                "hosts": [service],
                "http": [{"fault": {"delay": {
                    "percentage": {"value": 100},
                    "fixedDelay": f"{delay_ms}ms"
                }}, "route": [{"destination": {"host": service}}]}]
            }
        }
        await self._kubectl_apply(vs_manifest)

    async def remove_chaos(self, service: str):
        subprocess.run(["kubectl", "delete", "virtualservice",
                        f"chaos-latency-{service}", "--ignore-not-found"])
        subprocess.run(["kubectl", "delete", "virtualservice",
                        f"{service}-honeypot-split", "--ignore-not-found"])

    async def _kubectl_apply(self, manifest: dict):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(manifest, f)
        subprocess.run(["kubectl", "apply", "-f", f.name])
```

---

## 11. Demo Reliability Layer

### Three System Modes

```python
class SystemMode(Enum):
    LIVE     = "live"      # everything real — development
    DEMO     = "demo"      # scripted scenarios, real K8s but controlled
    FALLBACK = "fallback"  # pure simulation, no K8s needed
```

Fallback is the nuclear option. If K8s dies 30 minutes before judging, fallback mode runs the entire demo on simulated data. Dashboard looks identical.

### Pre-Demo Validator

Run 30 minutes before judging. Checks all 9 components. Auto-reseeds knowledge graph if < 18 strands found. Activates fallbacks for failed components automatically.

Components checked:
```
minikube, neo4j, redis, postgres, nats, prometheus,
all 6 services healthy, ml models loaded, knowledge graph seeded
```

### Fallback Simulator

Generates realistic-looking NATS events without any real infrastructure. Dashboard cannot distinguish from live events. Covers all 3 demo scenarios with pre-baked recovery times:

```python
self.recovery_times = {1: 18000, 2: 8000, 3: 1800}  # gen 1 → gen 2 → gen 3
```

### One-Command Startup

```bash
#!/bin/bash
# start.sh
minikube status || minikube start --memory=8192 --cpus=4
kubectl apply -f k8s/
kubectl wait --for=condition=ready pod --all --timeout=120s
docker-compose up -d neo4j redis postgres nats prometheus
python seed_graph.py
python virus_agent.py &
python antibody_agent.py &
python ml_pipeline.py &
cd dashboard && npm start &
echo "✅ System ready. Run demo: python demo.py full"
```

### Demo Runner

```bash
python demo.py 1      # Gen 1 → immunity
python demo.py 2      # Timing attack → preemptive
python demo.py 3      # Unknown strand → honeypot
python demo.py full   # All three back to back (5 minute demo slot)
```

---

## 12. Dashboard

### Tech Stack

```
React + TypeScript   component framework
D3-force            brain map (force-directed graph)
Recharts            evolutionary timeline + resilience score chart
Socket.io           WebSocket connection to NATS bridge
Tailwind            styling
Framer Motion       node animations on brain map
```

### Layout — 5 Panels

```
┌─────────────────────────┬──────────────────────┐
│                         │  LIVE BATTLE FEED    │
│      BRAIN MAP          │  Virus Gen: 2        │
│   (D3 force graph)      │  Antibody Gen: 3     │
│                         │  Current: timing_A   │
│                         │  Recovery: 8.2s      │
├─────────────────────────┼──────────────────────┤
│  EVOLUTIONARY TIMELINE  │   DNA REPLAY         │
│  (recovery time chart)  │   (gen selector)     │
├─────────────────────────┴──────────────────────┤
│     RESILIENCE SCORE: 847   |  0 HUMAN INTERVENTIONS   │
└─────────────────────────────────────────────────┘
```

Note: "0 human interventions" banner explicitly addresses the PS requirement of recovery without human intervention. Judges tick that box immediately.

### Panel 1 — Brain Map (D3-force)

Node colors:
```typescript
const NODE_COLORS = {
    healthy:    "#22c55e",  // green
    attacked:   "#ef4444",  // red
    healing:    "#f59e0b",  // amber — pulsing animation
    preemptive: "#f97316",  // orange — LSTM predicted, before attack lands
    discovered: "#a855f7",  // purple — new honeypot strand discovered
}
```

Animation sequence: green → red → amber (pulsing) → green

New unknown strand node: appears with purple, fades to family color after crystallized.

LSTM prediction: targeted service turns orange BEFORE attack lands (the Gen 3 moment).

### Panel 2 — Live Battle Feed

Rolling log with event icons:
```
🦠  Virus injected pod_crash_A → payment-service
🔍  IF detected anomaly (score: 0.87)
🧠  RF classified: pod_crash [94% confidence]
💉  Recovery started: rec_pod_crash_A
✅  Recovery complete: 18.2s
🧬  T-cell memory stored: pod_crash_A
⚡  T-cell hit: recovery in 1.8s (second encounter)
🔮  LSTM predicted: timing_A incoming [78% confidence]
🛡️  Preemptive scaling: payment-service → 3 replicas
```

### Panel 3 — Evolutionary Timeline (Recharts)

Two lines on same chart:
- Line 1: avg recovery time ms per generation (slopes DOWN — proof system learns)
- Line 2: unknown strand rate per generation (also slopes DOWN)

Pre-baked values for demo:
```typescript
const data = [
    {gen: 1, recovery_ms: 18000, unknown_rate: 0.0},
    {gen: 2, recovery_ms: 8200,  unknown_rate: 0.15},
    {gen: 3, recovery_ms: 1800,  unknown_rate: 0.0},
]
```

### Panel 4 — DNA Replay

Dropdown to select any past generation. Play button replays that generation's events on the brain map as ghost animation. Reads from PostgreSQL dna_log table ordered by relative_timestamp_ms.

```typescript
async function replayGeneration(gen: number) {
    const events = await fetch(`/api/dna/replay/${gen}`)
    for (const event of events) {
        await sleep(event.relative_timestamp_ms)
        updateBrainMap(event)
        updateBattleFeed(event)
    }
}
```

### Panel 5 — Resilience Score

Big animated number, 0-1000. Recalculated every 30 seconds. Counts up visually (satisfying to watch).

```typescript
function calculateResilienceScore(metrics: SystemMetrics): number {
    const recovery_score = normalize(metrics.avg_recovery_ms, 0, 20000) * 400
    const unknown_score  = (1 - metrics.unknown_strand_rate) * 200
    const fp_score       = (1 - metrics.false_positive_rate) * 200
    const blast_score    = (1 - metrics.avg_blast_radius / 6) * 200
    return Math.round(recovery_score + unknown_score + fp_score + blast_score)
}
// Gen 1: ~340 | Gen 2: ~580 | Gen 3: ~847
```

### WebSocket Bridge — NATS to Dashboard

```python
# ws_bridge.py
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

async def nats_to_ws():
    nc = await nats.connect("nats://localhost:4222")
    async def forward(msg):
        event = json.loads(msg.data)
        for client in connected_clients:
            await client.send_json(event)
    await nc.subscribe("brain.update", cb=forward)
    await nc.subscribe("services.health", cb=forward)
```

---

## 13. NATS Subject Map

Complete subject hierarchy. Final version.

```
NERVE ENDINGS PUBLISH:
  nerve.{service}.metrics         → ML pipeline (Prometheus poll replaces this in Option A)
  nerve.{service}.alert           → Decision Engine intake

DECISION ENGINE LISTENS:
  nerve.{service}.alert
  lstm.prediction
  honeypot.crystallized

DECISION ENGINE PUBLISHES:
  brain.update                    → Dashboard WebSocket bridge
  recovery.{service}.started      → K8s executor
  dna.log                         → PostgreSQL writer
  immunity.write                  → Redis cache writer

VIRUS AGENT PUBLISHES:
  virus.inject                    → Dashboard (shows what's being injected)
  virus.generation.event          → Virus mutation events

BRAIN UPDATE EVENT TYPES:
  attack_detected
  recovery_started
  recovery_complete
  recovery_preempted
  preemptive_action
  new_strand_discovered
  honeypot_deployed
  honeypot_observing
  mutation
```

---

## 14. Hour-by-Hour Build Plan

Assumes 3-4 people working in parallel.

```
Hours  0-4    minikube setup + 6 microservices deployed + Prometheus scraping all
Hours  4-8    Knowledge graph seeded + Virus agent Gen 1 working + attacks verified
Hours  8-12   ML pipeline (IF + RF + CUSUM) + nerve endings + antibody basic recovery
Hours 12-16   Decision engine + honeypot path + Istio configured
Hours 16-20   LSTM + Redis immunity memory + Gen 2 virus mutations (timing attacks)
Hours 20-26   Dashboard (brain map + timeline + battle feed) — NOTE: dashboard moved later
Hours 26-30   DNA replay + resilience score + Gen 3 virus (camouflage)
Hours 30-34   Demo reliability layer + chaos schedule YAML + fallback simulator
Hours 34-36   Rehearsal + bug fixes ONLY — no new features
```

### If Scope Needs Trimming (smaller team)

```
Cut first:    Camouflage attacks Gen 3 slow burn — complex, low demo value
Cut second:   DNA replay feature — impressive but not core to PS
Cut third:    LSTM prediction layer — replace with rule-based pre-scaling
Never cut:    Honeypot path — this is the differentiator
Never cut:    Evolutionary timeline — proves the system works
Never cut:    Brain map — this is what judges photograph
```

---

## 15. Demo Script

3-minute version. Judges will remember this.

```
00:00  Resilience score at 0. Brain map shows all green nodes.
       "0 human interventions" banner visible.

00:15  "Release Gen 1 virus"
       payment-service node turns red
       Cascade to order-service (turns orange)
       Battle feed: 🦠 pod_crash_A injected

00:30  Antibody kicks in
       Nodes turn amber (healing, pulsing)
       Battle feed: 💉 Recovery started
       Recovery time counter running

00:48  Nodes turn green. Recovery time: 18.2s
       Battle feed: 🧬 T-cell memory stored
       Resilience score climbs to ~340

01:00  "Gen 1 immunity acquired"
       Release Gen 1 again — same attack, same target
       Battle feed: ⚡ T-cell hit
       Recovery time: 1.8s
       Judges visibly react

01:20  "Virus mutates to Gen 2"
       Timing attack — hits during recovery window
       Battle feed: 🔮 LSTM predicted timing_A [78% confidence]
       payment-service turns ORANGE (preemptive — before attack lands)
       Antibody pre-scales to 3 replicas

01:35  Attack lands — service already scaled
       Recovery time: near zero
       Resilience score: ~580

02:00  "Unknown strand — Gen 3 camouflage"
       RF confidence: 43% — too low to classify
       Battle feed: 🍯 Honeypot deployed
       10 second observation bar appears on dashboard

02:15  New purple node ANIMATES onto brain map — "DISCOVERED: unknown_17430xxxxx"
       Judges lean forward
       Battle feed: new strand crystallized → resource family, 71% confidence

02:30  Release same camouflage attack again
       This time: 2.1s recovery (T-cell hit)
       Resilience score: ~847

02:50  Show evolutionary timeline — recovery slope: 18s → 8s → 1.8s → 2.1s
       Show DNA replay — gen 1 ghost animation replays on brain map

03:00  Final resilience score: 847/1000
       "0 human interventions"
       Done.
```

---

## 16. Remaining Gaps Before Hackathon

Things not yet fully designed that must be addressed before the event:

### 1. RF Training Data Generation Script (MOST URGENT)

Cannot be done during hackathon. Must be done night before. Script runs each of 18 strands 50 times, captures Prometheus metrics at T+0, T+5s, T+10s, T+30s, dumps to labeled CSV, trains RF, serializes with joblib. Synthetic LSTM sequences also generated and trained offline.

### 2. The 6 Microservices Design

Need `/health`, `/metrics`, and a `/process` endpoint with realistic enough load to show in Prometheus. Services too simple = IF fires on nothing.

### 3. Prometheus Scrape Config

Must be configured to know about all 6 services. Standard `prometheus.yml` with scrape configs per service.

### 4. Docker Compose File

For Neo4j, Redis, PostgreSQL, NATS running outside minikube or alongside it. Needed for `start.sh`.

### 5. K8s Manifests

Deployment + Service YAML for each of the 6 microservices. Standard boilerplate but needs to exist before event.

### 6. NATS Subject Map

Finalized above in section 13. Needs to be a single shared constants file imported by all agents.

Items 3-6 are mechanical — roughly 3 hours total. Item 1 is the only genuine pre-hackathon blocker.

---

## 17. Key Decisions Made

| Decision | Choice | Reason |
|---|---|---|
| Second ML model | Random Forest (not LSTM) | Controlled labeled training data, explainable, trains in seconds |
| Slow drift detection | CUSUM added | IF misses gradual camouflage attacks |
| Prometheus ingestion | Option A — direct HTTP poll | Option B (Alertmanager) adds 3-4 hours setup, 4 failure points, invisible latency difference |
| Network attack implementation | Istio VirtualService | Replaces tc netem privileged pods entirely — cleaner, no privileged containers |
| RL agent (PPO) | Replaced by LSTM prediction | No live training needed, more explainable to judges |
| Unknown attack path | Honeypot (not conservative-only) | Creates "new strand discovered" demo moment, judges lean forward |
| Traffic splitting | Istio 80/20 VirtualService weight | Required for honeypot partial observation |
| Memory | 32GB RAM — sufficient | Everything runs inside minikube together, no split needed |
| Istio profile | Minimal | istiod + istio-proxy + ingressgateway only — everything needed, nothing extra |

---

*This document reflects everything designed and decided in the planning session. Every architectural choice, every code pattern, every demo moment, every remaining gap. Nothing omitted.*
