"""Order Service - Creates and tracks orders, backed by PostgreSQL."""
import os, time, random, asyncio, json, uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SERVICE_NAME = "order-service"
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
ORDERS_CREATED = Counter("orders_created_total", "Total orders created",
    ["service"])

# In-memory order store (simulating PostgreSQL)
ORDERS = {}

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/create")
async def create_order(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        order_id = str(uuid.uuid4())

        # Simulate order validation (CPU work)
        items = body.get("items", [{"id": "item1", "qty": 1, "price": 29.99}])
        total = sum(item.get("price", 0) * item.get("qty", 1) for item in items)

        # Heavier computation — order risk scoring
        risk_data = [random.random() for _ in range(8000)]
        risk_score = sum(risk_data) / len(risk_data)
        sorted(risk_data)

        # Simulate DB write
        await asyncio.sleep(random.uniform(0.03, 0.10))

        order = {
            "order_id": order_id, "items": items, "total": total,
            "risk_score": round(risk_score, 4), "status": "created",
            "created_at": time.time()
        }
        ORDERS[order_id] = order
        ORDERS_CREATED.labels(service=SERVICE_NAME).inc()

        REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST",
            endpoint="/create", status="200").inc()
        return order
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/create").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/create").observe(time.time() - start)

@app.get("/order/{order_id}")
async def get_order(order_id: str):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        await asyncio.sleep(random.uniform(0.005, 0.02))
        order = ORDERS.get(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        REQUEST_COUNT.labels(service=SERVICE_NAME, method="GET",
            endpoint="/order", status="200").inc()
        return order
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/order").observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        data = [random.random() for _ in range(6000)]
        sorted(data)
        await asyncio.sleep(random.uniform(0.02, 0.06))
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
    port = int(os.environ.get("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
