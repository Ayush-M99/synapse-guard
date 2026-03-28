# DARWIN — System Design Document

> **Dynamic Adaptive Resilience With Intelligent Nodes**
> Manipal Institute of Technology Bengaluru · PS1 Hackathon

---

## 1. System Overview

DARWIN is a closed-loop autonomous chaos engineering platform. A **Virus agent** injects failures of increasing complexity across generations. A **4-stage ML pipeline** detects and classifies those failures — each model doing a single distinct job. A **RAG-based Antibody** retrieves and composes recovery playbooks from a Neo4j knowledge graph. The system learns over time, reducing recovery latency each generation.

**The core loop:**

```
Virus injects
    → Nerve endings stream telemetry
    → CUSUM catches slow drift  |  Isolation Forest catches fast anomalies
    → Random Forest classifies attack family
    → LSTM predicts next likely attack
    → RAG retrieves + composes playbook
    → Antibody recovers
    → DNA logged
    → repeat
```

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — Target Application (The Patient)                          │
│                                                                      │
│   auth-service   api-gateway   order-service                         │
│   payment-service   inventory-service   notification-service         │
│   darwin namespace · HTTP/gRPC inter-service · minikube              │
└─────────────────────────────┬────────────────────────────────────────┘
                              │  /metrics  /health
┌─────────────────────────────▼────────────────────────────────────────┐
│  LAYER 2 — Nerve Endings (Telemetry Collection Sidecars)             │
│                                                                      │
│   Collect: CPU · memory · error rate · P99 latency                   │
│   Collect: pod restart delta · net RX/TX delta                       │
│   Publish raw 7-feature vectors to NATS · no detection logic here    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │  raw telemetry stream (NATS)
┌─────────────────────────────▼────────────────────────────────────────┐
│  LAYER 3 — Brain (4-Stage ML Pipeline + Knowledge Graph)             │
│                                                                      │
│  Stage 1: CUSUM          slow drift pre-filter (classical stats)     │
│  Stage 2: Isolation Forest  fast point anomaly detection (unsup ML)  │
│  Stage 3: Random Forest     attack family classification (sup ML)    │
│  Stage 4: LSTM              next-attack prediction (temporal ML)     │
│                                                                      │
│  Neo4j knowledge graph · Redis immunity cache · RAG engine           │
└──────────────┬──────────────────────────────┬────────────────────────┘
               │                              │
┌──────────────▼─────────────┐  ┌─────────────▼──────────────────────┐
│  LAYER 4a — Virus Agent    │  │  LAYER 4b — Antibody Agent         │
│                            │  │  (RAG-based Recovery Engine)       │
│  6 attack families         │  │                                    │
│  Gen 1 / 2 / 3 strands     │  │  RF label → RAG retrieval          │
│  Fork / exec isolation     │  │  Redis → Neo4j → compose plan      │
└────────────────────────────┘  │  Min-heap queue · Semaphore locks  │
                                └────────────────────────────────────┘
                              │  writes
┌─────────────────────────────▼────────────────────────────────────────┐
│  LAYER 5 — DNA Store + Telemetry Stack                               │
│                                                                      │
│   PostgreSQL (generation history)   Redis (immunity cache)           │
│   Prometheus · Loki · Jaeger                                         │
└─────────────────────────────┬────────────────────────────────────────┘
                              │  WebSocket
┌─────────────────────────────▼────────────────────────────────────────┐
│  LAYER 6 — DARWIN Dashboard (React 18 + D3-force + Recharts)         │
│                                                                      │
│   Brain map · Evo timeline · Live battle feed · DNA replay · Score   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

### Languages

| Layer | Language | Reason |
|-------|----------|--------|
| Virus, Antibody, ML pipeline, Nerve endings | Python 3.11 | K8s SDK, scikit-learn, PyTorch, joblib — one ecosystem |
| NATS message consumers | Go 1.22 | Lightweight goroutines for high-throughput subscriber pattern |
| Dashboard frontend | TypeScript + React 18 | D3-force, Recharts, type-safe state management |
| Knowledge graph queries | Cypher (Neo4j) | Native graph query language |

### Infrastructure

| Tool | Role |
|------|------|
| minikube | Local single-node Kubernetes cluster |
| Docker | Container runtime for all pods |
| Helm | Kubernetes deployment manifests and package management |
| NATS | Message bus — raw telemetry stream + anomaly event propagation |

