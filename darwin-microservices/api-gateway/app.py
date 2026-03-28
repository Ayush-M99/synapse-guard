"""
API Gateway - Central routing and rate limiting
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response, JSONResponse

# Configuration
SERVICE_NAME = "api-gateway"
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

# Rate limiting config
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "gateway_requests_total",
    "Total gateway requests",
    ["method", "endpoint", "status", "target_service"]
)
REQUEST_LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint", "target_service"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
UPSTREAM_ERRORS = Counter(
    "gateway_upstream_errors_total",
    "Total upstream service errors",
    ["target_service", "error_type"]
)
ACTIVE_CONNECTIONS = Gauge(
    "gateway_active_connections",
    "Number of active connections"
)
CIRCUIT_BREAKER_STATE = Gauge(
    "gateway_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["target_service"]
)
CPU_USAGE = Gauge("gateway_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("gateway_memory_usage_pct", "Memory usage percentage")

# Rate limiter storage (in-memory, use Redis in production)
rate_limit_store: Dict[str, list] = {}

# Circuit breaker state per service
circuit_breakers: Dict[str, Dict[str, Any]] = {}

# HTTP Client
http_client: Optional[httpx.AsyncClient] = None

class CircuitBreaker:
    def __init__(self, service_name: str, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.state = "closed"  # closed, open, half-open
        self.last_failure_time = None
    
    def record_success(self):
        self.failures = 0
        self.state = "closed"
        CIRCUIT_BREAKER_STATE.labels(target_service=self.service_name).set(0)
    
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "open"
            CIRCUIT_BREAKER_STATE.labels(target_service=self.service_name).set(1)
    
    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                CIRCUIT_BREAKER_STATE.labels(target_service=self.service_name).set(2)
                return True
            return False
        return True  # half-open allows one request

# Initialize circuit breakers for all services
for svc in ["auth", "order", "payment", "inventory", "notification"]:
    circuit_breakers[svc] = CircuitBreaker(svc)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    # Startup
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
    )
    print(f"[{SERVICE_NAME}] HTTP client initialized")
    
    yield
    
    # Shutdown
    if http_client:
        await http_client.aclose()

app = FastAPI(
    title="API Gateway",
    description="Central API Gateway for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class LoginRequest(BaseModel):
    username: str
    password: str

class SignupRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class OrderRequest(BaseModel):
    items: list
    shipping_address: Optional[str] = None

class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    method: str = "card"

# Helpers
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def check_rate_limit(client_ip: str) -> bool:
    """Simple sliding window rate limiter"""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    
    if client_ip not in rate_limit_store:
        rate_limit_store[client_ip] = []
    
    # Clean old entries
    rate_limit_store[client_ip] = [
        ts for ts in rate_limit_store[client_ip] if ts > window_start
    ]
    
    if len(rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False
    
    rate_limit_store[client_ip].append(now)
    return True

async def proxy_request(
    service_name: str,
    service_url: str,
    method: str,
    path: str,
    headers: dict = None,
    json_data: dict = None,
    params: dict = None
) -> dict:
    """Proxy request to upstream service with circuit breaker"""
    cb = circuit_breakers.get(service_name)
    
    if cb and not cb.can_execute():
        UPSTREAM_ERRORS.labels(target_service=service_name, error_type="circuit_open").inc()
        raise HTTPException(
            status_code=503,
            detail=f"Service {service_name} temporarily unavailable (circuit open)"
        )
    
    start_time = time.time()
    full_url = f"{service_url}{path}"
    
    try:
        ACTIVE_CONNECTIONS.inc()
        
        if method == "GET":
            response = await http_client.get(full_url, headers=headers, params=params)
        elif method == "POST":
            response = await http_client.post(full_url, headers=headers, json=json_data)
        elif method == "PUT":
            response = await http_client.put(full_url, headers=headers, json=json_data)
        elif method == "DELETE":
            response = await http_client.delete(full_url, headers=headers)
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")
        
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(
            method=method, endpoint=path, target_service=service_name
        ).observe(latency)
        
        if response.status_code >= 500:
            if cb:
                cb.record_failure()
            UPSTREAM_ERRORS.labels(target_service=service_name, error_type="5xx").inc()
            REQUEST_COUNT.labels(
                method=method, endpoint=path, status=response.status_code, target_service=service_name
            ).inc()
            raise HTTPException(status_code=response.status_code, detail="Upstream error")
        
        if cb:
            cb.record_success()
        
        REQUEST_COUNT.labels(
            method=method, endpoint=path, status=response.status_code, target_service=service_name
        ).inc()
        
        return response.json()
    
    except httpx.TimeoutException:
        if cb:
            cb.record_failure()
        UPSTREAM_ERRORS.labels(target_service=service_name, error_type="timeout").inc()
        REQUEST_COUNT.labels(
            method=method, endpoint=path, status=504, target_service=service_name
        ).inc()
        raise HTTPException(status_code=504, detail=f"Service {service_name} timeout")
    
    except httpx.ConnectError:
        if cb:
            cb.record_failure()
        UPSTREAM_ERRORS.labels(target_service=service_name, error_type="connection").inc()
        REQUEST_COUNT.labels(
            method=method, endpoint=path, status=503, target_service=service_name
        ).inc()
        raise HTTPException(status_code=503, detail=f"Cannot connect to {service_name}")
    
    finally:
        ACTIVE_CONNECTIONS.dec()

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
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/ready")
async def readiness():
    """Readiness probe - checks upstream services"""
    services_status = {}
    
    for name, url in [
        ("auth", AUTH_SERVICE_URL),
        ("order", ORDER_SERVICE_URL),
        ("payment", PAYMENT_SERVICE_URL),
        ("inventory", INVENTORY_SERVICE_URL),
        ("notification", NOTIFICATION_SERVICE_URL)
    ]:
        try:
            response = await http_client.get(f"{url}/health", timeout=5.0)
            services_status[name] = "healthy" if response.status_code == 200 else "unhealthy"
        except:
            services_status[name] = "unreachable"
    
    all_healthy = all(s == "healthy" for s in services_status.values())
    
    return {
        "status": "ready" if all_healthy else "degraded",
        "services": services_status
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    update_resource_metrics()
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

# Rate limit middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for health/metrics
    if request.url.path in ["/health", "/ready", "/metrics"]:
        return await call_next(request)
    
    client_ip = get_client_ip(request)
    
    if not check_rate_limit(client_ip):
        REQUEST_COUNT.labels(
            method=request.method, endpoint=request.url.path, 
            status=429, target_service="gateway"
        ).inc()
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"}
        )
    
    return await call_next(request)

# Auth routes
@app.post("/api/auth/login")
async def login(credentials: LoginRequest):
    """Proxy login to auth service"""
    return await proxy_request(
        "auth", AUTH_SERVICE_URL, "POST", "/login",
        json_data=credentials.model_dump()
    )

@app.post("/api/auth/signup")
async def signup(user: SignupRequest):
    """Proxy signup to auth service"""
    return await proxy_request(
        "auth", AUTH_SERVICE_URL, "POST", "/signup",
        json_data=user.model_dump()
    )

@app.post("/api/auth/verify")
async def verify_token(authorization: str = Header(None)):
    """Proxy token verification"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "auth", AUTH_SERVICE_URL, "POST", "/verify",
        headers=headers
    )

