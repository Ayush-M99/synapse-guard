"""
Order Service - Order management with PostgreSQL
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List
from enum import Enum

import httpx
import asyncpg
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response

# Configuration
SERVICE_NAME = "order-service"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@postgres:5432/chaos_dna")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "order_requests_total",
    "Total order requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "order_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
ORDERS_CREATED = Counter(
    "orders_created_total",
    "Total orders created",
    ["status"]
)
ORDER_VALUE = Histogram(
    "order_value_dollars",
    "Order value in dollars",
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
)
DOWNSTREAM_CALLS = Counter(
    "order_downstream_calls_total",
    "Downstream service calls",
    ["service", "status"]
)
CPU_USAGE = Gauge("order_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("order_memory_usage_pct", "Memory usage percentage")

# Database pool
db_pool: Optional[asyncpg.Pool] = None
http_client: Optional[httpx.AsyncClient] = None

# Enums and Models
class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"

class OrderItem(BaseModel):
    item_id: str
    name: str
    quantity: int
    price: float

class CreateOrderRequest(BaseModel):
    items: List[dict]
    shipping_address: Optional[str] = None

class OrderResponse(BaseModel):
    id: str
    user_id: int
    items: list
    total_amount: float
    status: str
    shipping_address: Optional[str]
    created_at: datetime
    updated_at: datetime

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, http_client
    
    # Initialize HTTP client
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=50)
    )
    
    # Initialize database
    for attempt in range(30):
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            await init_db()
            print(f"[{SERVICE_NAME}] Database connected successfully")
            break
        except Exception as e:
            print(f"[{SERVICE_NAME}] DB connection attempt {attempt + 1}/30 failed: {e}")
            await asyncio.sleep(2)
    else:
        print(f"[{SERVICE_NAME}] WARNING: Running without database")
    
    yield
    
    # Shutdown
    if http_client:
        await http_client.aclose()
    if db_pool:
        await db_pool.close()

app = FastAPI(
    title="Order Service",
    description="Order Management Service for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

async def init_db():
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id VARCHAR(36) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                items JSONB NOT NULL,
                total_amount DECIMAL(10, 2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                shipping_address TEXT,
                payment_id VARCHAR(36),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)
        """)