### Databases

| Database | Role | Why |
|----------|------|-----|
| Neo4j | Vulnerability knowledge graph — The Brain | Graph traversal for RAG retrieval, blast radius scoring |
| PostgreSQL | DNA store — generation history, LSTM training sequence | Append-only writes, time-series queries |
| Redis | Immunity memory cache | O(1) key lookup, TTL expiry — fast RAG first-pass |

### ML Stack

| Model | Library | Stage | Job |
|-------|---------|-------|-----|
| CUSUM | Pure Python (stdlib) | 1 | Slow drift pre-filter — no training required |
| Isolation Forest | scikit-learn | 2 | Fast point anomaly detection — unsupervised |
| Random Forest | scikit-learn | 3 | Attack family classification — supervised, pre-trained |
| LSTM (2-layer) | PyTorch | 4 | Next-attack sequence prediction — temporal |

---

## 4. Component Design

### 4.1 Target Microservices

| Service | DB | Role | Recovery Priority |
|---------|----|------|------------------|
| `auth-service` | PostgreSQL | JWT login / signup | P1 — High |
| `api-gateway` | — | Routes all external traffic | P1 — High |
| `order-service` | PostgreSQL | Creates and tracks orders | P2 — Medium |
| `payment-service` | PostgreSQL | Processes payments — **primary attack target** | P1 — Critical |
| `inventory-service` | Redis | Stock level reads/writes | P2 — Medium |
| `notification-service` | — | Sends alerts | P3 — Low (safe to evict) |

Inter-service dependency chain:
```
api-gateway  →  payment-service  →  order-service  →  inventory-service
```

---

### 4.2 Nerve Endings — Pure Telemetry Sidecars

Nerve endings collect and stream raw metrics. They contain **no detection logic, no thresholds, no decisions**.

**7-feature metric vector collected per scrape:**

```python
metric_vector = {
    "cpu_usage_pct":            0.82,
    "memory_usage_pct":         0.71,
    "http_error_rate_5xx":      0.03,
    "request_latency_p99_ms":   420,
    "pod_restart_count_delta":  0,
    "network_rx_bytes_delta":   104857,
    "network_tx_bytes_delta":   52428,
}
```

**Published to NATS as:**

```python
nats.publish("nerve.telemetry", {
    "service":   "payment-service",
    "pod_id":    "payment-service-abc123",
    "timestamp": "2024-...",
    "metrics":   metric_vector
})
```

**OS analogy — I/O data bus:** Nerve endings are pure I/O channels — they stream raw signals onto the bus. All interpretation is handled centrally downstream, not at the sensor.

---

### 4.3 4-Stage ML Detection Pipeline

The pipeline is the sole detection mechanism. Each stage has one job and feeds the next.

```
telemetry stream
      │
      ▼
┌─────────────────────────────────────────────┐
│  STAGE 1 — CUSUM  (slow drift pre-filter)   │
│  Catches: Gen 3 Camouflage (2%/5min ramp)   │
│  Output:  drift_detected = True/False       │
└─────────────────┬───────────────────────────┘
                  │ drift OR
                  │ next scrape cycle
                  ▼
┌─────────────────────────────────────────────┐
│  STAGE 2 — Isolation Forest  (fast anomaly) │
│  Catches: Gen 1/2 sudden failures           │
│  Output:  anomaly_score 0.0→1.0             │
│  Fires:   score > 0.65 for 3 scrapes        │
└─────────────────┬───────────────────────────┘
                  │ anomaly confirmed
                  ▼
┌─────────────────────────────────────────────┐
│  STAGE 3 — Random Forest  (classifier)      │
│  Input:   22-feature windowed vector        │
│  Output:  family_label + confidence 0→1     │
│  e.g.:    "pod_crash, 0.91"                 │
└─────────────────┬───────────────────────────┘
                  │ label + confidence
                  ▼
┌─────────────────────────────────────────────┐
│  STAGE 4 — LSTM  (temporal predictor)       │
│  Input:   sequence of past N DNA records    │
│  Output:  P(next_attack_family) distribution│
│  e.g.:    "timing_attack, 0.78"             │
└─────────────────┬───────────────────────────┘
                  │ prediction
                  ▼
           Ensemble Decision
           → RAG retrieval
           → Antibody action
```

