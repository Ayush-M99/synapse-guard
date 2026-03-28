# DARWIN — Autonomous Chaos Engineering & Self-Healing Platform

> Inject → Detect (ML) → Recover (RAG) → Learn (Neo4j) → Evolve

## Quick Start (3 commands)

```bash
# 1. First-time setup
bash SETUP.sh setup

# 2. Start DARWIN API (keep this terminal open)
bash SETUP.sh run

# 3. In a new terminal — start dashboard + load generator
bash SETUP.sh dashboard    # → http://localhost:3000
bash SETUP.sh locust       # → http://localhost:8089
```

## Project Layout

```
DARWIN/
├── SETUP.sh                  ← Master launcher (run everything from here)
│
├── darwin_api/               ← FastAPI control plane (:9000)
│   ├── main.py               ← 12 REST endpoints
│   ├── chaos_engine.py       ← Fault injection (pod_crash, scale, stress, latency)
│   ├── recovery_engine.py    ← 3-tier RAG: Redis → Neo4j → LLM
│   ├── k8s_client.py         ← Kubernetes SDK wrapper
│   ├── prometheus_client.py  ← Prometheus metric poller
│   └── redis_client.py       ← T-cell cache + event store
│
├── ml_pipeline/              ← ML anomaly detection
│   ├── pipeline.py           ← Orchestrator (IF + RF + LSTM + CUSUM)
│   ├── model_loader.py       ← Load pre-trained models from Chaos_Platform_Assets
│   ├── cusum.py              ← CUSUM drift detector
│   └── prometheus_poller.py  ← Feature vector builder
│
├── darwin-dashboard/         ← React SPA (Vite + Recharts)
│   ├── src/
│   │   ├── App.jsx           ← 5-tab layout
│   │   ├── components/       ← Header, FaultInjector, AttackFeed, etc.
│   │   └── hooks/            ← useDarwinAPI, useMetricsPoller
│   └── package.json
│
├── microservices/            ← Patient application (6 FastAPI services)
│   ├── auth-service/
│   ├── api-gateway/
│   ├── order-service/
│   ├── payment-service/
│   ├── inventory-service/
│   └── notification-service/
│
├── locust/
│   └── locustfile.py         ← 4 traffic profiles (normal/stress/spike/camouflage)
│
├── k8s/
│   ├── darwin/               ← Redis, Prometheus, NATS manifests
│   └── target/               ← Patient app K8s manifests
│
├── Chaos_Platform_Assets/    ← Pre-trained ML models (IF, RF, LSTM)
├── docker-compose.yml        ← Full infra (Neo4j, Postgres, NATS, Loki, Jaeger)
└── seed_graph.py             ← Neo4j knowledge graph seeder
```

## Architecture

```
[Locust] ──traffic──▶ [Patient App (6 services)] ──metrics──▶ [Prometheus]
                                                                      │
                                                              [ML Pipeline]
                                                           (IF + RF + LSTM + CUSUM)
                                                                      │
                                                          anomaly detected
                                                                      │
[Redis T-cell cache] ──hit──▶ [Recovery Engine] ──playbook──▶ [K8s Actions]
[Neo4j graph]        ──miss──▶        │
[Gemini LLM]         ──fallback──▶    │
                                      ▼
                               [DARWIN Dashboard]
                        http://localhost:3000
```

## API Endpoints (localhost:9000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System component health |
| GET | `/pods` | List patient namespace pods |
| GET | `/metrics?service=X` | Prometheus metrics for service |
| POST | `/inject-fault` | Inject chaos fault |
| POST | `/recover` | Trigger autonomous recovery |
| GET | `/anomalies` | Recent anomaly events |
| GET | `/recoveries` | Recovery history |
| GET | `/immunity` | T-cell cache entries |
| GET | `/targets` | Prometheus scrape targets |

Interactive docs: **http://localhost:9000/docs**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus endpoint |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j graph DB |
| `DARWIN_NAMESPACE` | `darwin` | Infra K8s namespace |
| `PATIENT_NAMESPACE` | `patient` | Target app namespace |
| `GEMINI_API_KEY` | *(optional)* | LLM fallback for Tier 3 |

## Prerequisites

- **WSL2** with Ubuntu, minikube running
- **kubectl** configured to minikube cluster
- **Python 3.12** venv at `~/darwin/venv` (created by `SETUP.sh setup`)
- **Node.js** for dashboard: `winget install OpenJS.NodeJS.LTS` (Windows)
- K8s pods: Redis + Prometheus already deployed in `darwin` namespace

## Commands Reference

```bash
bash SETUP.sh setup     # First-time: venv, deps, K8s namespaces, port-forwards
bash SETUP.sh run       # DARWIN API server (foreground, :9000)
bash SETUP.sh dashboard # React dashboard (foreground, :3000)
bash SETUP.sh locust    # Load generator UI (foreground, :8089)
bash SETUP.sh all       # Everything in background
bash SETUP.sh status    # Health check all services
bash SETUP.sh stop      # Kill all DARWIN processes
```