@app.get("/api/auth/me")
async def get_me(authorization: str = Header(None)):
    """Get current user"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "auth", AUTH_SERVICE_URL, "GET", "/me",
        headers=headers
    )

# Order routes
@app.post("/api/orders")
async def create_order(order: OrderRequest, authorization: str = Header(None)):
    """Create new order"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "order", ORDER_SERVICE_URL, "POST", "/orders",
        headers=headers, json_data=order.model_dump()
    )

@app.get("/api/orders")
async def list_orders(authorization: str = Header(None)):
    """List user orders"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "order", ORDER_SERVICE_URL, "GET", "/orders",
        headers=headers
    )

@app.get("/api/orders/{order_id}")
async def get_order(order_id: str, authorization: str = Header(None)):
    """Get order details"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "order", ORDER_SERVICE_URL, "GET", f"/orders/{order_id}",
        headers=headers
    )

# Payment routes
@app.post("/api/payments")
async def process_payment(payment: PaymentRequest, authorization: str = Header(None)):
    """Process payment"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "payment", PAYMENT_SERVICE_URL, "POST", "/pay",
        headers=headers, json_data=payment.model_dump()
    )

@app.get("/api/payments/{payment_id}")
async def get_payment(payment_id: str, authorization: str = Header(None)):
    """Get payment status"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "payment", PAYMENT_SERVICE_URL, "GET", f"/payments/{payment_id}",
        headers=headers
    )

# Inventory routes
@app.get("/api/inventory")
async def list_inventory():
    """List all inventory"""
    return await proxy_request(
        "inventory", INVENTORY_SERVICE_URL, "GET", "/stock"
    )

@app.get("/api/inventory/{item}")
async def get_item_stock(item: str):
    """Get item stock"""
    return await proxy_request(
        "inventory", INVENTORY_SERVICE_URL, "GET", f"/stock/{item}"
    )

@app.post("/api/inventory/{item}/reserve")
async def reserve_item(item: str, qty: int = 1, authorization: str = Header(None)):
    """Reserve inventory item"""
    headers = {"Authorization": authorization} if authorization else {}
    return await proxy_request(
        "inventory", INVENTORY_SERVICE_URL, "POST", f"/reserve/{item}",
        headers=headers, params={"qty": qty}
    )

# Notification routes (internal, but exposed for testing)
@app.post("/api/notifications")
async def send_notification(message: str = "Test notification"):
    """Send notification"""
    return await proxy_request(
        "notification", NOTIFICATION_SERVICE_URL, "POST", "/notify",
        json_data={"message": message}
    )

# Service discovery / status
@app.get("/api/services")
async def list_services():
    """List all registered services and their status"""
    services = {}
    
    for name, url in [
        ("auth-service", AUTH_SERVICE_URL),
        ("order-service", ORDER_SERVICE_URL),
        ("payment-service", PAYMENT_SERVICE_URL),
        ("inventory-service", INVENTORY_SERVICE_URL),
        ("notification-service", NOTIFICATION_SERVICE_URL)
    ]:
        cb = circuit_breakers.get(name.replace("-service", ""))
        try:
            response = await http_client.get(f"{url}/health", timeout=3.0)
            services[name] = {
                "url": url,
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "circuit_breaker": cb.state if cb else "unknown"
            }
        except:
            services[name] = {
                "url": url,
                "status": "unreachable",
                "circuit_breaker": cb.state if cb else "unknown"
            }
    
    return {"services": services}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