---

#### Stage 1 — CUSUM (Cumulative Sum)

Purpose: catch gradual degradation that produces individually normal readings.

```python
def cusum(values: list[float], threshold: float = 5.0, drift: float = 0.5) -> bool:
    s_pos, s_neg = 0.0, 0.0
    for v in values:
        s_pos = max(0, s_pos + v - drift)
        s_neg = max(0, s_neg - v - drift)
        if s_pos > threshold or s_neg > threshold:
            return True   # sustained drift detected
    return False
```

Run on a rolling 10-minute window of each metric per service. When CUSUM fires, it wakes Isolation Forest to begin active scoring even if the current reading appears normal.

---

#### Stage 2 — Isolation Forest

Purpose: detect sudden point anomalies in the metric vector.

```python
from sklearn.ensemble import IsolationForest

# Pre-trained on 2000 baseline healthy-cluster snapshots
model = IsolationForest(contamination=0.05, random_state=42)
model.fit(baseline_metrics_df)   # done before hackathon

# At runtime — every 5 seconds
score = model.decision_function([current_7_feature_vector])[0]
normalised_score = 1 - ((score + 0.5) / 1.0)   # map to 0→1

if normalised_score > 0.65:
    sustained_count += 1
    if sustained_count >= 3:
        trigger_classifier(current_vector)
else:
    sustained_count = 0
```

---

#### Stage 3 — Random Forest Classifier

Purpose: identify *what kind* of attack this is. Outputs the label that drives RAG retrieval.

**22-feature input vector:**

```python
features = [
    # Current snapshot (7)
    cpu, memory, error_rate, latency_p99,
    restart_delta, rx_delta, tx_delta,

    # Delta over last 30 s (7)
    cpu_d30, mem_d30, err_d30, lat_d30,
    restart_d30, rx_d30, tx_d30,

    # Delta over last 60 s (7)
    cpu_d60, mem_d60, err_d60, lat_d60,
    restart_d60, rx_d60, tx_d60,

    # Structural context (1)
    downstream_services_also_anomalous,   # bool
]
```

**Pre-training strategy (night before the hackathon):**

```bash
# Run each attack strand 50 times, capture metrics at T+0, T+5s, T+10s, T+30s
python scripts/generate_training_data.py --strands all --runs 50
# Outputs: training_data.csv with 22 features + label column

# Train and serialise
python scripts/train_classifier.py
# Outputs: models/rf_classifier.joblib
```

**At runtime:**

```python
import joblib
clf = joblib.load("models/rf_classifier.joblib")

label, confidence = clf.predict([features])[0], clf.predict_proba([features]).max()
# e.g. label="pod_crash", confidence=0.91
```

---

#### Stage 4 — LSTM (Temporal Predictor)

Purpose: predict the *next* likely attack based on the observed sequence of past generations. This is what enables the antibody to pre-scale before a strike lands.

**Input — sequence from PostgreSQL DNA store:**

```python
sequence = [
    {"family": "pod_crash",    "recovery_ms": 18000, "outcome": "recovered"},
    {"family": "pod_crash",    "recovery_ms": 2100,  "outcome": "recovered"},
    {"family": "timing_attack","recovery_ms": 800,   "outcome": "recovered"},
    # ... last N generations
]
# Encoded as integer tensor and fed to LSTM
```

**Output:**

```python
# Probability distribution over attack families
{
    "pod_crash":    0.04,
    "network":      0.11,
    "timing_attack":0.78,   # ← high confidence
    "resource":     0.04,
    "camouflage":   0.03,
}
```

**Pre-scale trigger:**

```python
if prediction["timing_attack"] > 0.78:
    antibody.pre_scale(target="payment-service", replicas=3)
    antibody.pre_scale(target="order-service", replicas=2)
    log("LSTM pre-scale triggered — timing attack predicted")
```

---

#### Ensemble Decision Logic

