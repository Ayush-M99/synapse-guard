"""API Gateway - Routes all external traffic."""
import os, time, random, asyncio, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
import httpx

SERVICE_NAME = "api-gateway"
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
UPSTREAM_LATENCY = Histogram("upstream_request_duration_seconds",
    "Upstream service call latency", ["service", "upstream"])

# Service registry
SERVICES = {
    "auth": os.environ.get("AUTH_SERVICE_URL", "http://auth-service:8001"),
    "order": os.environ.get("ORDER_SERVICE_URL", "http://order-service:8003"),
    "payment": os.environ.get("PAYMENT_SERVICE_URL", "http://payment-service:8004"),
    "inventory": os.environ.get("INVENTORY_SERVICE_URL", "http://inventory-service:8005"),
    "notification": os.environ.get("NOTIFICATION_SERVICE_URL", "http://notification-service:8006"),
}

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.api_route("/api/{service_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_request(service_name: str, path: str, request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        if service_name not in SERVICES:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")

        upstream_url = f"{SERVICES[service_name]}/{path}"
        upstream_start = time.time()

        async with httpx.AsyncClient(timeout=10.0) as client:
            body = await request.body()
            resp = await client.request(
                method=request.method, url=upstream_url,
                content=body, headers={"Content-Type": "application/json"}
            )

        UPSTREAM_LATENCY.labels(service=SERVICE_NAME, upstream=service_name).observe(
            time.time() - upstream_start)

        REQUEST_COUNT.labels(service=SERVICE_NAME, method=request.method,
            endpoint=f"/api/{service_name}", status=str(resp.status_code)).inc()
        return Response(content=resp.content, status_code=resp.status_code,
                       media_type="application/json")
    except httpx.RequestError as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint=f"/api/{service_name}").inc()
        REQUEST_COUNT.labels(service=SERVICE_NAME, method=request.method,
            endpoint=f"/api/{service_name}", status="502").inc()
        raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint=f"/api/{service_name}").observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        # Route to a random downstream service
        data = [random.random() for _ in range(3000)]
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
    port = int(os.environ.get("PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
