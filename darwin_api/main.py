"""
DARWIN Control Plane — FastAPI Main Server
==========================================
All 7 endpoints wired to real K8s, Redis, Prometheus.

Run (from project root, inside WSL):
    uvicorn darwin_api.main:app --host 0.0.0.0 --port 9000 --reload

Endpoints:
  GET  /health          → system health (K8s, Redis, Prometheus, Neo4j)
  GET  /pods            → list pods in patient namespace
  GET  /deployments     → list deployments + ready status
  GET  /metrics         → live Prometheus metrics for all 6 services
  GET  /anomalies       → recent anomaly events from Redis
  GET  /recoveries      → recent recovery events from Redis
  GET  /immunity        → T-cell memory cache contents
  POST /inject-fault    → inject chaos into a service
  POST /recover         → trigger autonomous recovery
  POST /seed-graph      → seed (or re-seed) Neo4j knowledge graph
  GET  /graph/nodes     → Neo4j brain map data
"""

import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import k8s_client         as k8s
from . import prometheus_client  as prom
from . import redis_client       as redis_store
from .chaos_engine    import engine   as chaos
from .recovery_engine import engine   as recovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DARWIN-API] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

PATIENT_NS = os.getenv("PATIENT_NAMESPACE", "patient")
DARWIN_NS  = os.getenv("DARWIN_NAMESPACE",  "darwin")

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DARWIN Control Plane API",
    description=(
        "Autonomous Chaos Engineering & Self-Healing Platform\n"
        "Real connections: Kubernetes (minikube) · Redis · Prometheus · Neo4j"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response models ────────────────────────────────────────────────

class FaultRequest(BaseModel):
    service:          str   = Field(..., example="payment-service")
    fault_type:       str   = Field("pod_crash", example="pod_crash",
                                     description="pod_crash | scale_down | cpu_stress | memory_hog | network_latency")
    duration_seconds: int   = Field(0,    description="0 = permanent until recovered")
    params:           dict  = Field({},   description="Extra params e.g. {delay_ms: 2000}")


class RecoverRequest(BaseModel):
    service:       str   = Field(...,     example="payment-service")
    strand_id:     str   = Field("auto",  example="pod_crash_A")
    attack_family: str   = Field("pod_crash", example="pod_crash")
    rf_confidence: float = Field(0.90,   ge=0.0, le=1.0)
    anomaly_score: float = Field(0.87,   ge=0.0, le=1.0)
    metrics:       dict  = Field({},     description="Optional raw metric snapshot")


# ─── GET /health ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    """
    Full system health check.
    Checks: Kubernetes API, Redis, Prometheus, Neo4j (if available).
    """
    k8s_ok   = _check_k8s()
    redis_ok = redis_store.ping()
    prom_ok  = prom.is_prometheus_up()

    neo4j_ok = False
    try:
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASS", "chaospassword"))
        )
        d.verify_connectivity()
        neo4j_ok = True
        d.close()
    except Exception:
        pass

    overall = all([k8s_ok, redis_ok])  # prom + neo4j are optional

    return {
        "status":    "healthy" if overall else "degraded",
        "timestamp": time.time(),
        "components": {
            "kubernetes":  {"ok": k8s_ok,   "endpoint": f"kubectl context"},
            "redis":       {"ok": redis_ok,  "endpoint": "localhost:6379", **redis_store.info()},
            "prometheus":  {"ok": prom_ok,   "endpoint": os.getenv("PROMETHEUS_URL", "http://localhost:9090")},
            "neo4j":       {"ok": neo4j_ok,  "endpoint": os.getenv("NEO4J_URI", "bolt://localhost:7687")},
        },
        "active_faults":  len(chaos.list_active_faults()),
    }


# ─── GET /pods ───────────────────────────────────────────────────────────────

@app.get("/pods", tags=["Kubernetes"])
async def list_pods(namespace: str = PATIENT_NS):
    """List all pods in the patient namespace with status and restart counts."""
    pods = k8s.list_pods(namespace)
    return {
        "namespace": namespace,
        "count":     len(pods),
        "pods":      pods,
    }


# ─── GET /deployments ────────────────────────────────────────────────────────

@app.get("/deployments", tags=["Kubernetes"])
async def list_deployments(namespace: str = PATIENT_NS):
    """List all deployments and their ready/desired replica counts."""
    deploys = k8s.list_deployments(namespace)
    return {
        "namespace":   namespace,
        "deployments": deploys,
    }


# ─── GET /metrics ────────────────────────────────────────────────────────────

@app.get("/metrics", tags=["Observability"])
async def get_metrics(service: Optional[str] = None):
    """
    Fetch live Prometheus metrics for all services (or one service).
    Returns the exact 7-feature vector used by the ML models.
    """
    if service:
        metrics = prom.get_service_metrics(service)
        return {"service": service, "metrics": metrics}
    else:
        all_metrics = prom.get_all_services_metrics()
        return {
            "timestamp": time.time(),
            "services":  all_metrics,
        }


# ─── GET /targets ────────────────────────────────────────────────────────────

@app.get("/targets", tags=["Observability"])
async def get_targets():
    """Show Prometheus scrape targets and their health."""
    targets = prom.get_targets()
    return {"targets": targets, "count": len(targets)}


# ─── GET /anomalies ───────────────────────────────────────────────────────────

@app.get("/anomalies", tags=["Intelligence"])
async def get_anomalies(limit: int = 20):
    """Return recent anomaly events from Redis."""
    anomalies = redis_store.get_recent_anomalies(limit)
    return {"count": len(anomalies), "anomalies": anomalies}


# ─── GET /recoveries ─────────────────────────────────────────────────────────

@app.get("/recoveries", tags=["Intelligence"])
async def get_recoveries(limit: int = 10):
    """Return recent recovery actions from Redis."""
    recoveries = redis_store.get_recent_recoveries(limit)
    return {"count": len(recoveries), "recoveries": recoveries}


# ─── GET /immunity ────────────────────────────────────────────────────────────

@app.get("/immunity", tags=["Intelligence"])
async def get_immunity():
    """Show all T-cell memory entries (cached strand → playbook mappings)."""
    keys = redis_store.get_all_immunity_keys()
    entries = {}
    for k in keys:
        entries[k] = redis_store.check_immunity(k)
    return {"t_cell_count": len(keys), "immunity": entries}


# ─── GET /faults ──────────────────────────────────────────────────────────────

@app.get("/faults", tags=["Chaos"])
async def list_faults():
    """List currently active (not yet recovered) fault injections."""
    return {"active_faults": chaos.list_active_faults()}


# ─── POST /inject-fault ───────────────────────────────────────────────────────

@app.post("/inject-fault", tags=["Chaos"])
async def inject_fault(request: FaultRequest, background_tasks: BackgroundTasks):
    """
    Inject a controlled fault into a patient service.

    fault_type options:
      pod_crash        — delete pod (K8s restarts via Deployment)
      scale_down       — scale to 0 replicas
      cpu_stress       — deploy busybox CPU stress pod
      memory_hog       — deploy memory stress pod
      network_latency  — inject Istio latency (if Istio available)
    """
    logger.warning(
        f"⚠️  Fault injection requested: {request.fault_type} → {request.service}"
    )
    result = chaos.inject_fault(
        service          = request.service,
        fault_type       = request.fault_type,
        duration_seconds = request.duration_seconds,
        params           = request.params,
    )

    if not result.success:
        raise HTTPException(status_code=422, detail=result.details)

    # If duration set, schedule auto-recovery
    if request.duration_seconds > 0:
        background_tasks.add_task(
            _auto_recover_after,
            request.service,
            f"{request.fault_type}_auto",
            request.fault_type,
            request.duration_seconds,
        )

    return {
        "message":  f"Fault injected successfully",
        "result":   result.to_dict(),
        "auto_recover_in_s": request.duration_seconds or None,
    }


# ─── POST /recover ────────────────────────────────────────────────────────────

@app.post("/recover", tags=["Recovery"])
async def trigger_recovery(request: RecoverRequest):
    """
    Trigger autonomous recovery for a service.

    Flow:
      1. Redis T-cell memory check (O(1), ~2s if hit)
      2. Neo4j knowledge graph query (if PROBABLE confidence)
      3. Gemini LLM synthesis (if UNKNOWN / no graph result)
    """
    logger.info(f"💉 Recovery triggered: {request.service} | {request.strand_id}")

    outcome = recovery.recover(
        service        = request.service,
        strand_id      = request.strand_id,
        attack_family  = request.attack_family,
        rf_confidence  = request.rf_confidence,
        anomaly_score  = request.anomaly_score,
        metrics        = request.metrics,
    )

    status_code = 200 if outcome["success"] else 207  # 207 = partial success
    return JSONResponse(content=outcome, status_code=status_code)


# ─── POST /seed-graph ─────────────────────────────────────────────────────────

@app.post("/seed-graph", tags=["Intelligence"])
async def seed_graph(clear: bool = False):
    """
    Seed (or re-seed) the Neo4j knowledge graph.
    Runs seed_graph.py logic directly.
    """
    try:
        import sys
        from pathlib import Path
        assets_scripts = Path(__file__).parent.parent / "Chaos_Platform_Assets" / "scripts"
        sys.path.insert(0, str(assets_scripts))
        from seed_neo4j import wait_for_neo4j, seed_knowledge_graph
        driver = wait_for_neo4j(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASS", "chaospassword"),
            timeout=10,
        )
        if clear:
            with driver.session() as s:
                s.run("MATCH (n) DETACH DELETE n")
        seed_knowledge_graph(driver)
        driver.close()
        return {"success": True, "message": "Knowledge graph seeded successfully"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j error: {e}")


# ─── GET /graph/nodes ────────────────────────────────────────────────────────

@app.get("/graph/nodes", tags=["Intelligence"])
async def graph_nodes():
    """Return Neo4j brain map data for dashboard rendering."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASS", "chaospassword"))
        )
        with driver.session() as session:
            svcs = list(session.run(
                "MATCH (s:Service) RETURN s.name AS name, s.criticality AS crit"
            ))
            edges = list(session.run(
                "MATCH (a:Service)-[:DEPENDS_ON]->(b:Service) RETURN a.name AS from, b.name AS to"
            ))
            strands = list(session.run(
                "MATCH (st:Strand)-[:BELONGS_TO]->(f:AttackFamily) "
                "RETURN st.id AS id, f.name AS family, st.avg_recovery_time_ms AS avg_ms"
            ))
        driver.close()
        return {
            "nodes": [dict(r) for r in svcs + strands],
            "edges": [dict(r) for r in edges],
        }
    except Exception as e:
        return JSONResponse({"nodes": [], "edges": [], "error": str(e)})


# ─── GET /health/services ────────────────────────────────────────────────────

@app.get("/health/services", tags=["System"])
async def service_health():
    """Return per-service health scores stored in Redis."""
    return {
        "scores":    redis_store.get_health_scores(),
        "timestamp": time.time(),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _check_k8s() -> bool:
    try:
        pods = k8s.list_pods(DARWIN_NS)
        return True  # list call succeeded
    except Exception:
        return False


async def _auto_recover_after(
    service: str, strand_id: str, attack_family: str, delay_s: int
):
    """Background task: auto-trigger recovery after delay_s seconds."""
    await asyncio.sleep(delay_s)
    logger.info(f"⏰ Auto-recovery triggered for {service} after {delay_s}s")
    recovery.recover(
        service=service,
        strand_id=strand_id,
        attack_family=attack_family,
        rf_confidence=0.90,
        anomaly_score=0.80,
    )


# ─── Entry point for direct run ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("darwin_api.main:app", host="0.0.0.0", port=9000, reload=True)
