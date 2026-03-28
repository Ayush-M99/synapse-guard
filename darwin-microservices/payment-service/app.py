"""
Payment Service - Payment processing with PostgreSQL
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
import uuid
import random
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from enum import Enum

import asyncpg
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response

# Configuration
SERVICE_NAME = "payment-service"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@postgres:5432/chaos_dna")

# Simulate payment failure rate (for chaos testing)
FAILURE_RATE = float(os.getenv("PAYMENT_FAILURE_RATE", "0.1"))

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "payment_requests_total",
    "Total payment requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "payment_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
PAYMENTS_PROCESSED = Counter(
    "payments_processed_total",
    "Total payments processed",
    ["status", "method"]
)
PAYMENT_AMOUNT = Histogram(
    "payment_amount_dollars",
    "Payment amounts in dollars",
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
)
PAYMENT_PROCESSING_TIME = Histogram(
    "payment_processing_time_seconds",
    "Payment processing time",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)
CPU_USAGE = Gauge("payment_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("payment_memory_usage_pct", "Memory usage percentage")
PENDING_PAYMENTS = Gauge("payment_pending_count", "Number of pending payments")

# Database pool
db_pool: Optional[asyncpg.Pool] = None

# Enums and Models
class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"

class PaymentMethod(str, Enum):
    CARD = "card"
    BANK = "bank"
    WALLET = "wallet"
    CRYPTO = "crypto"

class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    method: str = "card"
    card_number: Optional[str] = None
    currency: str = "USD"

class RefundRequest(BaseModel):
    reason: Optional[str] = None

class PaymentResponse(BaseModel):
    id: str
    order_id: str
    amount: float
    currency: str
    status: str
    method: str
    created_at: datetime
    processed_at: Optional[datetime] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    
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
    if db_pool:
        await db_pool.close()

app = FastAPI(
    title="Payment Service",
    description="Payment Processing Service for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

async def init_db():
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id VARCHAR(36) PRIMARY KEY,
                order_id VARCHAR(36) NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                currency VARCHAR(3) DEFAULT 'USD',
                status VARCHAR(20) DEFAULT 'pending',
                method VARCHAR(20) DEFAULT 'card',
                card_last_four VARCHAR(4),
                error_message TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                processed_at TIMESTAMP,
                refunded_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)
        """)

def update_resource_metrics():
    try:
        import psutil
        CPU_USAGE.set(psutil.cpu_percent())
        MEMORY_USAGE.set(psutil.virtual_memory().percent)
    except:
        pass

async def update_pending_count():
    if db_pool:
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM payments WHERE status = 'pending'"
            )
            PENDING_PAYMENTS.set(count or 0)

async def simulate_payment_processing(amount: float, method: str) -> tuple[bool, str]:
    """Simulate payment gateway processing"""
    # Simulate processing time (realistic variation)
    processing_time = random.uniform(0.1, 0.5)
    
    # Higher amounts have slightly higher failure rates
    adjusted_failure_rate = FAILURE_RATE
    if amount > 1000:
        adjusted_failure_rate += 0.05
    if amount > 5000:
        adjusted_failure_rate += 0.1
    
    # Crypto has higher failure rate for demo
    if method == "crypto":
        adjusted_failure_rate += 0.15
    
    await asyncio.sleep(processing_time)
    PAYMENT_PROCESSING_TIME.observe(processing_time)
    
    # Determine success/failure
    if random.random() < adjusted_failure_rate:
        failure_reasons = [
            "Insufficient funds",
            "Card declined",
            "Gateway timeout",
            "Invalid card number",
            "Fraud detection triggered",
            "Bank declined transaction"
        ]
        return False, random.choice(failure_reasons)
    
    return True, "Payment approved"

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
    await update_pending_count()
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

