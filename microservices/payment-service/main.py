"""
payment-service — Payment processing
FastAPI / PostgreSQL (asyncpg)
Exposes: /health /metrics /pay /status/{id}
"""
import asyncio
import hashlib
import logging
import os
import random
import time
import uuid

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "payment-service")
DB_URL       = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@localhost:5432/chaos_dna")
PORT         = int(os.getenv("PORT", "8013"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

_reg = CollectorRegistry()
req_total   = Counter("http_requests_total", "Total requests",
                       ["method", "endpoint", "status"], registry=_reg)
req_latency = Histogram("http_request_duration_seconds", "Latency",
                         ["endpoint"], registry=_reg)
pay_total   = Counter("payments_total", "Payments processed",
                       ["status"], registry=_reg)
active_reqs = Gauge("active_requests", "Active requests", registry=_reg)
cpu_sim     = Gauge("simulated_cpu_pct", "Simulated CPU %", registry=_reg)
mem_sim     = Gauge("simulated_mem_mb", "Simulated mem MB", registry=_reg)

app  = FastAPI(title=SERVICE_NAME)
_pool: asyncpg.Pool = None

@app.on_event("startup")
async def startup():
    global _pool
    try:
        _pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id        VARCHAR(36) PRIMARY KEY,
                    order_id  VARCHAR(36),
                    amount    FLOAT,
                    status    VARCHAR(20) DEFAULT 'pending',
                    created   TIMESTAMP DEFAULT NOW()
                )
            """)
        log.info("DB pool ready")
    except Exception as e:
        log.warning(f"DB unavailable: {e}")
    asyncio.create_task(_metrics_simulator())

@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()

class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "USD"

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "ts": time.time()}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.post("/pay")
async def pay(req: PaymentRequest):
    start = time.time()
    active_reqs.inc()
    pay_id = str(uuid.uuid4())
    try:
        # Simulate payment processing (CPU-intensive hash)
        _ = hashlib.sha256((req.order_id * 50).encode()).hexdigest()
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Simulate 2% failure rate
        if random.random() < 0.02:
            pay_total.labels(status="failed").inc()
            _record_req("POST", "/pay", "500", start)
            raise HTTPException(500, "Payment gateway error")

        if _pool:
            async with _pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO payments (id, order_id, amount, status) VALUES ($1,$2,$3,'completed')",
                    pay_id, req.order_id, req.amount
                )

        pay_total.labels(status="completed").inc()
        _record_req("POST", "/pay", "200", start)
        return {"payment_id": pay_id, "status": "completed", "amount": req.amount}

    except HTTPException:
        raise
    except Exception as e:
        _record_req("POST", "/pay", "500", start)
        log.error(f"Payment error: {e}")
        raise HTTPException(500, "Internal error")
    finally:
        active_reqs.dec()

@app.get("/status/{pay_id}")
async def payment_status(pay_id: str):
    start = time.time()
    try:
        if _pool:
            async with _pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM payments WHERE id=$1", pay_id)
                if row:
                    _record_req("GET", "/status/{id}", "200", start)
                    return dict(row)
        _record_req("GET", "/status/{id}", "404", start)
        raise HTTPException(404, "Payment not found")
    except HTTPException:
        raise
    except Exception as e:
        _record_req("GET", "/status/{id}", "500", start)
        raise HTTPException(500, str(e))

@app.post("/process")
async def process():
    """Locust load endpoint."""
    start = time.time()
    active_reqs.inc()
    _ = hashlib.sha256((str(random.random()) * 200).encode()).hexdigest()
    await asyncio.sleep(random.uniform(0.02, 0.08))
    active_reqs.dec()
    _record_req("POST", "/process", "200", start)
    return {"processed": True}

def _record_req(method, endpoint, status, start):
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(time.time() - start)

async def _metrics_simulator():
    while True:
        cpu_sim.set(random.uniform(20, 55))  # payment-service is CPU heavier
        mem_sim.set(random.uniform(80, 180))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
