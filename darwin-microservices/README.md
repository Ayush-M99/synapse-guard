# Darwin Chaos Platform - Target Microservices

Production-ready microservices designed as chaos engineering targets for the Darwin Chaos Platform. These services simulate a realistic e-commerce system with intentional failure injection points.

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                     API Gateway                          │
                    │          (Rate Limiting, Circuit Breaker)                │
                    └─────────────────────┬───────────────────────────────────┘
                                          │
        ┌─────────────┬─────────────┬─────┴─────┬─────────────┬─────────────┐
        │             │             │           │             │             │
   ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐  ┌───▼───┐  ┌──────▼──────┐
   │  Auth   │  │   Order   │  │ Payment │  │Inventory│ │ Notification │
   │ Service │  │  Service  │  │ Service │  │ Service │ │   Service    │
   └────┬────┘  └─────┬─────┘  └────┬────┘  └───┬───┘  └──────┬──────┘
        │             │             │           │             │
        └─────────────┴─────────────┴───────────┴─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
         ┌────▼────┐           ┌────▼────┐           ┌────▼────┐
         │PostgreSQL│           │  Redis  │           │  NATS   │
         │   DNA    │           │ T-Cell  │           │ Neural  │
         │  Store   │           │ Memory  │           │   Bus   │
         └─────────┘           └─────────┘           └─────────┘
