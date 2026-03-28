"""Payment Service - Processes payments, backed by PostgreSQL."""
import os, time, random, asyncio, json, uuid, hashlib
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SERVICE_NAME = "payment-service"
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
PAYMENTS_PROCESSED = Counter("payments_processed_total",
    "Total payments processed", ["service", "status"])

TRANSACTIONS = {}

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/charge")
async def charge(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        tx_id = str(uuid.uuid4())
        amount = body.get("amount", round(random.uniform(10, 500), 2))

        # Heavy fraud detection simulation (CPU intensive)
        for _ in range(3):
            fraud_features = [random.random() for _ in range(10000)]
            fraud_score = sum(fraud_features) / len(fraud_features)
            hashlib.sha256(json.dumps(fraud_features[:500]).encode()).hexdigest()

        # Simulate payment gateway latency
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Random failure (simulates real payment failures)
        if random.random() < 0.02:
            PAYMENTS_PROCESSED.labels(service=SERVICE_NAME, status="failed").inc()
            ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/charge").inc()
            raise HTTPException(status_code=500, detail="Payment gateway timeout")

        tx = {
            "transaction_id": tx_id, "amount": amount,
            "fraud_score": round(fraud_score, 4), "status": "completed",
            "timestamp": time.time()
        }
        TRANSACTIONS[tx_id] = tx
        PAYMENTS_PROCESSED.labels(service=SERVICE_NAME, status="success").inc()

        REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST",
            endpoint="/charge", status="200").inc()
        return tx
    except HTTPException:
        raise
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/charge").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/charge").observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        data = [random.random() for _ in range(7000)]
        sorted(data)
        hashlib.sha256(str(data[:200]).encode()).hexdigest()
        await asyncio.sleep(random.uniform(0.02, 0.08))
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
    port = int(os.environ.get("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port)
