#!/bin/bash
# Darwin Chaos Platform - Microservices Build & Deploy Script
# Usage: ./build-deploy.sh [command] [options]
#
# Commands:
#   build       Build all Docker images
#   push        Push images to registry
#   deploy      Deploy to Kubernetes
#   local       Start local development with docker-compose
#   clean       Clean up resources
#   test        Run health checks on all services

set -e

# Configuration
REGISTRY="${REGISTRY:-docker.io}"
IMAGE_PREFIX="${IMAGE_PREFIX:-darwin}"
VERSION="${VERSION:-latest}"
NAMESPACE="${NAMESPACE:-darwin-microservices}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Services to build
SERVICES=(
    "auth-service"
    "api-gateway"
    "order-service"
    "payment-service"
    "inventory-service"
    "notification-service"
    "nerve-ending"
)

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Build all Docker images
build_images() {
    log_info "Building Docker images..."
    
    for service in "${SERVICES[@]}"; do
        if [ -d "$service" ]; then
            log_info "Building $service:$VERSION"
            docker build -t "${IMAGE_PREFIX}/${service}:${VERSION}" "./${service}"
        else
            log_warn "Directory $service not found, skipping"
        fi
    done
    
    log_info "All images built successfully!"
}

# Push images to registry
push_images() {
    log_info "Pushing images to $REGISTRY..."
    
    for service in "${SERVICES[@]}"; do
        image="${IMAGE_PREFIX}/${service}:${VERSION}"
        target="${REGISTRY}/${image}"
        
        log_info "Tagging and pushing $service"
        docker tag "$image" "$target"
        docker push "$target"
    done
    
    log_info "All images pushed successfully!"
}

# Deploy to Kubernetes
deploy_k8s() {
    log_info "Deploying to Kubernetes namespace: $NAMESPACE"
    
    # Create namespace if it doesn't exist
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply manifests
    log_info "Applying Kubernetes manifests..."
    kubectl apply -f k8s/k8s-manifests.yaml
    
    # Wait for deployments
    log_info "Waiting for deployments to be ready..."
    for service in "${SERVICES[@]}"; do
        if [ "$service" != "nerve-ending" ]; then
            kubectl rollout status deployment/"$service" -n "$NAMESPACE" --timeout=120s || true
        fi
    done
    
    log_info "Deployment complete!"
    
    # Show status
    echo ""
    log_info "Deployment Status:"
    kubectl get pods -n "$NAMESPACE"
    echo ""
    kubectl get services -n "$NAMESPACE"
}

# Start local development environment
start_local() {
    log_info "Starting local development environment..."
    
    # Build images first
    docker-compose build
    
    # Start services
    docker-compose up -d
    
    # Wait for services to be healthy
    log_info "Waiting for services to start..."
    sleep 10
    
    # Show status
    docker-compose ps
    
    echo ""
    log_info "Services available at:"
    echo "  API Gateway:        http://localhost:8000"
    echo "  Auth Service:       http://localhost:8001"
    echo "  Order Service:      http://localhost:8002"
    echo "  Payment Service:    http://localhost:8003"
    echo "  Inventory Service:  http://localhost:8004"
    echo "  Notification:       http://localhost:8005"
    echo "  Prometheus:         http://localhost:9090"
    echo "  Grafana:            http://localhost:3000 (admin/darwin)"
    echo "  Neo4j Browser:      http://localhost:7474"
}

# Clean up resources
cleanup() {
    log_info "Cleaning up resources..."
    
    if [ "$1" == "local" ]; then
        docker-compose down -v
        log_info "Local environment cleaned up"
    elif [ "$1" == "k8s" ]; then
        kubectl delete -f k8s/k8s-manifests.yaml || true
        log_info "Kubernetes resources cleaned up"
    else
        log_info "Usage: $0 clean [local|k8s]"
    fi
}

# Test services health
test_services() {
    log_info "Testing service health..."
    
    local base_url="${1:-http://localhost}"
    local ports=(8000 8001 8002 8003 8004 8005)
    local names=("api-gateway" "auth" "order" "payment" "inventory" "notification")
    
    for i in "${!ports[@]}"; do
        port="${ports[$i]}"
        name="${names[$i]}"
        url="${base_url}:${port}/health"
        
        if curl -s -f "$url" > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} $name ($port): healthy"
        else
            echo -e "  ${RED}✗${NC} $name ($port): unhealthy"
        fi
    done
}

# Show help
show_help() {
    echo "Darwin Chaos Platform - Microservices Build & Deploy Script"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  build           Build all Docker images"
    echo "  push            Push images to registry"
    echo "  deploy          Deploy to Kubernetes"
    echo "  local           Start local development with docker-compose"
    echo "  clean [target]  Clean up resources (local|k8s)"
    echo "  test [url]      Run health checks on all services"
    echo "  help            Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  REGISTRY        Docker registry (default: docker.io)"
    echo "  IMAGE_PREFIX    Image name prefix (default: darwin)"
    echo "  VERSION         Image version tag (default: latest)"
    echo "  NAMESPACE       Kubernetes namespace (default: darwin-microservices)"
}

# Main
case "${1:-help}" in
    build)
        build_images
        ;;
    push)
        push_images
        ;;
    deploy)
        deploy_k8s
        ;;
    local)
        start_local
        ;;
    clean)
        cleanup "$2"
        ;;
    test)
        test_services "$2"
        ;;
    help|*)
        show_help
        ;;
esac
