"""
DARWIN WebSocket Bridge
FastAPI server that:
  1. Bridges NATS → WebSocket (real-time events to dashboard)
  2. Exposes REST API for DNA replay, graph nodes, system status
  3. Exposes /metrics for Prometheus scraping

NATS subjects bridged:
  brain.update, brain.rf_classified, lstm.prediction,
  virus.inject, services.health, antibody.recovery_complete
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import nats
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from neo4j import AsyncGraphDatabase
from prometheus_client import (
    Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WS-BRIDGE] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
NATS_URL    = os.getenv("NATS_URL",    "nats://localhost:4222")
PG_URL      = os.getenv("PG_URL",     "postgres://chaos:chaospassword@localhost:5432/chaos_dna")
NEO4J_URI   = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER  = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS  = os.getenv("NEO4J_PASS", "chaospassword")

# Prometheus metrics
ws_clients_g      = Gauge("darwin_ws_clients",         "Active WebSocket clients")
events_forwarded  = Counter("darwin_ws_events_total",  "Events forwarded to dashboard", ["subject"])

# ─── Global state ─────────────────────────────────────────────────────────────
_connected_ws: list[WebSocket] = []
_nc: Optional[nats.NATS]       = None
_pg_pool: Optional[asyncpg.Pool] = None
_neo4j_driver                  = None


# ─── App lifecycle ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _nc, _pg_pool, _neo4j_driver
    logger.info("🚀 WS Bridge starting up...")

    # Connect NATS
    try:
        _nc = await nats.connect(NATS_URL)
        logger.info(f"✅ NATS connected: {NATS_URL}")
        asyncio.create_task(_nats_subscriber())
    except Exception as e:
        logger.error(f"⚠️  NATS unavailable: {e} — dashboard will show no events")

    # Connect PostgreSQL
    try:
        _pg_pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=5)
        await _ensure_dna_schema(_pg_pool)
        logger.info("✅ PostgreSQL connected")
    except Exception as e:
        logger.error(f"⚠️  PostgreSQL unavailable: {e}")

    # Connect Neo4j
    try:
        _neo4j_driver = AsyncGraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS)
        )
        logger.info("✅ Neo4j connected")
    except Exception as e:
        logger.error(f"⚠️  Neo4j unavailable: {e}")

    yield  # ← app runs here

    logger.info("🛑 WS Bridge shutting down...")
    if _nc:       await _nc.drain()
    if _pg_pool:  await _pg_pool.close()
    if _neo4j_driver: await _neo4j_driver.close()


app = FastAPI(title="DARWIN WS Bridge", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── NATS → WebSocket fan-out ─────────────────────────────────────────────────

BRIDGE_SUBJECTS = [
    "brain.update",
    "brain.rf_classified",
    "lstm.prediction",
    "virus.inject",
    "services.health",
    "antibody.recovery_complete",
]


async def _nats_subscriber():
    """Subscribe to all NATS subjects and fan-out to connected WS clients."""
    if not _nc:
        return

    async def _forward(msg):
        subject = msg.subject
        try:
            data = json.loads(msg.data.decode())
            data["_subject"] = subject
            data["_received_at"] = datetime.now(timezone.utc).isoformat()
            events_forwarded.labels(subject=subject).inc()
            await _broadcast(data)
        except Exception as e:
            logger.error(f"Forward error on {subject}: {e}")

    for subject in BRIDGE_SUBJECTS:
        await _nc.subscribe(subject, cb=_forward)
        logger.info(f"📡 Subscribed to NATS: {subject}")


async def _broadcast(payload: dict):
    """Send JSON payload to all connected WebSocket clients."""
    if not _connected_ws:
        return
    text = json.dumps(payload)
    dead = []
    for ws in _connected_ws:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connected_ws.remove(ws)
        ws_clients_g.dec()


# ─── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connected_ws.append(websocket)
    ws_clients_g.inc()
    logger.info(f"🔌 WS client connected. Total: {len(_connected_ws)}")

    # Send initial system state
    try:
        await websocket.send_text(json.dumps({
            "event": "connected",
            "system": "darwin",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        pass

    try:
        while True:
            await websocket.receive_text()   # keep connection alive; client sends pings
    except WebSocketDisconnect:
        _connected_ws.remove(websocket)
        ws_clients_g.dec()
        logger.info(f"🔌 WS client disconnected. Total: {len(_connected_ws)}")


# ─── REST API ─────────────────────────────────────────────────────────────────

@app.get("/api/graph/nodes")
async def get_graph_nodes():
    """Return Neo4j brain graph for initial dashboard render."""
    if not _neo4j_driver:
        return JSONResponse({"nodes": [], "edges": [], "error": "Neo4j not connected"})
    try:
        async with _neo4j_driver.session() as session:
            # Services
            svc_result = await session.run(
                "MATCH (s:Service) RETURN s.name AS name, s.criticality AS crit, s.recovery_priority AS prio"
            )
            services = [dict(r) async for r in svc_result]

            # Dependency edges
            dep_result = await session.run(
                "MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) RETURN a.name AS from, b.name AS to"
            )
            deps = [dict(r) async for r in dep_result]

            # Attack families
            fam_result = await session.run(
                "MATCH (f:AttackFamily) RETURN f.name AS name, f.generation AS gen"
            )
            families = [dict(r) async for r in fam_result]

            # Strands
            strand_result = await session.run(
                "MATCH (st:Strand)-[:BELONGS_TO]->(f:AttackFamily) "
                "RETURN st.id AS id, f.name AS family, st.generation AS gen, st.avg_recovery_time_ms AS avg_ms"
            )
            strands = [dict(r) async for r in strand_result]

        nodes = (
            [{"id": s["name"], "type": "service", **s} for s in services] +
            [{"id": f["name"], "type": "family",  **f} for f in families]  +
            [{"id": s["id"],   "type": "strand",  **s} for s in strands]
        )
        return {"nodes": nodes, "edges": deps}
    except Exception as e:
        logger.error(f"Graph query error: {e}")
        return JSONResponse({"nodes": [], "edges": [], "error": str(e)})


@app.get("/api/dna/replay/{gen}")
async def get_dna_replay(gen: int):
    """Return all DNA log events for a generation (for DNA Replay panel)."""
    if not _pg_pool:
        return JSONResponse({"events": [], "error": "PostgreSQL not connected"})
    try:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT virus_gen, antibody_gen, strand_id, service,
                       playbook_id, recovery_time_ms, success, timestamp
                FROM dna_log
                WHERE virus_gen = $1
                ORDER BY timestamp ASC
                """,
                gen,
            )
        events = [dict(r) for r in rows]
        # Add relative ms offset for replay animation
        if events:
            t0 = events[0]["timestamp"].timestamp() * 1000
            for e in events:
                e["relative_timestamp_ms"] = e["timestamp"].timestamp() * 1000 - t0
                e["timestamp"] = e["timestamp"].isoformat()
        return {"events": events, "generation": gen}
    except Exception as e:
        logger.error(f"DNA replay error: {e}")
        return JSONResponse({"events": [], "error": str(e)})


