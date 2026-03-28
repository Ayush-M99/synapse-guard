<<<<<<< HEAD
# Welcome to your Lovable project

TODO: Document your project here
=======
# DARWIN Platform — Complete README

## What Is DARWIN?

**DARWIN** is an autonomous chaos engineering and self-healing platform for Kubernetes microservices.  
It uses a biological immune-system model:

| Component | Biological Analogy | Implementation |
|---|---|---|
| Virus Agent | Pathogen | Injects K8s pod/network faults |
| ML Pipeline | Immune sensors | IF + RF + LSTM anomaly detection |
| Antibody / Recovery Engine | Antibodies | 3-tier RAG recovery (Redis → Neo4j → Gemini) |
| T-Cell Memory | Immune memory | Redis O(1) strand cache |
| DNA Store | Genetic memory | PostgreSQL evolutionary history |
| Knowledge Graph | Neural memory | Neo4j attack/recovery graph |
| NATS | Neural bus | Event messaging |
| Dashboard | Brain UI | Rich terminal + Matplotlib live figures |
| DARWIN API | Control plane | FastAPI REST API |

---

## Quick Start (WSL2 + Minikube)

### 1. Port-forward services from minikube

```bash
# Terminal 1 — keep alive
chmod +x port_forward.sh
./port_forward.sh darwin
```

### 2. Seed the knowledge graph

```bash
python seed_graph.py
```

### 3. Start the DARWIN API server

```bash
pip install -r darwin_api/requirements.txt
uvicorn darwin_api.main:app --host 0.0.0.0 --port 9000 --reload
```

### 4. Start the WS Bridge (NATS → Dashboard)

```bash
pip install -r ws_bridge/requirements.txt
uvicorn ws_bridge.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start the ML Pipeline

```bash
pip install -r ml_pipeline/requirements.txt
python -m ml_pipeline.pipeline
```

### 6. Start the Live Dashboard

```bash
pip install -r dashboard/requirements.txt
python -m dashboard.live_dashboard
```

### 7. Run Demo Scenarios

```bash
# Scenario 1: Gen1 — Immunity acquired (pod_crash × 2, second = T-cell hit)
python demo.py 1

# Scenario 2: Gen2 — Timing attack + LSTM preemptive scale
python demo.py 2

# Scenario 3: Gen3 — Unknown strand + Honeypot discovery
python demo.py 3

# Full 5-minute hackathon demo
python demo.py full

# Pure simulation (no K8s required)
python demo.py fallback
```

---

## DARWIN API Endpoints

Base URL: `http://localhost:9000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | System health (K8s, Redis, Prometheus, Neo4j) |
| GET | `/pods` | List pods in patient namespace |
| GET | `/deployments` | List deployments + replica status |
| GET | `/metrics` | Live Prometheus 7-feature metrics |
| GET | `/targets` | Prometheus scrape targets |
| GET | `/anomalies` | Recent anomalies from Redis |
| GET | `/recoveries` | Recent recoveries from Redis |
| GET | `/immunity` | T-cell memory contents |
| GET | `/faults` | Active fault injections |
| POST | `/inject-fault` | Inject chaos (see below) |
| POST | `/recover` | Trigger autonomous recovery |
| POST | `/seed-graph` | Seed Neo4j knowledge graph |
| GET | `/graph/nodes` | Neo4j brain map data |
| GET | `/health/services` | Per-service health scores |

### Inject Fault

```bash
curl -X POST http://localhost:9000/inject-fault \
  -H "Content-Type: application/json" \
  -d '{"service": "payment-service", "fault_type": "pod_crash"}'
```

Fault types: `pod_crash | scale_down | cpu_stress | memory_hog | network_latency`

### Trigger Recovery

```bash
curl -X POST http://localhost:9000/recover \
  -H "Content-Type: application/json" \
  -d '{"service": "payment-service", "strand_id": "pod_crash_A", "attack_family": "pod_crash", "rf_confidence": 0.94, "anomaly_score": 0.87}'
```

---

## ML Models (Pre-Trained — DO NOT MODIFY)