```python
def ensemble_decide(rf_label, rf_confidence, lstm_prediction):

    if rf_confidence > 0.85:
        # High confidence — execute known playbook immediately
        return Action.EXECUTE_PLAYBOOK(rf_label)

    elif 0.60 <= rf_confidence <= 0.85:
        # Medium confidence — execute playbook + hedge with honeypot
        return Action.EXECUTE_PLAYBOOK(rf_label) + Action.DEPLOY_HONEYPOT()

    else:
        # Low confidence — conservative restart + flag for brain update
        return Action.CONSERVATIVE_RESTART() + Action.UPDATE_NEO4J(anomaly_sig)

    # Independent of confidence — LSTM pre-scale runs in parallel
    if lstm_prediction.max_prob > 0.78:
        Action.PRE_SCALE(lstm_prediction.top_family)
```

---

### 4.4 Virus Agent

**File structure:**

```
virus/
├── agent.py
├── k8s_client.py
└── strands/
    ├── pod_crash.py       # Gen 1 — FR-08
    ├── network.py         # Gen 1 — FR-09
    ├── resource.py        # Gen 2 — FR-10
    ├── timing.py          # Gen 2 — FR-11
    ├── amplification.py   # Gen 2 — FR-12
    └── camouflage.py      # Gen 3 — FR-13 (tests CUSUM specifically)
```

**Generational progression:**

| Generation | Families Used | What it tests in the pipeline |
|------------|--------------|-------------------------------|
| Gen 1 | pod_crash, network | IF fast detection · RF high-confidence classification |
| Gen 2 | timing, resource | RF medium-confidence · LSTM predicts follow-up |
| Gen 3 | camouflage | CUSUM slow-drift path · IF stays quiet · RF camouflage label |

**Fork / exec isolation:**

```python
def execute_strand(strand_fn, *args):
    pid = os.fork()
    if pid == 0:
        result = strand_fn(*args)
        os._exit(0 if result else 1)
    else:
        _, status = os.waitpid(pid, 0)
        return os.WEXITSTATUS(status)
```

---

### 4.5 Antibody Agent — RAG-based Recovery

The antibody receives the RF label + anomaly signature as a retrieval query. It never hardcodes playbooks.

#### RAG Decision Flow

```
Anomaly event received (RF label + signature + confidence)
          │
          ▼
  Build retrieval query: {label, signature_hash, service}
          │
          ▼
  ┌───────────────────────────────┐
  │  1. Redis lookup              │
  │     KEY: immunity:{sig_hash}  │
  └────────────┬──────────────────┘
          HIT  │  MISS
           │   │
           │   ▼
           │  ┌───────────────────────────────────────────────────┐
           │  │  2. Neo4j RAG retrieval                           │
           │  │                                                   │
           │  │  MATCH (f:Family {name: $rf_label})               │
           │  │  -[:HAS_PLAYBOOK]->(p:Playbook)                   │
           │  │  RETURN p.actions, p.priority_order               │
           │  └───────────────────────────────────────────────────┘
           │
           ├── compose recovery plan from retrieved context
           │
           ▼
  Priority queue (min-heap)
  payment/auth P1 · order/inventory P2 · notification P3
          │
          ▼
  acquire semaphore(pod_id)
          │
          ▼
  Execute: restart · scale · reroute · rate-limit · circuit-break
          │
          ▼
  write Redis (TTL 24h) · write PostgreSQL DNA · release semaphore
```

**OS concepts in the antibody:**

| OS Concept | DARWIN Implementation |
|------------|----------------------|
| Virtual memory / page cache | Hot playbooks in Redis (RAM), full graph in Neo4j (disk). Cache miss = page fault → graph traversal |
| Preemptive scheduling | Min-heap priority queue — payment/auth preempt notification |
| Semaphore | `threading.Semaphore(1)` per pod ID — prevents recovery race conditions |
| Fork / exec | Virus attacks run in isolated child processes — parent never crashes |
| I/O bus | Nerve endings stream raw telemetry without interpretation — detection is centralised |

---

### 4.6 Knowledge Graph Schema (Neo4j)

```cypher
(:Family {name: "pod_crash"})
(:Family {name: "network"})
(:Family {name: "resource"})
(:Family {name: "timing"})
(:Family {name: "camouflage"})

(:Attack {
    strand_id:  "pod_crash_A",
    signature:  "payment:pod_deleted:oom",
    generation: 1
})

(:Playbook {
    id:             "playbook_pod_crash",
    actions:        ["restart_pod", "scale_replicas", "alert_brain"],
    priority_order: ["payment", "auth", "order"]
})

(:Service {name: "payment-service", priority: 1})

(:Attack)-[:BELONGS_TO]->(:Family)
(:Family)-[:HAS_PLAYBOOK]->(:Playbook)
(:Attack)-[:TARGETS]->(:Service)
(:Attack)-[:MUTATED_FROM]->(:Attack)
(:Service)-[:DEPENDS_ON]->(:Service)
```

