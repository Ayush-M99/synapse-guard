# Phase 2.2: Build & Deploy Microservices - Manual Instructions

## Prerequisites
1. **Docker Desktop** must be running
2. **Minikube** must be installed
3. All 6 microservices customized (✅ DONE)

## STEP 1: Start Docker Desktop

**Windows 11:**
- Open Windows Start Menu
- Search for "Docker Desktop"
- Click to launch it
- Wait 2-3 minutes for startup

**Verify Docker is running:**
```bash
docker ps
# Should return: (empty list, no errors)
```

## STEP 2: Start Minikube

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
```

**Verify Minikube is running:**
```bash
minikube status
# Should show: minikube: Running
```

## STEP 3: Build All 6 Docker Images

Navigate to microservices directory:
```bash
cd e:\#EditorCodes\banglore_Hackthon\microservices
```

Build each image:
```bash
# Auth Service
docker build -t darwin/auth-service:v1.0 auth-service/

# Gateway Service
docker build -t darwin/gateway-service:v1.0 gateway-service/

# Payment Service
docker build -t darwin/payment-service:v1.0 payment-service/

# Order Service
docker build -t darwin/order-service:v1.0 order-service/

# Inventory Service
docker build -t darwin/inventory-service:v1.0 inventory-service/

# Notification Service
docker build -t darwin/notification-service:v1.0 notification-service/
```

**Verify images are built:**
```bash
docker images | grep darwin
# Should show 6 images
```

## STEP 4: Load Images into Minikube

```bash
minikube image load darwin/auth-service:v1.0
minikube image load darwin/gateway-service:v1.0
minikube image load darwin/payment-service:v1.0
minikube image load darwin/order-service:v1.0
minikube image load darwin/inventory-service:v1.0
minikube image load darwin/notification-service:v1.0
```

**Verify images in Minikube:**
```bash
minikube image ls | grep darwin
# Should show 6 darwin images
```

## STEP 5: Create Kubernetes Manifests & Deploy

Create namespace:
```bash
kubectl create namespace darwin-target
```

Deploy all services:
```bash
# Apply deployment manifests
kubectl apply -f k8s/target/

# Or use the automated script
bash build-and-deploy.sh
```

## STEP 6: Verify Deployment

Check pods are running:
```bash
kubectl get pods -n darwin-target
# Should show 12 pods (6 services × 2 replicas)

# Expected output:
# NAME                                      READY   STATUS    RESTARTS
# auth-service-abc123                       1/1     Running   0
# auth-service-def456                       1/1     Running   0
# gateway-service-ghi789                    1/1     Running   0
# gateway-service-jkl012                    1/1     Running   0
# payment-service-mno345                    1/1     Running   0
# payment-service-pqr678                    1/1     Running   0
# order-service-stu901                      1/1     Running   0
# order-service-vwx234                      1/1     Running   0
# inventory-service-yz5678                  1/1     Running   0
# inventory-service-abcd901                 1/1     Running   0
# notification-service-efgh234              1/1     Running   0
# notification-service-ijkl567              1/1     Running   0
```

## STEP 7: Test Service Health

Test a single service:
```bash
# Port-forward to payment-service
kubectl port-forward -n darwin-target svc/payment-service 8080:8080

# In another terminal, test health endpoint:
curl http://localhost:8080/health
# Expected: {"status":"healthy","service":"payment-service","uptime_seconds":...}

# Test metrics endpoint:
curl http://localhost:8080/metrics
# Expected: Prometheus format metrics
```

## STEP 8: View Service Logs

Monitor a specific service:
```bash
kubectl logs -n darwin-target -l app=payment-service -f

# Or monitor all services:
kubectl logs -n darwin-target -f
```

## Test All Services

Quick validation script:
```bash
#!/bin/bash
NAMESPACE="darwin-target"
SERVICES=("auth-service" "gateway-service" "payment-service" "order-service" "inventory-service" "notification-service")

for service in "${SERVICES[@]}"; do
    echo "Testing $service..."
    kubectl port-forward -n $NAMESPACE "svc/$service" 9999:8080 &
    PF_PID=$!
    sleep 1

    HEALTH=$(curl -s http://localhost:9999/health | jq -r '.status')
    echo "  Health: $HEALTH"

    kill $PF_PID 2>/dev/null
done
```

## Troubleshooting

**Pods not starting?**
- Check logs: `kubectl logs -n darwin-target <pod-name>`
- Check events: `kubectl describe pod -n darwin-target <pod-name>`
- Check images loaded: `minikube image ls | grep darwin`

**Docker image build fail?**
- Check Dockerfile exists: `ls microservices/<service>/Dockerfile`
- Run with verbose: `docker build --progress=plain -t darwin/<service>:v1.0 <service>/`

**Port-forward not working?**
- Kill any existing port-forwards: `pkill -f "kubectl port-forward"`
- Try different port: `kubectl port-forward ... 8080:8080`

## Success Criteria

✅ All completed when:
1. 12 pods are Running
2. All pods have READY 1/1
3. Health checks return 200 OK for all services
4. Metrics endpoints return Prometheus format
5. Pod names include service name (auth-service, payment-service, etc.)
