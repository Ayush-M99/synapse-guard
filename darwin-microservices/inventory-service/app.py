"""
Inventory Service - Stock management with Redis caching
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict

try:
    import redis.asyncio as aioredis
except ImportError:
    import redis as aioredis

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response

# Configuration
SERVICE_NAME = "inventory-service"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "inventory_requests_total",
    "Total inventory requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "inventory_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)
STOCK_OPERATIONS = Counter(
    "inventory_stock_operations_total",
    "Stock operations",
    ["operation", "item", "status"]
)
CACHE_HITS = Counter(
    "inventory_cache_hits_total",
    "Redis cache hits"
)
CACHE_MISSES = Counter(
    "inventory_cache_misses_total",
    "Redis cache misses"
)
STOCK_LEVELS = Gauge(
    "inventory_stock_level",
    "Current stock level",
    ["item"]
)
LOW_STOCK_ALERTS = Counter(
    "inventory_low_stock_alerts_total",
    "Low stock alerts triggered",
    ["item"]
)
CPU_USAGE = Gauge("inventory_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("inventory_memory_usage_pct", "Memory usage percentage")

# Redis client
redis_client: Optional[aioredis.Redis] = None

# Default inventory (fallback if Redis unavailable)
DEFAULT_INVENTORY = {
    "laptop": {"name": "Laptop Pro 15", "stock": 50, "price": 1299.99, "category": "electronics"},
    "phone": {"name": "SmartPhone X", "stock": 100, "price": 899.99, "category": "electronics"},
    "headphones": {"name": "Wireless Headphones", "stock": 200, "price": 199.99, "category": "electronics"},
    "keyboard": {"name": "Mechanical Keyboard", "stock": 150, "price": 149.99, "category": "accessories"},
    "mouse": {"name": "Gaming Mouse", "stock": 300, "price": 79.99, "category": "accessories"},
    "monitor": {"name": "4K Monitor 27\"", "stock": 75, "price": 449.99, "category": "electronics"},
    "tablet": {"name": "Tablet Pro", "stock": 80, "price": 699.99, "category": "electronics"},
    "charger": {"name": "Fast Charger", "stock": 500, "price": 29.99, "category": "accessories"},
    "case": {"name": "Phone Case", "stock": 1000, "price": 19.99, "category": "accessories"},
    "cable": {"name": "USB-C Cable", "stock": 800, "price": 14.99, "category": "accessories"}
}

# In-memory fallback
in_memory_stock: Dict[str, dict] = {}

# Models
class StockUpdate(BaseModel):
    quantity: int

class ItemCreate(BaseModel):
    name: str
    stock: int
    price: float
    category: str = "general"

class ReservationRequest(BaseModel):
    quantity: int = 1
    order_id: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, in_memory_stock
    
    # Initialize in-memory fallback
    in_memory_stock = {k: v.copy() for k, v in DEFAULT_INVENTORY.items()}
    
    # Try to connect to Redis
    for attempt in range(30):
        try:
            redis_client = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            await redis_client.ping()
            print(f"[{SERVICE_NAME}] Redis connected successfully")
            
            # Initialize inventory in Redis
            await init_inventory()
            break
        except Exception as e:
            print(f"[{SERVICE_NAME}] Redis connection attempt {attempt + 1}/30 failed: {e}")
            await asyncio.sleep(2)
    else:
        print(f"[{SERVICE_NAME}] WARNING: Running without Redis, using in-memory storage")
    
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.aclose()

app = FastAPI(
    title="Inventory Service",
    description="Inventory Management Service for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

async def init_inventory():
    """Initialize inventory in Redis"""
    if not redis_client:
        return
    
    for item_id, item_data in DEFAULT_INVENTORY.items():
        key = f"inventory:{item_id}"
        exists = await redis_client.exists(key)
        if not exists:
            await redis_client.hset(key, mapping={
                "name": item_data["name"],
                "stock": item_data["stock"],
                "price": item_data["price"],
                "category": item_data["category"],
                "reserved": 0
            })
            STOCK_LEVELS.labels(item=item_id).set(item_data["stock"])

async def get_item_from_cache(item_id: str) -> Optional[dict]:
    """Get item from Redis or in-memory fallback"""
    if redis_client:
        try:
            data = await redis_client.hgetall(f"inventory:{item_id}")
            if data:
                CACHE_HITS.inc()
                return {
                    "item_id": item_id,
                    "name": data.get("name", item_id),
                    "stock": int(data.get("stock", 0)),
                    "price": float(data.get("price", 0)),
                    "category": data.get("category", "general"),
                    "reserved": int(data.get("reserved", 0))
                }
            CACHE_MISSES.inc()
        except Exception as e:
            print(f"[{SERVICE_NAME}] Redis error: {e}")
    
    # Fallback to in-memory
    if item_id in in_memory_stock:
        return {
            "item_id": item_id,
            **in_memory_stock[item_id],
            "reserved": in_memory_stock[item_id].get("reserved", 0)
        }
    
    return None

async def update_stock_in_cache(item_id: str, stock: int, reserved: int = None):
    """Update stock in Redis or in-memory fallback"""
    if redis_client:
        try:
            updates = {"stock": stock}
            if reserved is not None:
                updates["reserved"] = reserved
            await redis_client.hset(f"inventory:{item_id}", mapping=updates)
            STOCK_LEVELS.labels(item=item_id).set(stock)
            
            # Check for low stock
            if stock < 10:
                LOW_STOCK_ALERTS.labels(item=item_id).inc()
            return
        except Exception as e:
            print(f"[{SERVICE_NAME}] Redis error: {e}")
    
    # Fallback to in-memory
    if item_id in in_memory_stock:
        in_memory_stock[item_id]["stock"] = stock
        if reserved is not None:
            in_memory_stock[item_id]["reserved"] = reserved

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
    redis_status = "connected"
    if redis_client:
        try:
            await redis_client.ping()
        except:
            redis_status = "error"
    else:
        redis_status = "disconnected"
    
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "redis": redis_status
    }

@app.get("/ready")
async def readiness():
    if redis_client:
        try:
            await redis_client.ping()
            return {"status": "ready", "redis": "connected"}
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Redis not ready: {e}")
    return {"status": "ready", "redis": "not_configured", "mode": "in_memory"}

@app.get("/metrics")
async def metrics():
    update_resource_metrics()
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

# Inventory endpoints
@app.get("/stock")
async def list_all_stock(category: Optional[str] = None):
    """List all inventory items"""
    start_time = time.time()
    
    items = []
    
    if redis_client:
        try:
            keys = await redis_client.keys("inventory:*")
            for key in keys:
                item_id = key.replace("inventory:", "")
                item = await get_item_from_cache(item_id)
                if item:
                    if category is None or item.get("category") == category:
                        items.append(item)
        except Exception as e:
            print(f"[{SERVICE_NAME}] Redis error: {e}")
    
    # Fallback to in-memory
    if not items:
        for item_id, data in in_memory_stock.items():
            if category is None or data.get("category") == category:
                items.append({
                    "item_id": item_id,
                    **data
                })
    
    REQUEST_COUNT.labels(method="GET", endpoint="/stock", status="200").inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/stock").observe(time.time() - start_time)
    
    return {"items": items, "total": len(items)}

@app.get("/stock/{item_id}")
async def get_stock(item_id: str):
    """Get stock for specific item"""
    start_time = time.time()
    
    item = await get_item_from_cache(item_id)
    
    if not item:
        REQUEST_COUNT.labels(method="GET", endpoint="/stock/{id}", status="404").inc()
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    
    available = item["stock"] - item.get("reserved", 0)
    
    REQUEST_COUNT.labels(method="GET", endpoint="/stock/{id}", status="200").inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/stock/{id}").observe(time.time() - start_time)
    
    return {
        "item": item_id,
        "name": item["name"],
        "stock": item["stock"],
        "reserved": item.get("reserved", 0),
        "available": available,
        "price": item["price"],
        "category": item["category"]
    }

@app.post("/reserve/{item_id}")
async def reserve_stock(item_id: str, qty: int = Query(default=1, ge=1)):
    """Reserve stock for an order"""
    start_time = time.time()
    
    item = await get_item_from_cache(item_id)
    
    if not item:
        REQUEST_COUNT.labels(method="POST", endpoint="/reserve/{id}", status="404").inc()
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    
    available = item["stock"] - item.get("reserved", 0)
    
    if available < qty:
        STOCK_OPERATIONS.labels(operation="reserve", item=item_id, status="insufficient").inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/reserve/{id}", status="400").inc()
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient stock. Available: {available}, Requested: {qty}"
        )
    
    new_reserved = item.get("reserved", 0) + qty
    await update_stock_in_cache(item_id, item["stock"], new_reserved)
    
    STOCK_OPERATIONS.labels(operation="reserve", item=item_id, status="success").inc()
    REQUEST_COUNT.labels(method="POST", endpoint="/reserve/{id}", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/reserve/{id}").observe(time.time() - start_time)
    
    return {
        "status": "reserved",
        "item": item_id,
        "quantity": qty,
        "remaining_available": available - qty
    }

@app.post("/decrease/{item_id}")
async def decrease_stock(item_id: str, qty: int = Query(default=1, ge=1)):
    """Decrease stock (after order fulfillment)"""
    start_time = time.time()
    
    item = await get_item_from_cache(item_id)
    
    if not item:
        REQUEST_COUNT.labels(method="POST", endpoint="/decrease/{id}", status="404").inc()
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    
    if item["stock"] < qty:
        STOCK_OPERATIONS.labels(operation="decrease", item=item_id, status="insufficient").inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/decrease/{id}", status="400").inc()
        raise HTTPException(status_code=400, detail="Insufficient stock")
    
    new_stock = item["stock"] - qty
    new_reserved = max(0, item.get("reserved", 0) - qty)
    
    await update_stock_in_cache(item_id, new_stock, new_reserved)
    
    STOCK_OPERATIONS.labels(operation="decrease", item=item_id, status="success").inc()
    REQUEST_COUNT.labels(method="POST", endpoint="/decrease/{id}", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/decrease/{id}").observe(time.time() - start_time)
    
    return {
        "status": "updated",
        "item": item_id,
        "remaining": new_stock
    }

@app.post("/increase/{item_id}")
async def increase_stock(item_id: str, qty: int = Query(default=1, ge=1)):
    """Increase stock (restock)"""
    start_time = time.time()
    
    item = await get_item_from_cache(item_id)
    
    if not item:
        REQUEST_COUNT.labels(method="POST", endpoint="/increase/{id}", status="404").inc()
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    
    new_stock = item["stock"] + qty
    await update_stock_in_cache(item_id, new_stock)
    
    STOCK_OPERATIONS.labels(operation="increase", item=item_id, status="success").inc()
    REQUEST_COUNT.labels(method="POST", endpoint="/increase/{id}", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/increase/{id}").observe(time.time() - start_time)
    
    return {
        "status": "restocked",
        "item": item_id,
        "new_stock": new_stock
    }

@app.post("/items")
async def create_item(item: ItemCreate, item_id: str = Query(...)):
    """Create a new inventory item"""
    start_time = time.time()
    
    existing = await get_item_from_cache(item_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Item '{item_id}' already exists")
    
    if redis_client:
        await redis_client.hset(f"inventory:{item_id}", mapping={
            "name": item.name,
            "stock": item.stock,
            "price": item.price,
            "category": item.category,
            "reserved": 0
        })
    
    in_memory_stock[item_id] = {
        "name": item.name,
        "stock": item.stock,
        "price": item.price,
        "category": item.category,
        "reserved": 0
    }
    
    STOCK_LEVELS.labels(item=item_id).set(item.stock)
    REQUEST_COUNT.labels(method="POST", endpoint="/items", status="201").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/items").observe(time.time() - start_time)
    
    return {
        "status": "created",
        "item_id": item_id,
        "name": item.name,
        "stock": item.stock
    }

@app.get("/search")
async def search_items(q: str = Query(..., min_length=1)):
    """Search inventory items"""
    start_time = time.time()
    
    results = []
    
    # Search in Redis or in-memory
    if redis_client:
        keys = await redis_client.keys("inventory:*")
        for key in keys:
            item_id = key.replace("inventory:", "")
            item = await get_item_from_cache(item_id)
            if item and (q.lower() in item["name"].lower() or q.lower() in item_id.lower()):
                results.append(item)
    else:
        for item_id, data in in_memory_stock.items():
            if q.lower() in data["name"].lower() or q.lower() in item_id.lower():
                results.append({"item_id": item_id, **data})
    
    REQUEST_COUNT.labels(method="GET", endpoint="/search", status="200").inc()
    REQUEST_LATENCY.labels(method="GET", endpoint="/search").observe(time.time() - start_time)
    
    return {"query": q, "results": results, "count": len(results)}

@app.get("/low-stock")
async def get_low_stock(threshold: int = 20):
    """Get items with low stock"""
    all_items = await list_all_stock()
    low_stock = [
        item for item in all_items["items"] 
        if item["stock"] < threshold
    ]
    
    return {
        "threshold": threshold,
        "items": low_stock,
        "count": len(low_stock)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