Located in `Chaos_Platform_Assets/models/`:

| File | Type | Details |
|---|---|---|
| `isolation_forest.joblib` | scikit-learn IF | Unsupervised, 7 features, Locust-trained |
| `random_forest.joblib` | scikit-learn RF | **87.6% accuracy**, 5 families |
| `lstm_predictor.pt` | PyTorch LSTM | 2-layer 64-hidden, next-attack prediction |

Feature vector: `cpu_usage_pct, memory_usage_pct, http_error_rate_5xx, request_latency_p99, pod_restart_count_delta, network_rx_bytes_delta, network_tx_bytes_delta`

---

## Infrastructure

External services run via Docker Compose:

| Service | Port | Credentials |
|---|---|---|
| PostgreSQL | 5432 | chaos / chaospassword / chaos_dna |
| Redis | 6379 | none |
| Neo4j | 7474 / 7687 | neo4j / chaospassword |
| NATS | 4222 | none |
| Prometheus | 9090 | none |
| Grafana | 3000 | admin / admin |
| Loki | 3100 | none |
| Jaeger | 16686 | none |

```bash
docker compose up -d
```

**WSL2 note:** Redis and Prometheus are already running in minikube.  
Use `./port_forward.sh darwin` to expose them on localhost.

---

## Project Structure

```
Hackthon_solistic/
├── darwin_api/              ← DARWIN Control Plane (FastAPI)
│   ├── main.py              ← 12 REST endpoints
│   ├── k8s_client.py        ← Real kubernetes-python SDK
│   ├── prometheus_client.py ← Real Prometheus HTTP API
│   ├── redis_client.py      ← Real Redis (T-cell memory)
│   ├── chaos_engine.py      ← Fault injection engine
│   └── recovery_engine.py   ← 3-tier RAG recovery
├── ml_pipeline/             ← ML Brain (CUSUM + IF + RF + LSTM)
│   ├── pipeline.py          ← Main orchestrator
│   ├── cusum.py             ← CUSUM slow-drift detection
│   ├── model_loader.py      ← Loads pre-trained .joblib/.pt
│   └── prometheus_poller.py ← Async Prometheus poller
├── dashboard/
│   └── live_dashboard.py    ← Rich terminal + Matplotlib live
├── ws_bridge/
│   └── main.py              ← FastAPI NATS→WS bridge + REST
├── virus_agent/
│   ├── attack_library.py    ← 18 strands, 5 families
│   ├── istio_client.py      ← Istio VirtualService client
│   └── generation_controller.py ← VirusBrain mutation logic
├── antibody/                ← (existing) Antibody agent
├── Chaos_Platform_Assets/   ← Pre-trained models + seeds (DO NOT MODIFY)
├── k8s/
│   ├── darwin/              ← DARWIN K8s deployments
│   ├── target/              ← Patient app manifests
│   └── namespaces.yaml
├── observability/           ← Prometheus / Loki / Grafana configs
├── docker-compose.yml       ← Full infrastructure stack
├── seed_graph.py            ← Neo4j seeder wrapper
├── demo.py                  ← Hackathon demo runner
├── port_forward.sh          ← WSL2 port-forward helper
├── start.ps1                ← Windows one-command startup
└── start.sh                 ← Linux/WSL2 one-command startup
```

---

## Environment Variables

```bash
# Required
PROMETHEUS_URL=http://localhost:9090
NATS_URL=nats://localhost:4222
REDIS_URL=redis://localhost:6379
PG_URL=postgres://chaos:chaospassword@localhost:5432/chaos_dna
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=chaospassword
PATIENT_NAMESPACE=patient
DARWIN_NAMESPACE=darwin

# Optional (needed for LLM honeypot synthesis)
GEMINI_API_KEY=your_key_here

# Tuning
IF_THRESHOLD=0.65
IF_SUSTAIN_COUNT=3
RF_PROB_THRESH=0.60
LSTM_CONF_THRESH=0.70
SCRAPE_INTERVAL=5
```
>>>>>>> origin/SHikhar_branch
