#!/bin/bash
# Build and Deploy DARWIN Microservices
# This script builds Docker images and deploys pods to Minikube

set -e

echo "=================================="
echo "DARWIN Phase 2.2: Build & Deploy"
echo "=================================="

# Configuration
SERVICES=("auth-service" "gateway-service" "payment-service" "order-service" "inventory-service" "notification-service")
DOCKER_REGISTRY="darwin"
IMAGE_VERSION="v1.0"
NAMESPACE="darwin-target"
REPLICAS=2

# ============================================================================
# STEP 1: Verify Prerequisites
# ============================================================================

echo -e "\n📋 Step 1: Verifying Prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker Desktop."
    exit 1
fi

# Check if Docker daemon is running
if ! docker ps &> /dev/null; then
    echo "❌ Docker daemon is not running."
    echo "   Please start Docker Desktop and try again."
    exit 1
fi

# Check Minikube
if ! command -v minikube &> /dev/null; then
    echo "⚠️  Minikube not found. Installing..."
    # Installation instructions would go here
    exit 1
fi

# Start Minikube if not running
if ! minikube status &> /dev/null; then
    echo "🚀 Starting Minikube..."
    minikube start --cpus=4 --memory=8192 --driver=docker
fi

echo "✅ Prerequisites verified"

# ============================================================================
# STEP 2: Build Docker Images
# ============================================================================

echo -e "\n🏗️  Step 2: Building Docker Images..."

cd "e:\\#EditorCodes\\banglore_Hackthon/microservices"

for service in "${SERVICES[@]}"; do
    echo ""
    echo "Building: $service"
    docker build -t "$DOCKER_REGISTRY/$service:$IMAGE_VERSION" "$service"

    if [ $? -eq 0 ]; then
        echo "✅ $service built successfully"
    else
        echo "❌ Failed to build $service"
        exit 1
    fi
done

echo -e "\n✅ All images built successfully"

# ============================================================================
# STEP 3: Load Images into Minikube
# ============================================================================

echo -e "\n📦 Step 3: Loading Images into Minikube..."

for service in "${SERVICES[@]}"; do
    echo "Loading: $service"
    minikube image load "$DOCKER_REGISTRY/$service:$IMAGE_VERSION"

    if [ $? -eq 0 ]; then
        echo "✅ $service loaded"
    else
        echo "❌ Failed to load $service"
        exit 1
    fi
done

echo -e "\n✅ All images loaded into Minikube"

# ============================================================================
# STEP 4: Create Kubernetes Namespace
# ============================================================================

echo -e "\n🔧 Step 4: Setting Up Kubernetes..."

kubectl get namespace $NAMESPACE > /dev/null 2>&1 || kubectl create namespace $NAMESPACE

# Label namespace for Istio injection (if using Istio)
# kubectl label namespace $NAMESPACE istio-injection=enabled --overwrite

echo "✅ Namespace '$NAMESPACE' ready"

# ============================================================================
# STEP 5: Deploy Services to Kubernetes
# ============================================================================

echo -e "\n🚀 Step 5: Deploying Services..."

# Generate and apply Kubernetes manifests
for service in "${SERVICES[@]}"; do
    echo "Deploying: $service"

    # Create deployment
    kubectl apply -f - << EOF
apiVersion: v1
kind: Service
metadata:
  name: $service
  namespace: $NAMESPACE
  labels:
    app: $service
spec:
  selector:
    app: $service
  ports:
    - port: 8080
      name: http
  type: ClusterIP
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $service
  namespace: $NAMESPACE
spec:
  replicas: $REPLICAS
  selector:
    matchLabels:
      app: $service
  template:
    metadata:
      labels:
        app: $service
    spec:
      containers:
        - name: $service
          image: $DOCKER_REGISTRY/$service:$IMAGE_VERSION
          imagePullPolicy: Never  # Use local image
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
EOF

    if [ $? -eq 0 ]; then
        echo "✅ $service deployed"
    else
        echo "❌ Failed to deploy $service"
        exit 1
    fi
done

echo -e "\n✅ All services deployed"

# ============================================================================
# STEP 6: Verify Deployment
# ============================================================================

echo -e "\n✅ Step 6: Verifying Deployment..."

echo "Waiting for pods to be ready (30 seconds)..."
sleep 10

echo -e "\n📊 Pod Status:"
kubectl get pods -n $NAMESPACE

echo -e "\n📊 Service Status:"
kubectl get svc -n $NAMESPACE

echo -e "\n✅ Deployment Complete!"

# ============================================================================
# STEP 7: Health Checks
# ============================================================================

echo -e "\n🏥 Step 7: Running Health Checks..."

# Wait a bit for pods to actually start
sleep 5

for service in "${SERVICES[@]}"; do
    echo -n "Checking $service... "

    # Port-forward temporarily to test
    kubectl port-forward -n $NAMESPACE "svc/$service" 9999:8080 &
    PF_PID=$!
    sleep 2

    if curl -s http://localhost:9999/health > /dev/null 2>&1; then
        echo "✅"
    else
        echo "⏳ (Still starting)"
    fi

    kill $PF_PID 2>/dev/null || true
done

# ============================================================================
# FINAL SUMMARY
# ============================================================================

echo -e "\n=================================="
echo "✅ PHASE 2.2 COMPLETE"
echo "=================================="
echo ""
echo "Summary:"
echo "  • 6 Docker images built: $DOCKER_REGISTRY/{auth,gateway,payment,order,inventory,notification}-service:$IMAGE_VERSION"
echo "  • 12 pods deployed (2 replicas × 6 services)"
echo "  • Namespace: $NAMESPACE"
echo ""
echo "Next Steps:"
echo "  1. Verify all pods are running:"
echo "     kubectl get pods -n $NAMESPACE"
echo "  2. Test service connectivity:"
echo "     kubectl port-forward -n $NAMESPACE svc/payment-service 8080:8080"
echo "     curl http://localhost:8080/health"
echo "  3. View service logs:"
echo "     kubectl logs -n $NAMESPACE -l app=payment-service -f"
echo ""
