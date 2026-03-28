"""
notification-service — Alert / notification dispatcher
FastAPI — no DB, lightweight event emitter
"""
import asyncio
import logging
import os
import random
import time

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from pydantic import BaseModel

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
PORT         = int(os.getenv("PORT", "8015"))

logging.basicConfig(level=logging.INFO, format=f"[{SERVICE_NAME}] %(message)s")
log = logging.getLogger(__name__)

_reg          = CollectorRegistry()
req_total     = Counter("http_requests_total", "Total requests",
                        ["method", "endpoint", "status"], registry=_reg)
req_latency   = Histogram("http_request_duration_seconds", "Latency",
                          ["endpoint"], registry=_reg)
notifs_sent   = Counter("notifications_sent_total", "Notifications sent",
                        ["channel"], registry=_reg)
active_reqs   = Gauge("active_requests", "Active requests", registry=_reg)
cpu_sim       = Gauge("simulated_cpu_pct", "CPU %", registry=_reg)
mem_sim       = Gauge("simulated_mem_mb",  "Mem MB", registry=_reg)

app = FastAPI(title=SERVICE_NAME)
_notification_log: list[dict] = []

class NotificationRequest(BaseModel):
    user_id:  str
    event:    str
    message:  str
    channel:  str = "email"  # email | sms | push

@app.on_event("startup")
async def startup():
    asyncio.create_task(_metrics_simulator())

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(_reg), media_type=CONTENT_TYPE_LATEST)

@app.post("/notify")
async def send_notification(req: NotificationRequest):
    start = time.time()
    active_reqs.inc()
    try:
        await asyncio.sleep(random.uniform(0.01, 0.03))
        notif = {
            "id":        len(_notification_log) + 1,
            "user_id":   req.user_id,
            "event":     req.event,
            "message":   req.message,
            "channel":   req.channel,
            "sent_at":   time.time(),
            "status":    "delivered",
        }
        _notification_log.append(notif)
        if len(_notification_log) > 500:
            _notification_log.pop(0)
        notifs_sent.labels(channel=req.channel).inc()
        _record_req("POST", "/notify", "200", start)
        return notif
    except Exception as e:
        _record_req("POST", "/notify", "500", start)
        raise
    finally:
        active_reqs.dec()

@app.get("/recent")
async def recent_notifications(limit: int = 20):
    return {"notifications": _notification_log[-limit:][::-1]}

@app.post("/process")
async def process():
    active_reqs.inc()
    await asyncio.sleep(random.uniform(0.005, 0.015))
    active_reqs.dec()
    return {"processed": True}

def _record_req(method, endpoint, status, start):
    req_total.labels(method=method, endpoint=endpoint, status=status).inc()
    req_latency.labels(endpoint=endpoint).observe(time.time() - start)

async def _metrics_simulator():
    while True:
        cpu_sim.set(random.uniform(3, 15))
        mem_sim.set(random.uniform(30, 60))
        await asyncio.sleep(5)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