---

### 4.7 DNA Store Schema (PostgreSQL)

```sql
CREATE TABLE generations (
    id                  SERIAL PRIMARY KEY,
    virus_gen           INTEGER      NOT NULL,
    antibody_gen        INTEGER      NOT NULL,
    strand_id           VARCHAR(64)  NOT NULL,
    strand_family       VARCHAR(32)  NOT NULL,
    target_service      VARCHAR(64)  NOT NULL,
    injection_ts        TIMESTAMPTZ  NOT NULL,
    detection_ts        TIMESTAMPTZ,
    recovery_ts         TIMESTAMPTZ,
    recovery_ms         INTEGER,
    cache_hit           BOOLEAN      DEFAULT FALSE,
    rag_source          VARCHAR(16),       -- 'redis' | 'neo4j'
    rf_label            VARCHAR(32),       -- classifier output
    rf_confidence       FLOAT,             -- 0.0–1.0
    lstm_predicted      BOOLEAN,           -- was this attack LSTM-predicted?
    detection_path      VARCHAR(32),       -- 'cusum' | 'isolation_forest' | 'both'
    outcome             VARCHAR(16)        -- 'recovered' | 'failed' | 'partial'
);
```

The `detection_path` column lets the dashboard show — per generation — which detection stage caught the attack. Directly proves the pipeline's value to judges.

---

### 4.8 Dashboard

**Panel breakdown:**

| Panel | Library | Data Source | Key Feature |
|-------|---------|-------------|-------------|
| Brain Map | D3-force | WebSocket live | Node colour by health — watch cascade spread in real time |
| Battle Feed | React state | WebSocket live | Shows all 4 model scores live — CUSUM / IF / RF label / LSTM prediction |
| Evo Timeline | Recharts `LineChart` | PostgreSQL | Recovery time slope across generations |
| DNA Replay | D3-force + playback | PostgreSQL | Replay any past generation on the brain map |
| Resilience Score | SVG gauge | Client-side calc | `(1−recovery_time)×400 + rf_accuracy×200 + (1−unknown_rate)×200 + blast_contained×200` |

---

## 5. Full Attack Cycle — Data Flow

```
 1.  virus/agent.py           Selects strand for current generation
 2.  virus/strands/*.py       Executes attack via K8s SDK (fork/exec child)
 3.  Kubernetes API           Pod deleted / network policy / resource pressure
 4.  nerve_ending.py          Publishes 7-feature metric vector to NATS every 2 s
 5.  CUSUM                    Checks rolling window for sustained drift (Gen 3 path)
 6.  Isolation Forest         Scores metric vector — fires if > 0.65 for 3 scrapes (Gen 1/2 path)
 7.  Random Forest            Classifies confirmed anomaly → family label + confidence
 8.  LSTM                     Checks DNA sequence → outputs next-attack prediction
 9.  Ensemble logic           Decides: immediate playbook / playbook + honeypot / conservative
 9b. LSTM trigger             If prediction > 0.78 → pre-scale target before strike
10.  antibody/rag_engine.py   Redis lookup → Neo4j retrieval → compose plan
11.  antibody/recovery.py     Execute recovery actions
12.  antibody/agent.py        Write Redis (TTL 24h) · write PostgreSQL DNA row
13.  dashboard/ws.py          Fan event to WebSocket clients
14.  React Dashboard          Brain map · timeline · scores all update
```

---

## 6. Directory Structure

