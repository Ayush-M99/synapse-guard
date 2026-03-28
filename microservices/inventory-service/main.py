"""
inventory-service — Stock level management (Redis-backed)
FastAPI / Redis
"""
import asyncio
import logging
import os
import random
import time

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "inventory-service")
REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379")
PORT         = int(os.getenv("PORT", "8014"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

_reg = CollectorRegistry()
req_total   = Counter("http_requests_total", "Total requests",
                       ["method", "endpoint", "status"], registry=_reg)
req_latency = Histogram("http_request_duration_seconds", "Latency",
                         ["endpoint"], registry=_reg)
cache_hits  = Counter("cache_hits_total",   "Cache hits",   registry=_reg)
cache_miss  = Counter("cache_misses_total", "Cache misses", registry=_reg)
active_reqs = Gauge("active_requests", "Active requests", registry=_reg)
cpu_sim     = Gauge("simulated_cpu_pct", "CPU %", registry=_reg)
mem_sim     = Gauge("simulated_mem_mb",  "Mem MB", registry=_reg)

app = FastAPI(title=SERVICE_NAME)
_redis = None

# Seed inventory
ITEMS = {f"item_{i:03d}": random.randint(50, 500) for i in range(1, 50)}

@app.on_event("startup")
async def startup():
    global _redis
    try:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        # Seed stock levels
        for item_id, qty in ITEMS.items():
            await _redis.set(f"inventory:{item_id}", qty)
        log.info("Redis ready, inventory seeded")
    except Exception as e:
        log.warning(f"Redis unavailable: {e}")
    asyncio.create_task(_metrics_simulator())

@app.on_event("shutdown")
async def shutdown():
    if _redis:
        await _redis.aclose()

@app.get("/health")
async def health():
    redis_ok = False
    if _redis:
        try:
            await _redis.ping()
            redis_ok = True
        except Exception:
            pass
    return {"status": "ok" if redis_ok else "degraded",
            "service": SERVICE_NAME, "redis": redis_ok}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.get("/stock/{item_id}")
async def get_stock(item_id: str):
    start = time.time()
    active_reqs.inc()
    try:
        await asyncio.sleep(random.uniform(0.005, 0.02))
        if _redis:
            cached = await _redis.get(f"inventory:{item_id}")
            if cached is not None:
                cache_hits.inc()
                _record_req("GET", "/stock/{id}", "200", start)
                return {"item_id": item_id, "quantity": int(cached), "source": "cache"}
        cache_miss.inc()
        qty = ITEMS.get(item_id, 0)
        _record_req("GET", "/stock/{id}", "200", start)
        return {"item_id": item_id, "quantity": qty, "source": "fallback"}
    except Exception as e:
        _record_req("GET", "/stock/{id}", "500", start)
        raise HTTPException(500, str(e))
    finally:
        active_reqs.dec()

@app.post("/reserve/{item_id}")
async def reserve_stock(item_id: str, qty: int = 1):
    start = time.time()
    active_reqs.inc()
    try:
        if _redis:
            current = int(await _redis.get(f"inventory:{item_id}") or 0)
            if current < qty:
                _record_req("POST", "/reserve/{id}", "409", start)
                raise HTTPException(409, "Insufficient stock")
            await _redis.decrby(f"inventory:{item_id}", qty)
        _record_req("POST", "/reserve/{id}", "200", start)
        return {"reserved": qty, "item_id": item_id}
    except HTTPException:
        raise
    except Exception as e:
        _record_req("POST", "/reserve/{id}", "500", start)
        raise HTTPException(500, str(e))
    finally:
        active_reqs.dec()

@app.get("/catalog")
async def catalog():
    if _redis:
        keys = await _redis.keys("inventory:*")
        result = {}
        for k in keys[:20]:
            result[k.split(":")[1]] = int(await _redis.get(k) or 0)
        return {"items": result, "count": len(keys)}
    return {"items": ITEMS, "count": len(ITEMS)}

@app.post("/process")
async def process():
    active_reqs.inc()
    await asyncio.sleep(random.uniform(0.005, 0.02))
    active_reqs.dec()
    return {"processed": True}

def _record_req(method, endpoint, status, start):
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(time.time() - start)

async def _metrics_simulator():
    while True:
        cpu_sim.set(random.uniform(5, 25))
        mem_sim.set(random.uniform(40, 80))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
