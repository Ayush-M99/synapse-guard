"""
api-gateway — Routes all external traffic to downstream services
FastAPI — no DB, just routing + load stats
"""
import asyncio
import logging
import os
import random
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME  = os.getenv("SERVICE_NAME", "api-gateway")
AUTH_URL      = os.getenv("AUTH_SERVICE_URL",      "http://auth-service")
ORDER_URL     = os.getenv("ORDER_SERVICE_URL",     "http://order-service")
PAYMENT_URL   = os.getenv("PAYMENT_SERVICE_URL",   "http://payment-service")
INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service")
PORT          = int(os.getenv("PORT", "8011"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

_reg = CollectorRegistry()
req_total     = Counter("http_requests_total", "Total requests",
                        ["method", "endpoint", "status"], registry=_reg)
req_latency   = Histogram("http_request_duration_seconds", "Latency",
                          ["endpoint"], registry=_reg)
upstream_errs = Counter("upstream_errors_total", "Upstream errors",
                        ["service"], registry=_reg)
active_reqs   = Gauge("active_requests", "Active requests", registry=_reg)
cpu_sim       = Gauge("simulated_cpu_pct", "CPU %", registry=_reg)
mem_sim       = Gauge("simulated_mem_mb",  "Mem MB", registry=_reg)

app = FastAPI(title=SERVICE_NAME)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

class OrderReq(BaseModel):
    user_id: str
    item_id: str
    quantity: int = 1
    price:    float = 9.99

@app.on_event("startup")
async def startup():
    asyncio.create_task(_metrics_simulator())

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "ts": time.time()}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.post("/api/login")
async def proxy_login(creds: dict):
    return await _proxy("POST", AUTH_URL, "/login", creds, "/api/login")

@app.post("/api/register")
async def proxy_register(creds: dict):
    return await _proxy("POST", AUTH_URL, "/register", creds, "/api/register")

@app.post("/api/order")
async def proxy_order(req: OrderReq):
    return await _proxy("POST", ORDER_URL, "/order", req.dict(), "/api/order")

@app.post("/api/pay")
async def proxy_pay(req: dict):
    return await _proxy("POST", PAYMENT_URL, "/pay", req, "/api/pay")

@app.get("/api/stock/{item_id}")
async def proxy_stock(item_id: str):
    return await _proxy("GET", INVENTORY_URL, f"/stock/{item_id}", None, "/api/stock/{id}")

@app.get("/api/catalog")
async def proxy_catalog():
    return await _proxy("GET", INVENTORY_URL, "/catalog", None, "/api/catalog")

@app.post("/process")
async def process():
    """Locust direct load endpoint on gateway."""
    active_reqs.inc()
    await asyncio.sleep(random.uniform(0.005, 0.02))
    active_reqs.dec()
    return {"processed": True}

async def _proxy(method: str, base: str, path: str, body, endpoint_label: str):
    start = time.time()
    active_reqs.inc()
    svc = base.split("//")[-1].split(":")[0]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            if method == "POST":
                resp = await c.post(f"{base}{path}", json=body)
            else:
                resp = await c.get(f"{base}{path}")
        _record_req(method, endpoint_label, str(resp.status_code), start)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        upstream_errs.labels(service=svc).inc()
        _record_req(method, endpoint_label, "504", start)
        raise HTTPException(504, f"Timeout calling {svc}")
    except Exception as e:
        upstream_errs.labels(service=svc).inc()
        _record_req(method, endpoint_label, "502", start)
        raise HTTPException(502, str(e))
    finally:
        active_reqs.dec()

def _record_req(method, endpoint, status, start):
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(time.time() - start)

async def _metrics_simulator():
    while True:
        cpu_sim.set(random.uniform(25, 60))
        mem_sim.set(random.uniform(50, 100))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