# Payment endpoints
@app.post("/pay")
async def process_payment(payment: PaymentRequest):
    """Process a payment"""
    start_time = time.time()
    payment_id = str(uuid.uuid4())
    
    # Record payment amount
    PAYMENT_AMOUNT.observe(payment.amount)
    
    # Validate amount
    if payment.amount <= 0:
        REQUEST_COUNT.labels(method="POST", endpoint="/pay", status="400").inc()
        raise HTTPException(status_code=400, detail="Invalid payment amount")
    
    if payment.amount > 50000:
        REQUEST_COUNT.labels(method="POST", endpoint="/pay", status="400").inc()
        raise HTTPException(status_code=400, detail="Amount exceeds maximum limit")
    
    # Get card last four if provided
    card_last_four = None
    if payment.card_number and len(payment.card_number) >= 4:
        card_last_four = payment.card_number[-4:]
    
    try:
        # Store payment record
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO payments (id, order_id, amount, currency, status, method, card_last_four)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, payment_id, payment.order_id, payment.amount, payment.currency,
                    PaymentStatus.PROCESSING.value, payment.method, card_last_four)
        
        # Process payment
        success, message = await simulate_payment_processing(payment.amount, payment.method)
        
        status = PaymentStatus.SUCCESS.value if success else PaymentStatus.FAILED.value
        
        # Update payment record
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE payments 
                    SET status = $1, processed_at = NOW(), error_message = $2
                    WHERE id = $3
                """, status, None if success else message, payment_id)
        
        # Record metrics
        PAYMENTS_PROCESSED.labels(status=status, method=payment.method).inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/pay", status="200").inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/pay").observe(time.time() - start_time)
        
        if success:
            return {
                "id": payment_id,
                "status": "success",
                "order_id": payment.order_id,
                "amount": payment.amount,
                "currency": payment.currency,
                "method": payment.method,
                "message": message,
                "processed_at": datetime.utcnow().isoformat()
            }
        else:
            return {
                "id": payment_id,
                "status": "failed",
                "order_id": payment.order_id,
                "amount": payment.amount,
                "error": message
            }
    
    except Exception as e:
        PAYMENTS_PROCESSED.labels(status="error", method=payment.method).inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/pay", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    """Get payment details"""
    start_time = time.time()
    
    if not db_pool:
        REQUEST_COUNT.labels(method="GET", endpoint="/payments/{id}", status="503").inc()
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM payments WHERE id = $1", payment_id
            )
        
        if not row:
            REQUEST_COUNT.labels(method="GET", endpoint="/payments/{id}", status="404").inc()
            raise HTTPException(status_code=404, detail="Payment not found")
        
        REQUEST_COUNT.labels(method="GET", endpoint="/payments/{id}", status="200").inc()
        REQUEST_LATENCY.labels(method="GET", endpoint="/payments/{id}").observe(time.time() - start_time)
        
        return {
            "id": row["id"],
            "order_id": row["order_id"],
            "amount": float(row["amount"]),
            "currency": row["currency"],
            "status": row["status"],
            "method": row["method"],
            "card_last_four": row["card_last_four"],
            "error_message": row["error_message"],
            "created_at": row["created_at"].isoformat(),
            "processed_at": row["processed_at"].isoformat() if row["processed_at"] else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(method="GET", endpoint="/payments/{id}", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/payments/order/{order_id}")
async def get_payments_by_order(order_id: str):
    """Get all payments for an order"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM payments WHERE order_id = $1 ORDER BY created_at DESC",
            order_id
        )
    
    payments = []
    for row in rows:
        payments.append({
            "id": row["id"],
            "order_id": row["order_id"],
            "amount": float(row["amount"]),
            "currency": row["currency"],
            "status": row["status"],
            "method": row["method"],
            "created_at": row["created_at"].isoformat(),
            "processed_at": row["processed_at"].isoformat() if row["processed_at"] else None
        })
    
    return {"payments": payments}

@app.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: str, refund: RefundRequest = None):
    """Refund a payment"""
    start_time = time.time()
    
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM payments WHERE id = $1", payment_id
            )
            
            if not row:
                raise HTTPException(status_code=404, detail="Payment not found")
            
            if row["status"] != PaymentStatus.SUCCESS.value:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Cannot refund payment with status: {row['status']}"
                )
            
            if row["refunded_at"]:
                raise HTTPException(status_code=400, detail="Payment already refunded")
            
            # Simulate refund processing
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
            await conn.execute("""
                UPDATE payments 
                SET status = $1, refunded_at = NOW(), error_message = $2
                WHERE id = $3
            """, PaymentStatus.REFUNDED.value, 
                refund.reason if refund else "Customer requested refund",
                payment_id)
        
        PAYMENTS_PROCESSED.labels(status="refunded", method=row["method"]).inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/payments/{id}/refund", status="200").inc()
        REQUEST_LATENCY.labels(method="POST", endpoint="/payments/{id}/refund").observe(time.time() - start_time)
        
        return {
            "id": payment_id,
            "status": "refunded",
            "amount": float(row["amount"]),
            "refunded_at": datetime.utcnow().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/payments/{id}/refund", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """Get payment statistics"""
    if not db_pool:
        return {"error": "Database not available"}
    
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM payments")
        successful = await conn.fetchval(
            "SELECT COUNT(*) FROM payments WHERE status = 'success'"
        )
        failed = await conn.fetchval(
            "SELECT COUNT(*) FROM payments WHERE status = 'failed'"
        )
        total_amount = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'success'"
        )
    
    return {
        "total_payments": total,
        "successful": successful,
        "failed": failed,
        "success_rate": round(successful / total * 100, 2) if total > 0 else 0,
        "total_processed_amount": float(total_amount)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