async def verify_auth_token(authorization: str = Header(None)) -> dict:
    """Verify JWT token with auth service"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    try:
        response = await http_client.post(
            f"{AUTH_SERVICE_URL}/verify",
            headers={"Authorization": authorization}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        return response.json()
    except httpx.RequestError:
        # Fallback: decode token locally for demo
        import jwt
        try:
            token = authorization.replace("Bearer ", "")
            payload = jwt.decode(token, options={"verify_signature": False})
            return {"user_id": payload.get("sub", 1), "username": payload.get("username", "demo")}
        except:
            raise HTTPException(status_code=401, detail="Invalid token")

async def call_downstream_service(service_name: str, url: str, method: str = "GET", json_data: dict = None) -> dict:
    """Call downstream service with metrics"""
    try:
        if method == "GET":
            response = await http_client.get(url)
        else:
            response = await http_client.post(url, json=json_data)
        
        DOWNSTREAM_CALLS.labels(service=service_name, status="success").inc()
        
        if response.status_code >= 400:
            DOWNSTREAM_CALLS.labels(service=service_name, status="error").inc()
            return {"error": True, "status_code": response.status_code}
        
        return response.json()
    except Exception as e:
        DOWNSTREAM_CALLS.labels(service=service_name, status="error").inc()
        return {"error": True, "message": str(e)}

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
    db_status = "connected" if db_pool else "disconnected"
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    }

@app.get("/ready")
async def readiness():
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "ready", "database": "connected"}
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Database not ready: {e}")
    return {"status": "ready", "database": "not_configured"}

@app.get("/metrics")
async def metrics():
    update_resource_metrics()
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

# Order endpoints
@app.post("/orders", response_model=OrderResponse)
async def create_order(order_request: CreateOrderRequest, authorization: str = Header(None)):
    """Create a new order"""
    start_time = time.time()
    
    # Verify authentication
    user = await verify_auth_token(authorization)
    user_id = int(user.get("user_id", 1))
    
    if not db_pool:
        REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="503").inc()
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        # Calculate total
        items = order_request.items
        total_amount = sum(
            item.get("price", 0) * item.get("quantity", 1) 
            for item in items
        )
        
        # Check inventory for each item
        for item in items:
            item_id = item.get("item_id", item.get("name", "unknown"))
            inv_response = await call_downstream_service(
                "inventory",
                f"{INVENTORY_SERVICE_URL}/stock/{item_id}"
            )
            if inv_response.get("error"):
                print(f"[{SERVICE_NAME}] Inventory check failed for {item_id}, proceeding anyway")
        
        # Create order
        order_id = str(uuid.uuid4())
        
        async with db_pool.acquire() as conn:
            import json
            await conn.execute("""
                INSERT INTO orders (id, user_id, items, total_amount, status, shipping_address)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, order_id, user_id, json.dumps(items), total_amount, 
                OrderStatus.PENDING.value, order_request.shipping_address)
            
            result = await conn.fetchrow(
                "SELECT * FROM orders WHERE id = $1", order_id
            )
        
        # Process payment
        payment_response = await call_downstream_service(
            "payment",
            f"{PAYMENT_SERVICE_URL}/pay",
            method="POST",
            json_data={
                "order_id": order_id,
                "amount": float(total_amount),
                "method": "card"
            }
        )
        
        # Update order status based on payment
        new_status = OrderStatus.PAID.value if payment_response.get("status") == "success" else OrderStatus.PENDING.value
        
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2",
                new_status, order_id
            )
            result = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        
        # Send notification
        await call_downstream_service(
            "notification",
            f"{NOTIFICATION_SERVICE_URL}/notify",
            method="POST",
            json_data={"message": f"Order {order_id} created successfully!"}
        )
        
        # Record metrics
        ORDERS_CREATED.labels(status="success").inc()
        ORDER_VALUE.observe(float(total_amount))
        REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="201").inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/orders").observe(time.time() - start_time)
        
        import json
        return OrderResponse(
            id=result["id"],
            user_id=result["user_id"],
            items=json.loads(result["items"]) if isinstance(result["items"], str) else result["items"],
            total_amount=float(result["total_amount"]),
            status=result["status"],
            shipping_address=result["shipping_address"],
            created_at=result["created_at"],
            updated_at=result["updated_at"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        ORDERS_CREATED.labels(status="failed").inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/orders", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders")
async def list_orders(
    authorization: str = Header(None),
    status: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0
):
    """List orders for the authenticated user"""
    start_time = time.time()
    
    user = await verify_auth_token(authorization)
    user_id = int(user.get("user_id", 1))
    
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        async with db_pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT * FROM orders 
                    WHERE user_id = $1 AND status = $2
                    ORDER BY created_at DESC
                    LIMIT $3 OFFSET $4
                """, user_id, status, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM orders 
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $3 OFFSET $4
                """, user_id, limit, offset)
        
        import json
        orders = []
        for row in rows:
            orders.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "items": json.loads(row["items"]) if isinstance(row["items"], str) else row["items"],
                "total_amount": float(row["total_amount"]),
                "status": row["status"],
                "shipping_address": row["shipping_address"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat()
            })
        
        REQUEST_COUNT.labels(method="GET", endpoint="/orders", status="200").inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/orders").observe(time.time() - start_time)
        
        return {"orders": orders, "total": len(orders)}
    
    except Exception as e:
        REQUEST_COUNT.labels(method="GET", endpoint="/orders", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/{order_id}")
async def get_order(order_id: str, authorization: str = Header(None)):
    """Get order details"""
    start_time = time.time()
    
    user = await verify_auth_token(authorization)
    user_id = int(user.get("user_id", 1))
    
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE id = $1 AND user_id = $2",
                order_id, user_id
            )
        
        if not row:
            REQUEST_COUNT.labels(method="GET", endpoint="/orders/{id}", status="404").inc()
            raise HTTPException(status_code=404, detail="Order not found")
        
        import json
        REQUEST_COUNT.labels(method="GET", endpoint="/orders/{id}", status="200").inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/orders/{id}").observe(time.time() - start_time)
        
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "items": json.loads(row["items"]) if isinstance(row["items"], str) else row["items"],
            "total_amount": float(row["total_amount"]),
            "status": row["status"],
            "shipping_address": row["shipping_address"],
            "payment_id": row["payment_id"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(method="GET", endpoint="/orders/{id}", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, authorization: str = Header(None)):
    """Cancel an order"""
    user = await verify_auth_token(authorization)
    user_id = int(user.get("user_id", 1))
    
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE id = $1 AND user_id = $2",
            order_id, user_id
        )
        
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        
        if row["status"] in [OrderStatus.SHIPPED.value, OrderStatus.DELIVERED.value]:
            raise HTTPException(status_code=400, detail="Cannot cancel shipped/delivered order")
        
        await conn.execute(
            "UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2",
            OrderStatus.CANCELLED.value, order_id
        )
    
    # Notify about cancellation
    await call_downstream_service(
        "notification",
        f"{NOTIFICATION_SERVICE_URL}/notify",
        method="POST",
        json_data={"message": f"Order {order_id} has been cancelled"}
    )
    
    REQUEST_COUNT.labels(method="PUT", endpoint="/orders/{id}/cancel", status="200").inc()
    
    return {"status": "cancelled", "order_id": order_id}

# Legacy endpoint for backward compatibility
@app.post("/create")
async def create_order_legacy():
    """Legacy endpoint - creates demo order"""
    # Call payment service
    payment_response = await call_downstream_service(
        "payment",
        f"{PAYMENT_SERVICE_URL}/pay",
        method="POST",
        json_data={"order_id": str(uuid.uuid4()), "amount": 99.99}
    )
    
    return {
        "order": "created",
        "payment": payment_response,
        "order_id": str(uuid.uuid4())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