```
darwin/
├── k8s/
│   ├── namespace.yaml
│   ├── services/
│   ├── prometheus/
│   ├── nats/
│   ├── neo4j/
│   ├── redis/
│   └── postgres/
│
├── services/
│   ├── auth-service/
│   ├── api-gateway/
│   ├── order-service/
│   ├── payment-service/
│   ├── inventory-service/
│   └── notification-service/
│
├── nerve-ending/
│   └── nerve.py
│
├── virus/
│   ├── agent.py
│   ├── k8s_client.py
│   └── strands/
│       ├── pod_crash.py
│       ├── network.py
│       ├── resource.py
│       ├── timing.py
│       ├── amplification.py
│       └── camouflage.py
│
├── detector/
│   ├── pipeline.py           # Orchestrates all 4 stages
│   ├── cusum.py              # Stage 1
│   ├── isolation_forest.py   # Stage 2
│   ├── classifier.py         # Stage 3 — Random Forest
│   ├── lstm.py               # Stage 4
│   └── ensemble.py           # Decision logic
│
├── models/
│   ├── rf_classifier.joblib  # Pre-trained before hackathon
│   ├── lstm_weights.pt       # Pre-trained before hackathon
│   └── if_baseline.joblib    # Trained on healthy baseline
│
├── antibody/
│   ├── agent.py
│   ├── rag_engine.py
│   ├── recovery.py
│   ├── brain.py              # Neo4j
│   ├── memory.py             # Redis
│   └── dna.py                # PostgreSQL
│
├── dashboard/
│   ├── backend/main.py
│   └── frontend/src/
│       ├── panels/
│       │   ├── BrainMap.tsx
│       │   ├── BattleFeed.tsx
│       │   ├── EvoTimeline.tsx
│       │   ├── DNAReplay.tsx
│       │   └── ResilienceScore.tsx
│       └── App.tsx
│
├── graph/seed.cypher
│
└── scripts/
    ├── generate_training_data.py   # Runs attacks, captures CSV
    ├── train_classifier.py         # Trains RF + LSTM, saves weights
    ├── setup.sh
    ├── demo.sh
    └── teardown.sh
```

---

## 7. Build Sequence — 36 Hours

| Hours | Milestone | Done When |
|-------|-----------|-----------|
| 0 – 4 | minikube · 6 services · Prometheus scraping | All pods `Running` in darwin namespace |
| 4 – 8 | Virus Gen 1–3 strands · Neo4j seeded · nerve endings streaming to NATS | Manual attack deletes pod — nerve.py publishes telemetry event |
| 8 – 12 | CUSUM + Isolation Forest running · training data generation script | IF fires within 5 s of Gen 1 injection · CSV output verified |
| 12 – 16 | RF classifier trained + loaded · LSTM trained + loaded · ensemble decision logic | RF outputs correct family label on all 6 attack families |
| 16 – 20 | RAG engine wired (Redis → Neo4j) · antibody executing playbooks · DNA store writing | Full loop completes end-to-end: inject → detect → classify → recover → write |
| 20 – 26 | Dashboard: brain map + battle feed (4 model scores live) + evo timeline | Dashboard shows real-time node colour + RF label during attack |
| 26 – 30 | DNA replay · resilience score · 3 hardcoded demo scenarios | `demo.sh scenario_1` passes 3× consecutively |
| 30 – 36 | Bug buffer · demo rehearsal · slide prep | Full 3-min demo runs clean |

---

## 8. Demo Script — 3 Minutes

| Time | Action | Expected Visual |
|------|--------|-----------------|
| 0:00 | Open dashboard | 6 green nodes · all model scores at 0 · Score: 0 |
| 0:15 | `demo.sh gen1` (pod crash) | Payment → red · cascades to order → orange |
| 0:30 | IF fires | Battle feed: IF score bar climbs · RF label appears: `pod_crash 91%` |
| 0:50 | RAG retrieves playbook | Battle feed: `Neo4j → playbook_pod_crash → executing` |
| 1:00 | Recovery complete | All green · 18 s · Score: 210 |
| 1:10 | Re-inject Gen 1 | Redis hit · 2 s recovery · Score: 480 |
| 1:20 | `demo.sh gen3` (camouflage) | Gradual latency ramp begins |
| 1:35 | IF stays quiet, CUSUM fires | Battle feed: `CUSUM: drift detected` · RF label: `camouflage 83%` |
| 1:50 | LSTM prediction fires | `timing_attack predicted (0.81) → pre-scaling payment` · node turns yellow before attack |
| 2:05 | Recovery complete | 0.8 s · Score: 720 |
| 2:15 | Show Evo Timeline | Slope: 18 s → 2 s → 0.8 s |
| 2:35 | DNA Replay Gen 1 | Brain map replays · `detection_path: isolation_forest` shown |
| 2:55 | Final score | **847 / 1000** |
| 3:00 | Done | — |
