"""Notification Service - Sends alerts."""
import os, time, random, asyncio, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SERVICE_NAME = "notification-service"
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
NOTIFICATIONS_SENT = Counter("notifications_sent_total",
    "Total notifications sent", ["service", "channel"])

NOTIFICATION_LOG = []

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/ready")
async def ready():
    return {"ready": True, "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/send")
async def send_notification(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        body = await request.json()
        channel = body.get("channel", "email")
        message = body.get("message", "System notification")

        # Template rendering simulation
        template_data = [random.random() for _ in range(3000)]
        sorted(template_data)

        # Simulate external API call (email/SMS provider)
        await asyncio.sleep(random.uniform(0.05, 0.20))

        notification = {
            "id": f"notif_{int(time.time())}_{random.randint(1000,9999)}",
            "channel": channel, "message": message,
            "status": "sent", "timestamp": time.time()
        }
        NOTIFICATION_LOG.append(notification)
        NOTIFICATIONS_SENT.labels(service=SERVICE_NAME, channel=channel).inc()

        REQUEST_COUNT.labels(service=SERVICE_NAME, method="POST",
            endpoint="/send", status="200").inc()
        return notification
    except Exception as e:
        ERROR_COUNT.labels(service=SERVICE_NAME, endpoint="/send").inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.labels(service=SERVICE_NAME).dec()
        REQUEST_LATENCY.labels(service=SERVICE_NAME,
            endpoint="/send").observe(time.time() - start)

@app.post("/process")
async def process(request: Request):
    start = time.time()
    ACTIVE_REQUESTS.labels(service=SERVICE_NAME).inc()
    try:
        data = [random.random() for _ in range(2000)]
        sorted(data)
        await asyncio.sleep(random.uniform(0.01, 0.05))
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
    port = int(os.environ.get("PORT", 8006))
    uvicorn.run(app, host="0.0.0.0", port=port)
