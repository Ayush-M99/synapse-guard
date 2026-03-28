"""Inventory Service - Stock levels, backed by Redis."""
import os, time, random, asyncio, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SERVICE_NAME = "inventory-service"
app = FastAPI(title=SERVICE_NAME)

REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests",
    ["service", "method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency",
    ["service", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10])
ERROR_COUNT = Counter("http_errors_total", "Total HTTP 5xx errors",
    ["service", "endpoint"])
ACTIVE_REQUESTS = Gauge("active_requests", "Currently processing requests",
    ["service"])
STOCK_LEVEL = Gauge("inventory_stock_level", "Current stock level",
    ["service", "item"])

# Simulated inventory (Redis in production)
INVENTORY = {f"item_{i}": random.randint(50, 500) for i in range(1, 21)}
for item, qty in INVENTORY.items():
    STOCK_LEVEL.labels(service=SERVICE_NAME, item=item).set(qty)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/stock/{item_id}")
async def get_stock(item_id: str):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        await asyncio.sleep(random.uniform(0.005, 0.02))
        qty = INVENTORY.get(item_id, 0)
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET",
            endpoint="/stock", status="200").inc()
        return {"item_id": item_id, "quantity": qty}
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/stock").observe(time.time() - start)

@app.post("/reserve")
async def reserve(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        item_id = body.get("item_id", "item_1")
        qty = body.get("quantity", 1)

        # Inventory check with contention simulation
        data = [random.random() for _ in range(4000)]
        sorted(data)

        await asyncio.sleep(random.uniform(0.01, 0.04))

        current = INVENTORY.get(item_id, 0)
        if current < qty:
            STOCK_LEVEL.labels(service=SERVICE_NAME, item=item_id).set(current)
            raise HTTPException(status_code=409, detail="Insufficient stock")

        INVENTORY[item_id] = current - qty
        STOCK_LEVEL.labels(service=SERVICE_NAME, item=item_id).set(INVENTORY[item_id])

        REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST",
            endpoint="/reserve", status="200").inc()
        return {"item_id": item_id, "reserved": qty, "remaining": INVENTORY[item_id]}
    except HTTPException:
        raise
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/reserve").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/reserve").observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        data = [random.random() for _ in range(4000)]
        sorted(data)
        await asyncio.sleep(random.uniform(0.01, 0.04))
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST",
            endpoint="/process", status="200").inc()
        return {"processed": True, "service": SERVICE_NAME}
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/process").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/process").observe(time.time() - start)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8005))
    uvicorn.run(app, host="0.0.0.0", port=port)
