"""
Auth Service - JWT Authentication with PostgreSQL
Part of the Darwin Chaos Platform target microservices
"""
import os
import time
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional

import jwt
import asyncpg
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from starlette.responses import Response

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "darwin-secret-key-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://chaos:chaospassword@postgres:5432/chaos_dna")
SERVICE_NAME = "auth-service"

# Prometheus Metrics
REQUEST_COUNT = Counter(
    "auth_requests_total",
    "Total auth requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "auth_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
ACTIVE_SESSIONS = Gauge(
    "auth_active_sessions",
    "Number of active user sessions"
)
LOGIN_ATTEMPTS = Counter(
    "auth_login_attempts_total",
    "Total login attempts",
    ["status"]
)
CPU_USAGE = Gauge("auth_cpu_usage_pct", "CPU usage percentage")
MEMORY_USAGE = Gauge("auth_memory_usage_pct", "Memory usage percentage")

# Database pool
db_pool: Optional[asyncpg.Pool] = None

# Models
class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str
    expires_in: int
    token_type: str = "Bearer"

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    created_at: datetime

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    # Startup
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
    title="Auth Service",
    description="JWT Authentication Service for Darwin Chaos Platform",
    version="1.0.0",
    lifespan=lifespan
)

security = HTTPBearer(auto_error=False)

# Database initialization
async def init_db():
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                email VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                last_login TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                token_hash VARCHAR(256) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        # Create default user for testing
        try:
            await conn.execute("""
                INSERT INTO users (username, password_hash, email)
                VALUES ($1, $2, $3)
                ON CONFLICT (username) DO NOTHING
            """, "testuser", hash_password("testpass"), "test@darwin.io")
        except:
            pass

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_jwt_token(user_id: int, username: str) -> tuple[str, datetime]:
    expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expires_at,
        "iat": datetime.utcnow(),
        "jti": secrets.token_hex(16)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="No authorization header")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def update_resource_metrics():
    try:
        import psutil
        CPU_USAGE.set(psutil.cpu_percent())
        MEMORY_USAGE.set(psutil.virtual_memory().percent)
    except:
        pass

# Routes
@app.get("/health")
async def health():
    """Health check endpoint for Kubernetes probes"""
    db_status = "connected" if db_pool else "disconnected"
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    }

@app.get("/ready")
async def readiness():
    """Readiness probe - checks if service can handle requests"""
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
    """Prometheus metrics endpoint"""
    update_resource_metrics()
    return Response(generate_latest(), media_type="text/plain; charset=utf-8")

@app.post("/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    """Register a new user"""
    start_time = time.time()
    
    if not db_pool:
        REQUEST_COUNT.labels(method="POST", endpoint="/signup", status="503").inc()
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM users WHERE username = $1", user.username
            )
            if existing:
                REQUEST_COUNT.labels(method="POST", endpoint="/signup", status="409").inc()
                raise HTTPException(status_code=409, detail="Username already exists")
            
            result = await conn.fetchrow("""
                INSERT INTO users (username, password_hash, email)
                VALUES ($1, $2, $3)
                RETURNING id, username, email, created_at
            """, user.username, hash_password(user.password), user.email)
            
            REQUEST_COUNT.labels(method="POST", endpoint="/signup", status="201").inc()
            REQUEST_LATENCY.labels(method="POST", endpoint="/signup").observe(time.time() - start_time)
            
            return UserResponse(
                id=result["id"],
                username=result["username"],
                email=result["email"],
                created_at=result["created_at"]
            )
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/signup", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Authenticate user and return JWT token"""
    start_time = time.time()
    
    if not db_pool:
        # Fallback for demo mode without DB
        if credentials.username == "testuser" and credentials.password == "testpass":
            token, _ = create_jwt_token(1, credentials.username)
            LOGIN_ATTEMPTS.labels(status="success").inc()
            return TokenResponse(token=token, expires_in=JWT_EXPIRATION_HOURS * 3600)
        LOGIN_ATTEMPTS.labels(status="failed").inc()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT id, username, password_hash FROM users WHERE username = $1
            """, credentials.username)
            
            if not user or user["password_hash"] != hash_password(credentials.password):
                LOGIN_ATTEMPTS.labels(status="failed").inc()
                REQUEST_COUNT.labels(method="POST", endpoint="/login", status="401").inc()
                raise HTTPException(status_code=401, detail="Invalid credentials")
            
            token, expires_at = create_jwt_token(user["id"], user["username"])
            
            # Store session
            await conn.execute("""
                INSERT INTO sessions (user_id, token_hash, expires_at)
                VALUES ($1, $2, $3)
            """, user["id"], hashlib.sha256(token.encode()).hexdigest(), expires_at)
            
            # Update last login
            await conn.execute(
                "UPDATE users SET last_login = NOW() WHERE id = $1", user["id"]
            )
            
            # Update metrics
            active = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE is_active = TRUE AND expires_at > NOW()"
            )
            ACTIVE_SESSIONS.set(active)
            
            LOGIN_ATTEMPTS.labels(status="success").inc()
            REQUEST_COUNT.labels(method="POST", endpoint="/login", status="200").inc()
            REQUEST_LATENCY.labels(method="POST", endpoint="/login").observe(time.time() - start_time)
            
            return TokenResponse(token=token, expires_in=JWT_EXPIRATION_HOURS * 3600)
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/login", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify")
async def verify(payload: dict = Depends(verify_token)):
    """Verify a JWT token - used by other services"""
    REQUEST_COUNT.labels(method="POST", endpoint="/verify", status="200").inc()
    return {
        "valid": True,
        "user_id": payload["sub"],
        "username": payload["username"],
        "expires": payload["exp"]
    }

@app.post("/logout")
async def logout(payload: dict = Depends(verify_token)):
    """Invalidate user session"""
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE sessions SET is_active = FALSE 
                WHERE user_id = $1 AND is_active = TRUE
            """, int(payload["sub"]))
            ACTIVE_SESSIONS.dec()
    
    REQUEST_COUNT.labels(method="POST", endpoint="/logout", status="200").inc()
    return {"status": "logged_out"}

@app.get("/me", response_model=UserResponse)
async def get_current_user(payload: dict = Depends(verify_token)):
    """Get current user info"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, email, created_at FROM users WHERE id = $1",
            int(payload["sub"])
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"]
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
