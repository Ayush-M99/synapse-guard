"""
order-service — Order management
FastAPI / PostgreSQL (asyncpg)
Calls: payment-service, inventory-service
"""
import asyncio
import logging
import os
import random
import time
import uuid

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME   = os.getenv("SERVICE_NAME", "order-service")
DB_URL         = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@localhost:5432/chaos_dna")
PAYMENT_URL    = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service")
INVENTORY_URL  = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service")
PORT           = int(os.getenv("PORT", "8012"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

_reg = CollectorRegistry()
req_total       = Counter("http_requests_total", "Total requests",
                           ["method", "endpoint", "status"], registry=_reg)
req_latency     = Histogram("http_request_duration_seconds", "Latency",
                             ["endpoint"], registry=_reg)
orders_created  = Counter("orders_created_total", "Orders created", registry=_reg)
orders_failed   = Counter("orders_failed_total",  "Orders failed",  registry=_reg)
active_reqs     = Gauge("active_requests", "Active requests", registry=_reg)
downstream_errs = Counter("downstream_errors_total", "Downstream errors",
                          ["service"], registry=_reg)
cpu_sim         = Gauge("simulated_cpu_pct", "CPU %", registry=_reg)
mem_sim         = Gauge("simulated_mem_mb",  "Mem MB", registry=_reg)

app  = FastAPI(title=SERVICE_NAME)
_pool: asyncpg.Pool = None

@app.on_event("startup")
async def startup():
    global _pool
    try:
        _pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id         VARCHAR(36) PRIMARY KEY,
                    user_id    VARCHAR(100),
                    item_id    VARCHAR(100),
                    quantity   INT,
                    total      FLOAT,
                    status     VARCHAR(20) DEFAULT 'created',
                    created    TIMESTAMP DEFAULT NOW()
                )
            """)
        log.info("DB ready")
    except Exception as e:
        log.warning(f"DB unavailable: {e}")
    asyncio.create_task(_metrics_simulator())

@app.on_event("shutdown")
async def shutdown():
    if _pool: await _pool.close()

class OrderRequest(BaseModel):
    user_id:  str
    item_id:  str
    quantity: int = 1
    price:    float = 9.99

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "ts": time.time()}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.post("/order")
async def create_order(req: OrderRequest):
    start = time.time()
    active_reqs.inc()
    order_id = str(uuid.uuid4())
    try:
        total = req.quantity * req.price
        await asyncio.sleep(random.uniform(0.02, 0.06))

        # Call payment-service
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                await c.post(f"{PAYMENT_URL}/pay",
                             json={"order_id": order_id, "amount": total})
        except Exception as e:
            downstream_errs.labels(service="payment").inc()
            log.warning(f"Payment failed: {e}")

        # Persist order
        if _pool:
            async with _pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO orders (id, user_id, item_id, quantity, total) VALUES($1,$2,$3,$4,$5)",
                    order_id, req.user_id, req.item_id, req.quantity, total
                )

        orders_created.inc()
        _record_req("POST", "/order", "200", start)
        return {"order_id": order_id, "status": "created", "total": total}

    except Exception as e:
        orders_failed.inc()
        _record_req("POST", "/order", "500", start)
        raise HTTPException(500, str(e))
    finally:
        active_reqs.dec()

@app.get("/orders/{user_id}")
async def list_orders(user_id: str):
    start = time.time()
    try:
        if _pool:
            async with _pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM orders WHERE user_id=$1 LIMIT 20", user_id)
                _record_req("GET", "/orders/{id}", "200", start)
                return [dict(r) for r in rows]
        return []
    except Exception as e:
        _record_req("GET", "/orders/{id}", "500", start)
        raise HTTPException(500, str(e))

@app.post("/process")
async def process():
    active_reqs.inc()
    await asyncio.sleep(random.uniform(0.01, 0.04))
    active_reqs.dec()
    return {"processed": True}

def _record_req(method, endpoint, status, start):
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(time.time() - start)

async def _metrics_simulator():
    while True:
        cpu_sim.set(random.uniform(10, 35))
        mem_sim.set(random.uniform(60, 130))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
