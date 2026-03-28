"""
Notification Service - Async notification handling
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
import uuid
import random
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List
from enum import Enum
from collections import deque

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response

# Configuration
SERVICE_NAME = "notification-service"

# Simulate notification failure rate (for chaos testing)
FAILURE_RATE = float(os.getenv("NOTIFICATION_FAILURE_RATE", "0.1"))
# Simulate processing delay
MIN_DELAY = float(os.getenv("NOTIFICATION_MIN_DELAY", "0.05"))
MAX_DELAY = float(os.getenv("NOTIFICATION_MAX_DELAY", "0.3"))

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "notification_requests_total",
    "Total notification requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "notification_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)
NOTIFICATIONS_SENT = Counter(
    "notifications_sent_total",
    "Total notifications sent",
    ["type", "status"]
)
NOTIFICATION_PROCESSING_TIME = Histogram(
    "notification_processing_time_seconds",
    "Notification processing time",
    ["type"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
)
NOTIFICATION_QUEUE_SIZE = Gauge(
    "notification_queue_size",
    "Number of notifications in queue"
)
CPU_USAGE = Gauge("notification_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("notification_memory_usage_pct", "Memory usage percentage")

# In-memory notification storage (for demo purposes)
notifications_store: deque = deque(maxlen=1000)
notification_queue: asyncio.Queue = None

# Enums and Models
class NotificationType(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"
    SLACK = "slack"

class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    QUEUED = "queued"

class NotificationRequest(BaseModel):
    message: str
    type: str = "email"
    recipient: Optional[str] = None
    subject: Optional[str] = None
    priority: int = 1  # 1=low, 2=medium, 3=high

class BulkNotificationRequest(BaseModel):
    messages: List[dict]
    type: str = "email"

class NotificationResponse(BaseModel):
    id: str
    status: str
    message: str
    type: str
    sent_at: Optional[datetime] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global notification_queue
    
    # Initialize async queue
    notification_queue = asyncio.Queue(maxsize=1000)
    
    # Start background worker
    worker_task = asyncio.create_task(notification_worker())
    
    print(f"[{SERVICE_NAME}] Notification worker started")
    
    yield
    
    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Notification Service",
    description="Notification Service for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

async def notification_worker():
    """Background worker to process notification queue"""
    while True:
        try:
            notification = await asyncio.wait_for(
                notification_queue.get(), 
                timeout=1.0
            )
            
            NOTIFICATION_QUEUE_SIZE.set(notification_queue.qsize())
            
            # Process notification
            await send_notification_internal(notification)
            
            notification_queue.task_done()
        except asyncio.TimeoutError:
            # No notifications in queue
            continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{SERVICE_NAME}] Worker error: {e}")

async def send_notification_internal(notification: dict) -> dict:
    """Internal notification sending logic"""
    start_time = time.time()
    notification_type = notification.get("type", "email")
    
    # Simulate processing delay
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(delay)
    
    # Simulate occasional failures
    if random.random() < FAILURE_RATE:
        NOTIFICATIONS_SENT.labels(type=notification_type, status="failed").inc()
        notification["status"] = NotificationStatus.FAILED.value
        notification["error"] = random.choice([
            "Connection timeout",
            "Service unavailable",
            "Rate limit exceeded",
            "Invalid recipient"
        ])
        return notification
    
    # Success
    NOTIFICATIONS_SENT.labels(type=notification_type, status="sent").inc()
    NOTIFICATION_PROCESSING_TIME.labels(type=notification_type).observe(time.time() - start_time)
    
    notification["status"] = NotificationStatus.SENT.value
    notification["sent_at"] = datetime.utcnow().isoformat()
    
    # Store notification
    notifications_store.append(notification)
    
    return notification

def update_resource_metrics():
    try:
        import psutil
        CPU_USAGE.set(psutil.cpu_percent())
        MEMORY_USAGE.set(psutil.virtual_memory().percent)
    except:
        pass

# Health endpoints
@app.get("/health")
async def health():
    queue_size = notification_queue.qsize() if notification_queue else 0
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "queue_size": queue_size
    }

@app.get("/ready")
async def readiness():
    if notification_queue is None:
        raise HTTPException(status_code=503, detail="Queue not initialized")
    return {
        "status": "ready",
        "queue_capacity": notification_queue.maxsize,
        "queue_size": notification_queue.qsize()
    }

@app.get("/metrics")
async def metrics():
    update_resource_metrics()
    if notification_queue:
        NOTIFICATION_QUEUE_SIZE.set(notification_queue.qsize())
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

# Notification endpoints
@app.post("/notify")
async def send_notification(notification: NotificationRequest):
    """Send a notification (synchronous)"""
    start_time = time.time()
    
    notification_id = str(uuid.uuid4())
    
    notification_data = {
        "id": notification_id,
        "message": notification.message,
        "type": notification.type,
        "recipient": notification.recipient,
        "subject": notification.subject,
        "priority": notification.priority,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Process synchronously
    result = await send_notification_internal(notification_data)
    
    REQUEST_COUNT.labels(method="POST", endpoint="/notify", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/notify").observe(time.time() - start_time)
    
    return {
        "id": notification_id,
        "status": result["status"],
        "message": notification.message,
        "type": notification.type,
        "sent_at": result.get("sent_at"),
        "error": result.get("error")
    }

@app.post("/notify/async")
async def send_notification_async(notification: NotificationRequest, background_tasks: BackgroundTasks):
    """Queue a notification for async processing"""
    start_time = time.time()
    
    notification_id = str(uuid.uuid4())
    
    notification_data = {
        "id": notification_id,
        "message": notification.message,
        "type": notification.type,
        "recipient": notification.recipient,
        "subject": notification.subject,
        "priority": notification.priority,
        "status": NotificationStatus.QUEUED.value,
        "created_at": datetime.utcnow().isoformat()
    }
    
    try:
        notification_queue.put_nowait(notification_data)
        NOTIFICATION_QUEUE_SIZE.set(notification_queue.qsize())
        
        REQUEST_COUNT.labels(method="POST", endpoint="/notify/async", status="202").inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/notify/async").observe(time.time() - start_time)
        
        return {
            "id": notification_id,
            "status": "queued",
            "queue_position": notification_queue.qsize()
        }
    except asyncio.QueueFull:
        REQUEST_COUNT.labels(method="POST", endpoint="/notify/async", status="503").inc()
        raise HTTPException(status_code=503, detail="Notification queue is full")

@app.post("/notify/bulk")
async def send_bulk_notifications(bulk: BulkNotificationRequest):
    """Send multiple notifications"""
    start_time = time.time()
    
    results = []
    success_count = 0
    failed_count = 0
    
    for msg_data in bulk.messages:
        notification_id = str(uuid.uuid4())
        
        notification_data = {
            "id": notification_id,
            "message": msg_data.get("message", ""),
            "type": bulk.type,
            "recipient": msg_data.get("recipient"),
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = await send_notification_internal(notification_data)
        
        if result["status"] == NotificationStatus.SENT.value:
            success_count += 1
        else:
            failed_count += 1
        
        results.append({
            "id": notification_id,
            "status": result["status"],
            "recipient": msg_data.get("recipient")
        })
    
    REQUEST_COUNT.labels(method="POST", endpoint="/notify/bulk", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/notify/bulk").observe(time.time() - start_time)
    
    return {
        "total": len(bulk.messages),
        "success": success_count,
        "failed": failed_count,
        "results": results
    }

@app.get("/notifications")
async def list_notifications(
    limit: int = Query(default=50, le=100),
    type: Optional[str] = None,
    status: Optional[str] = None
):
    """List recent notifications"""
    start_time = time.time()
    
    notifications = list(notifications_store)
    
    # Filter by type
    if type:
        notifications = [n for n in notifications if n.get("type") == type]
    
    # Filter by status
    if status:
        notifications = [n for n in notifications if n.get("status") == status]
    
    # Sort by created_at (newest first) and limit
    notifications = sorted(
        notifications, 
        key=lambda x: x.get("created_at", ""), 
        reverse=True
    )[:limit]
    
    REQUEST_COUNT.labels(method="GET", endpoint="/notifications", status="200").inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/notifications").observe(time.time() - start_time)
    
    return {
        "notifications": notifications,
        "total": len(notifications)
    }

@app.get("/notifications/{notification_id}")
async def get_notification(notification_id: str):
    """Get notification by ID"""
    start_time = time.time()
    
    for notification in notifications_store:
        if notification.get("id") == notification_id:
            REQUEST_COUNT.labels(method="GET", endpoint="/notifications/{id}", status="200").inc()
            REQUEST_LATENCY.labels(method="GET", endpoint="/notifications/{id}").observe(time.time() - start_time)
            return notification
    
    REQUEST_COUNT.labels(method="GET", endpoint="/notifications/{id}", status="404").inc()
    raise HTTPException(status_code=404, detail="Notification not found")

@app.get("/stats")
async def get_stats():
    """Get notification statistics"""
    all_notifications = list(notifications_store)
    
    sent = sum(1 for n in all_notifications if n.get("status") == "sent")
    failed = sum(1 for n in all_notifications if n.get("status") == "failed")
    
    by_type = {}
    for n in all_notifications:
        t = n.get("type", "unknown")
        if t not in by_type:
            by_type[t] = {"sent": 0, "failed": 0}
        if n.get("status") == "sent":
            by_type[t]["sent"] += 1
        else:
            by_type[t]["failed"] += 1
    
    return {
        "total_processed": len(all_notifications),
        "sent": sent,
        "failed": failed,
        "success_rate": round(sent / len(all_notifications) * 100, 2) if all_notifications else 0,
        "queue_size": notification_queue.qsize() if notification_queue else 0,
        "by_type": by_type
    }

@app.post("/test")
async def test_notification():
    """Send a test notification"""
    return await send_notification(NotificationRequest(
        message="This is a test notification from Darwin Chaos Platform",
        type="email",
        recipient="test@darwin.io",
        subject="Test Notification"
    ))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
