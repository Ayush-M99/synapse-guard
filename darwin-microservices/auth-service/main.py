"""Auth Service - JWT login/signup backed by PostgreSQL."""
import os, time, random, asyncio, hashlib, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SERVICE_NAME = "auth-service"
app = FastAPI(title=SERVICE_NAME)

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests",
    ["service", "method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency",
    ["service", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
)
ERROR_COUNT = Counter(
    "http_errors_total", "Total HTTP 5xx errors",
    ["service", "endpoint"]
)
ACTIVE_REQUESTS = Gauge(
    "active_requests", "Currently processing requests",
    ["service"]
)
CPU_INTENSIVE_OPS = Counter(
    "cpu_intensive_operations_total", "CPU intensive operations performed",
    ["service"]
)

# Simulated user store
USERS = {}

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/signup")
async def signup(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        username = body.get("username", f"user_{random.randint(1000,9999)}")
        password = body.get("password", "password123")

        # CPU-intensive: hash password multiple rounds (shows in Prometheus)
        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        CPU_INTENSIVE_OPS.labels(service=SERVICE_NAME).inc()

        # Simulate DB write latency
        await asyncio.sleep(random.uniform(0.02, 0.08))

        token = hashlib.sha256(f"{username}{time.time()}".encode()).hexdigest()[:32]
        USERS[username] = {"password_hash": key.hex(), "salt": salt.hex()}

        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST",
            endpoint="/signup", status="200"
        ).inc()
        return {"token": token, "username": username, "status": "created"}
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/signup").inc()
        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST",
            endpoint="/signup", status="500"
        ).inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(
            service=SERVICE_NAME, endpoint="/signup"
        ).observe(time.time() - start)

@app.post("/login")
async def login(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        username = body.get("username", "testuser")
        password = body.get("password", "password123")

        # CPU-intensive: verify password hash
        salt = os.urandom(32)
        hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 50000)
        CPU_INTENSIVE_OPS.labels(service=SERVICE_NAME).inc()

        await asyncio.sleep(random.uniform(0.01, 0.05))

        token = hashlib.sha256(f"{username}{time.time()}".encode()).hexdigest()[:32]

        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST",
            endpoint="/login", status="200"
        ).inc()
        return {"token": token, "username": username}
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/login").inc()
        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST",
            endpoint="/login", status="500"
        ).inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(
            service=SERVICE_NAME, endpoint="/login"
        ).observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        # Do CPU + memory work so attacks register in Prometheus
        data = [random.random() for _ in range(5000)]
        sorted_data = sorted(data)
        hashlib.sha256(json.dumps(sorted_data[:100]).encode()).hexdigest()
        CPU_INTENSIVE_OPS.labels(service=SERVICE_NAME).inc()

        await asyncio.sleep(random.uniform(0.01, 0.05))

        REQUEST_COUNT.labels(
            service=SERVICE_NAME, method="POST",
            endpoint="/process", status="200"
        ).inc()
        return {"processed": True, "service": SERVICE_NAME}
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/process").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(
            service=SERVICE_NAME, endpoint="/process"
        ).observe(time.time() - start)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
