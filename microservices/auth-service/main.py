"""
auth-service — JWT authentication
FastAPI / PostgreSQL (asyncpg)
Exposes: /health /metrics /register /login /verify
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta

import asyncpg
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST,
    REGISTRY, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "auth-service")
DB_URL       = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@localhost:5432/chaos_dna")
JWT_SECRET   = os.getenv("JWT_SECRET",   "darwin-secret-key-2024")
PORT         = int(os.getenv("PORT", "8010"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
_reg = CollectorRegistry()
req_total   = Counter("http_requests_total", "Total HTTP requests",
                       ["method", "endpoint", "status"], registry=_reg)
req_latency = Histogram("http_request_duration_seconds", "Request latency",
                         ["endpoint"], registry=_reg)
active_reqs = Gauge("active_requests", "Active requests currently processing", registry=_reg)
db_errors   = Counter("db_errors_total", "DB connection errors", registry=_reg)
cpu_sim     = Gauge("simulated_cpu_pct", "Simulated CPU usage %", registry=_reg)
mem_sim     = Gauge("simulated_mem_mb",  "Simulated memory MB",  registry=_reg)

app = FastAPI(title=SERVICE_NAME)
_pool: asyncpg.Pool = None

# ── Startup / Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global _pool
    try:
        _pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id       SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(200) NOT NULL,
                    created  TIMESTAMP DEFAULT NOW()
                )
            """)
        log.info("DB pool ready")
    except Exception as e:
        log.warning(f"DB unavailable: {e} — running in degraded mode")

    # Seed metrics background task
    asyncio.create_task(_metrics_simulator())

@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()

# ── Endpoints ─────────────────────────────────────────────────────────────────
class UserCreds(BaseModel):
    username: str
    password: str

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "ts": time.time()}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.post("/register")
async def register(creds: UserCreds):
    start = time.time()
    active_reqs.inc()
    try:
        hashed = _hash_password(creds.password)
        if _pool:
            async with _pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (username, password) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    creds.username, hashed
                )
        await asyncio.sleep(random.uniform(0.02, 0.08))
        _record_req("POST", "/register", "200", start)
        return {"registered": True, "username": creds.username}
    except Exception as e:
        _record_req("POST", "/register", "500", start)
        db_errors.inc()
        raise HTTPException(500, str(e))
    finally:
        active_reqs.dec()

@app.post("/login")
async def login(creds: UserCreds):
    start = time.time()
    active_reqs.inc()
    try:
        await asyncio.sleep(random.uniform(0.01, 0.05))
        token = _make_token(creds.username)
        _record_req("POST", "/login", "200", start)
        return {"token": token, "expires_in": 3600}
    except Exception as e:
        _record_req("POST", "/login", "500", start)
        raise HTTPException(500, str(e))
    finally:
        active_reqs.dec()

@app.get("/verify")
async def verify(authorization: str = Header(None)):
    start = time.time()
    try:
        if not authorization or not authorization.startswith("Bearer "):
            _record_req("GET", "/verify", "401", start)
            raise HTTPException(401, "No token")
        token = authorization.split(" ")[1]
        sub = _verify_token(token)
        if not sub:
            _record_req("GET", "/verify", "401", start)
            raise HTTPException(401, "Invalid token")
        _record_req("GET", "/verify", "200", start)
        return {"valid": True, "subject": sub}
    except HTTPException:
        raise

@app.post("/process")
async def process():
    """CPU-intensive endpoint — used by Locust for realistic load."""
    start = time.time()
    active_reqs.inc()
    # Simulate realistic CPU work
    _ = hashlib.sha256((str(time.time()) * 100).encode()).hexdigest()
    await asyncio.sleep(random.uniform(0.01, 0.05))
    active_reqs.dec()
    _record_req("POST", "/process", "200", start)
    return {"processed": True}

# ── Helpers ───────────────────────────────────────────────────────────────────
def _hash_password(pw: str) -> str:
    return hmac.new(JWT_SECRET.encode(), pw.encode(), hashlib.sha256).hexdigest()

def _make_token(subject: str) -> str:
    payload = json.dumps({"sub": subject, "exp": time.time() + 3600})
    sig = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    import base64
    return base64.b64encode(payload.encode()).decode() + "." + sig

def _verify_token(token: str):
    try:
        import base64
        parts = token.split(".")
        payload = json.loads(base64.b64decode(parts[0]).decode())
        if payload["exp"] < time.time():
            return None
        return payload["sub"]
    except Exception:
        return None

def _record_req(method, endpoint, status, start):
    elapsed = time.time() - start
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(elapsed)

async def _metrics_simulator():
    """Simulate realistic CPU/mem usage so Prometheus has meaningful data."""
    while True:
        cpu_sim.set(random.uniform(15, 40))
        mem_sim.set(random.uniform(60, 120))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