```

## Services

### Auth Service (Port 8001)
- JWT-based authentication
- User registration and login
- Token verification
- Session management

**Endpoints:**
- `POST /signup` - Register new user
- `POST /login` - Authenticate user
- `POST /verify` - Verify JWT token
- `GET /me` - Get current user
- `POST /logout` - Invalidate session

### API Gateway (Port 8000)
- Central routing for all services
- Rate limiting (configurable)
- Circuit breaker per service
- Request/response metrics

**Endpoints:**
- `GET /api/services` - List service status
- `/api/auth/*` - Proxy to auth service
- `/api/orders/*` - Proxy to order service
- `/api/payments/*` - Proxy to payment service
- `/api/inventory/*` - Proxy to inventory service
- `/api/notifications/*` - Proxy to notification service

### Order Service (Port 8002)
- Order creation and management
- Orchestrates payment, inventory, notification
- PostgreSQL-backed persistence

**Endpoints:**
- `POST /orders` - Create order
- `GET /orders` - List orders
- `GET /orders/{id}` - Get order details
- `PUT /orders/{id}/cancel` - Cancel order

### Payment Service (Port 8003)
- Simulated payment processing
- Configurable failure rate
- Transaction history

**Endpoints:**
- `POST /pay` - Process payment
- `GET /payments/{id}` - Get payment status
- `GET /payments/order/{id}` - Get payments for order
- `POST /payments/{id}/refund` - Refund payment
- `GET /stats` - Payment statistics

### Inventory Service (Port 8004)
- Redis-backed stock management
- In-memory fallback
- Reservation system

**Endpoints:**
- `GET /stock` - List all inventory
- `GET /stock/{id}` - Get item stock
- `POST /reserve/{id}` - Reserve stock
- `POST /decrease/{id}` - Decrease stock
- `POST /increase/{id}` - Restock
- `GET /search?q=` - Search items
- `GET /low-stock` - Low stock alerts

### Notification Service (Port 8005)
- Async queue-based processing
- Multiple notification types
- Bulk sending support

**Endpoints:**
- `POST /notify` - Send notification (sync)
- `POST /notify/async` - Queue notification
- `POST /notify/bulk` - Bulk send
- `GET /notifications` - List sent notifications
- `GET /stats` - Notification statistics

## Quick Start

### Local Development (Docker Compose)

```bash
# Start all services
./build-deploy.sh local

# Or manually
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down -v
```

### Kubernetes Deployment

```bash
# Build images
./build-deploy.sh build

# Push to registry (optional)
REGISTRY=your-registry.io ./build-deploy.sh push

# Deploy to K8s
./build-deploy.sh deploy

# Check status
kubectl get pods -n darwin-microservices
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://chaos:chaospassword@postgres:5432/chaos_dna` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `NATS_URL` | `nats://nats:4222` | NATS connection |
| `JWT_SECRET` | `darwin-chaos-jwt-secret` | JWT signing key |
| `PAYMENT_FAILURE_RATE` | `0.1` | Payment failure probability |
| `NOTIFICATION_FAILURE_RATE` | `0.1` | Notification failure probability |
| `RATE_LIMIT_REQUESTS` | `100` | Requests per window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |

## Metrics

All services expose Prometheus metrics at `/metrics`:

### Common Metrics
- `{service}_requests_total` - Request count by method/endpoint/status
- `{service}_request_latency_seconds` - Request latency histogram
- `{service}_cpu_usage_pct` - CPU usage percentage
- `{service}_memory_usage_pct` - Memory usage percentage

### Service-Specific Metrics

**Auth Service:**
- `auth_active_sessions` - Current active sessions
- `auth_login_attempts_total` - Login attempts by result

**API Gateway:**
- `gateway_active_connections` - Active client connections
- `gateway_circuit_breaker_state` - Circuit breaker state per service
- `gateway_upstream_errors_total` - Upstream service errors

**Order Service:**
- `orders_created_total` - Orders created by status
- `order_value_dollars` - Order value histogram
- `order_downstream_calls_total` - Downstream service calls

**Payment Service:**
- `payments_processed_total` - Payments by status/method
- `payment_amount_dollars` - Payment amount histogram
- `payment_processing_time_seconds` - Processing time

**Inventory Service:**
- `inventory_stock_operations_total` - Stock operations by type
- `inventory_cache_hits_total` - Redis cache hits
- `inventory_stock_level` - Current stock level per item

**Notification Service:**
- `notifications_sent_total` - Notifications by type/status
- `notification_queue_size` - Queue depth
- `notification_processing_time_seconds` - Processing time

## Nerve Ending Sidecar

Each service can be deployed with a nerve ending sidecar that:
- Monitors CPU, memory, error rate, latency
- Publishes alerts to NATS (`nerve.{service}.alert`)
- Recommends remediation actions
- Triggers reflex isolation

### Alert Types
- `cpu_high` - CPU usage exceeds threshold
- `memory_high` - Memory usage exceeds threshold
- `error_rate_high` - Error rate exceeds threshold
- `latency_high` - Average latency exceeds threshold
- `health_check_failed` - Health endpoint failures

### Recommended Actions
- `scale_horizontal` - Add more replicas
- `restart_pod` - Restart the problematic pod
- `isolate_pod` - Remove from load balancer
- `traffic_shift` - Redirect traffic to healthy pods
- `circuit_breaker` - Enable circuit breaker

## Chaos Engineering Integration

These services are designed to be chaos targets:

1. **Failure Injection** - Configurable failure rates for payment and notification
2. **Latency Injection** - Simulated processing delays
3. **Resource Exhaustion** - Memory/CPU monitoring with thresholds
4. **Circuit Breaker** - Gateway implements circuit breaker pattern
5. **Health Degradation** - Services report detailed health status

### Testing Chaos Scenarios

```bash
# Increase payment failures
docker-compose exec payment-service env PAYMENT_FAILURE_RATE=0.5

# Test circuit breaker (kill a service)
docker-compose stop inventory-service

# Observe recovery
docker-compose start inventory-service

# Monitor metrics
curl http://localhost:8000/metrics
```

## Project Structure

```
darwin-microservices/
├── auth-service/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── api-gateway/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── order-service/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── payment-service/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── inventory-service/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── notification-service/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── nerve-ending/
│   ├── nerve_ending.py
│   └── Dockerfile
├── k8s/
│   ├── k8s-manifests.yaml
│   └── nerve-ending-sidecar.yaml
├── monitoring/
│   └── prometheus.yml
├── docker-compose.yml
├── build-deploy.sh
└── README.md
```

## License

Part of the Darwin Chaos Platform - Autonomous Self-Healing Kubernetes System
