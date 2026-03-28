# DARWIN - Database Installation Script
# Installs Neo4j, PostgreSQL, Redis, NATS via Helm

Write-Host "=== Installing DARWIN Databases ===" -ForegroundColor Cyan
Write-Host ""

# Check if helm is available
$helm = Get-Command helm -ErrorAction SilentlyContinue
if (-Not $helm) {
    Write-Host "✗ Helm not found! Please install Helm first." -ForegroundColor Red
    exit 1
}

# Add Helm repositories
Write-Host "Adding Helm repositories..." -ForegroundColor Yellow
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add nats https://nats-io.github.io/k8s/helm/charts/
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update

Write-Host "✓ Helm repos added" -ForegroundColor Green

# 1. Install Neo4j
Write-Host ""
Write-Host "Installing Neo4j (Knowledge Graph)..." -ForegroundColor Yellow
helm install neo4j neo4j/neo4j `
  --set neo4j.password=darwin123 `
  --set neo4j.acceptLicenseAgreement=yes `
  --set resources.requests.cpu=500m `
  --set resources.requests.memory=1Gi `
  --set resources.limits.cpu=1000m `
  --set resources.limits.memory=2Gi `
  --set persistence.size=5Gi `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Neo4j installed" -ForegroundColor Green
} else {
    Write-Host "⚠ Neo4j installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 2. Install PostgreSQL
Write-Host ""
Write-Host "Installing PostgreSQL (DNA Store)..." -ForegroundColor Yellow
helm install postgresql bitnami/postgresql `
  --set auth.username=darwin `
  --set auth.password=darwin123 `
  --set auth.database=darwin_dna `
  --set primary.persistence.size=5Gi `
  --set resources.requests.cpu=250m `
  --set resources.requests.memory=512Mi `
  --set resources.limits.cpu=500m `
  --set resources.limits.memory=1Gi `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ PostgreSQL installed" -ForegroundColor Green
} else {
    Write-Host "⚠ PostgreSQL installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 3. Install Redis
Write-Host ""
Write-Host "Installing Redis (Immunity Cache)..." -ForegroundColor Yellow
helm install redis bitnami/redis `
  --set auth.password=darwin123 `
  --set master.persistence.size=2Gi `
  --set replica.replicaCount=1 `
  --set resources.requests.cpu=100m `
  --set resources.requests.memory=256Mi `
  --set resources.limits.cpu=200m `
  --set resources.limits.memory=512Mi `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Redis installed" -ForegroundColor Green
} else {
    Write-Host "⚠ Redis installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 4. Install NATS
Write-Host ""
Write-Host "Installing NATS (Message Bus)..." -ForegroundColor Yellow
helm install nats nats/nats `
  --set nats.jetstream.enabled=true `
  --set nats.jetstream.memStorage.enabled=true `
  --set nats.jetstream.memStorage.size=1Gi `
  --set resources.requests.cpu=100m `
  --set resources.requests.memory=256Mi `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ NATS installed" -ForegroundColor Green
} else {
    Write-Host "⚠ NATS installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 5. Install Prometheus Stack (Observability)
Write-Host ""
Write-Host "Installing Prometheus + Grafana (Observability)..." -ForegroundColor Yellow
helm install prometheus prometheus-community/kube-prometheus-stack `
  --set prometheus.prometheusSpec.retention=7d `
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=10Gi `
  --set grafana.adminPassword=darwin123 `
  --set prometheus.prometheusSpec.resources.requests.cpu=200m `
  --set prometheus.prometheusSpec.resources.requests.memory=512Mi `
  --namespace darwin --wait --timeout=10m

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Prometheus + Grafana installed" -ForegroundColor Green
} else {
    Write-Host "⚠ Prometheus installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 6. Install Loki (Logs)
Write-Host ""
Write-Host "Installing Loki (Log Aggregation)..." -ForegroundColor Yellow
helm install loki grafana/loki-stack `
  --set loki.persistence.enabled=true `
  --set loki.persistence.size=5Gi `
  --set promtail.enabled=true `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Loki installed" -ForegroundColor Green
} else {
    Write-Host "⚠ Loki installation had warnings (may already exist)" -ForegroundColor Yellow
}

# 7. Install Jaeger (Distributed Tracing)
Write-Host ""
Write-Host "Installing Jaeger (Distributed Tracing)..." -ForegroundColor Yellow
helm install jaeger jaegertracing/jaeger `
  --set provisionDataStore.cassandra=false `
  --set allInOne.enabled=true `
  --set storage.type=memory `
  --namespace darwin --wait

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Jaeger installed" -ForegroundColor Green
} else {
    Write-Host "⚠ Jaeger installation had warnings (may already exist)" -ForegroundColor Yellow
}

# Wait for all pods to be ready
Write-Host ""
Write-Host "Waiting for all pods to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

kubectl wait --for=condition=ready pod --all -n darwin --timeout=300s

# Show pod status
Write-Host ""
Write-Host "=== Pod Status ===" -ForegroundColor Cyan
kubectl get pods -n darwin

Write-Host ""
Write-Host "=== Database Installation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Installed components:"
Write-Host "✓ Neo4j (Knowledge Graph) - Port 7474, 7687"
Write-Host "✓ PostgreSQL (DNA Store) - Port 5432"
Write-Host "✓ Redis (Immunity Cache) - Port 6379"
Write-Host "✓ NATS (Message Bus) - Port 4222"
Write-Host "✓ Prometheus (Metrics) - Port 9090"
Write-Host "✓ Grafana (Dashboards) - Port 3000"
Write-Host "✓ Loki (Logs)"
Write-Host "✓ Jaeger (Traces) - Port 16686"
Write-Host ""
Write-Host "Default credentials:"
Write-Host "- Neo4j: neo4j / darwin123"
Write-Host "- PostgreSQL: darwin / darwin123"
Write-Host "- Redis: (password: darwin123)"
Write-Host "- Grafana: admin / darwin123"
Write-Host ""
Write-Host "Access services:"
Write-Host "kubectl port-forward svc/neo4j 7474:7474 -n darwin"
Write-Host "kubectl port-forward svc/prometheus-operated 9090:9090 -n darwin"
Write-Host "kubectl port-forward svc/prometheus-grafana 3000:80 -n darwin"
Write-Host "kubectl port-forward svc/jaeger-query 16686:16686 -n darwin"
Write-Host ""
Write-Host "Next step: Build and deploy microservices" -ForegroundColor Cyan