@app.get("/api/dna/stats")
async def get_dna_stats():
    """Return per-generation stats for the Evolutionary Timeline chart."""
    if not _pg_pool:
        return JSONResponse({"generations": [], "error": "PostgreSQL not connected"})
    try:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    virus_gen AS gen,
                    COUNT(*) AS total,
                    AVG(recovery_time_ms) AS avg_recovery_ms,
                    SUM(CASE WHEN success THEN 0 ELSE 1 END)::float / COUNT(*) AS unknown_rate,
                    MIN(timestamp) AS started_at
                FROM dna_log
                GROUP BY virus_gen
                ORDER BY virus_gen ASC
                """
            )
        return {"generations": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"DNA stats error: {e}")
        return JSONResponse({"generations": [], "error": str(e)})


@app.get("/api/immunity/cache")
async def get_immunity_cache():
    """Return Redis T-cell memory contents (for status display)."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
        keys = await r.keys("immunity:*")
        cache = {}
        for k in keys:
            v = await r.get(k)
            cache[k] = json.loads(v) if v else None
        await r.aclose()
        return {"immunity_cache": cache, "count": len(keys)}
    except Exception as e:
        return JSONResponse({"immunity_cache": {}, "error": str(e)})


@app.get("/api/system/status")
async def system_status():
    """Health check for all connected DARWIN components."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ws_clients": len(_connected_ws),
        "nats": {"connected": bool(_nc and not _nc.is_closed)},
        "postgres": {"connected": bool(_pg_pool and not _pg_pool._closed)},
        "neo4j": {"connected": bool(_neo4j_driver)},
    }
    return status


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ws-bridge"}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        generate_latest().decode(), media_type=CONTENT_TYPE_LATEST
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _ensure_dna_schema(pool: asyncpg.Pool):
    """Create DNA log table if not exists (idempotent)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dna_log (
                id               SERIAL PRIMARY KEY,
                virus_gen        INTEGER,
                antibody_gen     INTEGER,
                strand_id        VARCHAR(100),
                service          VARCHAR(100),
                playbook_id      VARCHAR(100),
                recovery_time_ms FLOAT,
                success          BOOLEAN,
                timestamp        TIMESTAMP DEFAULT NOW()
            )
        """)
