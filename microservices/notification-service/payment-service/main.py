"""
Payment Service - DARWIN Target Application
Simple FastAPI microservice for testing chaos engineering
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
import time
import logging
from datetime import datetime
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from contextlib import asynccontextmanager
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# PROMETHEUS METRICS - 7-Feature Vector
# ============================================================================

# Counter: Total HTTP requests
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# Histogram: Request duration
http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Gauge: Current error rate (%)
http_error_rate = Gauge(
    'http_error_rate',
    'Current HTTP error rate (percentage)',
)

# Gauge: P99 latency
http_latency_p99_ms = Gauge(
    'http_latency_p99_ms',
    'P99 HTTP latency in milliseconds',
)

# Gauge: Pod restart count (simulated)
pod_restart_count = Gauge(
    'pod_restart_count',
    'Pod restart count',
)

# Gauge: Network RX bytes
network_rx_bytes = Gauge(
    'network_rx_bytes',
    'Network received bytes',
)

# Gauge: Network TX bytes
network_tx_bytes = Gauge(
    'network_tx_bytes',
    'Network transmitted bytes',
)

# ============================================================================
# SERVICE STATE
# ============================================================================

service_state = {
    "name": "payment-service",
    "version": "1.0.0",
    "status": "healthy",
    "start_time": datetime.utcnow(),
    "request_count": 0,
    "error_count": 0,
    "latencies": [],  # Last 100 request latencies
    "max_latencies": 100,
}

# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    logger.info("🚀 Payment Service starting up...")
    service_state["start_time"] = datetime.utcnow()

    # Initialize metrics
    pod_restart_count.set(0)
    network_rx_bytes.set(0)
    network_tx_bytes.set(0)
    http_error_rate.set(0)
    http_latency_p99_ms.set(0)

    yield

    logger.info("🛑 Payment Service shutting down...")

# ============================================================================
# CREATE FASTAPI APP
# ============================================================================

app = FastAPI(
    title="DARWIN Payment Service",
    description="Target microservice for chaos engineering testing",
    version="1.0.0",
    lifespan=lifespan
)

# ============================================================================
# MIDDLEWARE - Request timing and metrics
# ============================================================================

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    """Track request metrics"""
    start_time = time.time()

    try:
        response = await call_next(request)

        # Calculate latency
        latency = time.time() - start_time

        # Record metrics
        service_state["request_count"] += 1
        http_requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()

        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(latency)

        # Track latencies for P99 calculation
        service_state["latencies"].append(latency * 1000)  # Convert to ms
        if len(service_state["latencies"]) > service_state["max_latencies"]:
            service_state["latencies"].pop(0)

        # Update error rate
        if response.status_code >= 400:
            service_state["error_count"] += 1

        error_rate = (service_state["error_count"] / max(service_state["request_count"], 1)) * 100
        http_error_rate.set(error_rate)

        # Update P99 latency
        if service_state["latencies"]:
            sorted_latencies = sorted(service_state["latencies"])
            p99_index = int(len(sorted_latencies) * 0.99)
            http_latency_p99_ms.set(sorted_latencies[p99_index])

        return response

    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        service_state["error_count"] += 1
        raise

# ============================================================================
# HEALTH ENDPOINT
# ============================================================================

@app.get("/health")
def health():
    """
    Health check endpoint
    Returns: JSON with service status
    """
    uptime = (datetime.utcnow() - service_state["start_time"]).total_seconds()

    return {
        "status": service_state["status"],
        "service": service_state["name"],
        "version": service_state["version"],
        "uptime_seconds": uptime,
        "timestamp": datetime.utcnow().isoformat(),
    }

# ============================================================================
# METRICS ENDPOINT
# ============================================================================

@app.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint
    Returns: Prometheus text format metrics
    """
    return Response(content=generate_latest(), media_type="text/plain")

# ============================================================================
# BUSINESS LOGIC ENDPOINTS
# ============================================================================

@app.post("/process-payment")
async def process_payment(amount: float):
    """
    Process a payment transaction

    Args:
        amount: Payment amount in dollars

    Returns:
        Payment result with transaction ID

    Raises:
        400: Invalid amount
        503: Service unavailable (chaos injection)
    """

    # Validation
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    if amount > 100000:
        raise HTTPException(status_code=400, detail="Amount exceeds limit")

    # Simulate processing time
    processing_time = 0.1 + (amount / 10000)  # More delay for large amounts
    await asyncio.sleep(processing_time)

    # Simulate occasional failures (1% error rate)
    import random
    if random.random() < 0.01:
        raise HTTPException(status_code=503, detail="Processing temporarily unavailable")

    return {
        "status": "success",
        "transaction_id": f"txn-{int(time.time())}",
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat(),
    }

@app.get("/list-transactions")
async def list_transactions():
    """
    List recent transactions

    Returns:
        List of mock transaction records
    """
    return {
        "transactions": [
            {
                "transaction_id": f"txn-{1000 + i}",
                "amount": 50 + i * 10,
                "status": "completed",
                "timestamp": (datetime.utcnow().timestamp() - i * 60),
            }
            for i in range(5)
        ],
        "count": 5,
    }

@app.post("/refund")
async def refund(transaction_id: str, amount: float):
    """
    Process a refund

    Args:
        transaction_id: Transaction to refund
        amount: Refund amount

    Returns:
        Refund confirmation
    """

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be positive")

    # Simulate processing
    await asyncio.sleep(0.15)

    return {
        "status": "success",
        "refund_id": f"ref-{int(time.time())}",
        "transaction_id": transaction_id,
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat(),
    }

# ============================================================================
# CHAOS INJECTION ENDPOINTS (for testing)
# ============================================================================

@app.post("/chaos/degrade")
async def chaos_degrade(latency_ms: int = 500):
    """
    Simulate service degradation (add latency)
    For testing chaos engineering detection
    """
    logger.warning(f"⚠️ Chaos: Adding {latency_ms}ms latency")
    service_state["chaos_latency"] = latency_ms
    return {"status": "degraded", "latency_ms": latency_ms}

@app.post("/chaos/recover")
async def chaos_recover():
    """
    Recover from chaos injection
    """
    logger.info("✅ Chaos: Recovering to normal")
    service_state["chaos_latency"] = 0
    return {"status": "recovered"}

# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "service": service_state["name"],
        "version": service_state["version"],
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }

# ============================================================================
# STARTUP MESSAGE
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("""
╔════════════════════════════════════════════════════════════╗
║         DARWIN Payment Service Starting                   ║
║                                                            ║
║  📊 Health Check:  http://localhost:8080/health           ║
║  📈 Metrics:       http://localhost:8080/metrics           ║
║  📖 API Docs:      http://localhost:8080/docs             ║
║  🔗 Root:          http://localhost:8080/                 ║
║                                                            ║
║  Service: payment-service v1.0.0                          ║
║  Target Application (Patient) for DARWIN                 ║
╚════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )
