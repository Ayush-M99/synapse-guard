# DARWIN Platform — Windows One-Command Startup
# Run: .\start.ps1
# Run with minikube: .\start.ps1 -WithMinikube

param(
    [switch]$WithMinikube,
    [switch]$SkipSeed,
    [switch]$DemoMode
)

$ErrorActionPreference = "Continue"

function Print-Header($text) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor White
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Print-OK($text)   { Write-Host "  [OK] $text" -ForegroundColor Green }
function Print-WARN($text) { Write-Host "  [!!] $text" -ForegroundColor Yellow }
function Print-ERR($text)  { Write-Host "  [XX] $text" -ForegroundColor Red }

Print-Header "DARWIN Platform — Startup"
Write-Host "  Time: $(Get-Date -Format 'HH:mm:ss')"

# ─── 1. Docker Compose (external services) ────────────────────────────────────
Print-Header "Step 1: Starting External Services (Docker Compose)"

if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    Print-ERR "Docker not found. Please install Docker Desktop."
    exit 1
}

docker compose -f docker-compose.yml up -d
if ($LASTEXITCODE -eq 0) {
    Print-OK "Redis, PostgreSQL, Neo4j, NATS, Prometheus, Loki, Grafana, Jaeger started"
} else {
    Print-WARN "docker compose had issues — check: docker compose logs"
}

# ─── 2. Wait for services to be ready ────────────────────────────────────────
Print-Header "Step 2: Waiting for services to be healthy"
Write-Host "  Waiting 15 seconds for databases to initialize..."
Start-Sleep -Seconds 15

# Quick health check
$redisOk = (docker exec darwin-redis redis-cli ping 2>$null) -eq "PONG"
if ($redisOk) { Print-OK "Redis ready" } else { Print-WARN "Redis not responding" }

$pgOk = (docker exec darwin-postgres pg_isready -U chaos 2>$null) -match "accepting"
if ($pgOk) { Print-OK "PostgreSQL ready" } else { Print-WARN "PostgreSQL not ready yet" }

# ─── 3. Seed Neo4j Knowledge Graph ───────────────────────────────────────────
if (!$SkipSeed) {
    Print-Header "Step 3: Seeding Neo4j Knowledge Graph"
    python seed_graph.py
    if ($LASTEXITCODE -eq 0) {
        Print-OK "Knowledge graph seeded (18 strands, 5 families, service deps)"
    } else {
        Print-WARN "Seed had errors — Neo4j may still be starting up"
        Write-Host "  Retry manually: python seed_graph.py"
    }
} else {
    Print-OK "Skipping seed (--SkipSeed)"
}

# ─── 4. minikube (optional) ───────────────────────────────────────────────────
if ($WithMinikube) {
    Print-Header "Step 4: Starting minikube"
    $mkStatus = minikube status 2>&1
    if ($mkStatus -match "Running") {
        Print-OK "minikube already running"
    } else {
        minikube start --memory=8192 --cpus=4 --driver=docker
        if ($LASTEXITCODE -eq 0) {
            Print-OK "minikube started"
        } else {
            Print-WARN "minikube start failed"
        }
    }

    # Apply namespaces and infra
    kubectl apply -f k8s/namespaces.yaml
    kubectl apply -f k8s/target/
    Print-OK "Patient microservices applied to minikube"

    # Port-forward patient services for Prometheus
    Print-Header "Step 5: Port-forwarding patient services → Prometheus"
    $ports = @{
        "auth-service"         = 8010
        "api-gateway"          = 8011
        "order-service"        = 8012
        "payment-service"      = 8013
        "inventory-service"    = 8014
        "notification-service" = 8015
    }
    foreach ($svc in $ports.Keys) {
        $port = $ports[$svc]
        Start-Process powershell -ArgumentList "-NoExit", "-Command", `
            "kubectl port-forward svc/$svc ${port}:80 -n patient 2>&1" -WindowStyle Minimized
        Write-Host "  port-forward: $svc → localhost:$port"
    }
    Start-Sleep -Seconds 5
    Print-OK "Port-forwards started"
}

# ─── 5. Start WS Bridge ───────────────────────────────────────────────────────
Print-Header "Step $(if($WithMinikube){'6'}else{'4'}): Starting WS Bridge (NATS → Terminal/Plots)"
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PWD'; pip install -q -r ws_bridge/requirements.txt; python -m uvicorn ws_bridge.main:app --port 8000 --reload 2>&1" `
    -WindowStyle Normal
Print-OK "WS Bridge starting on http://localhost:8000"

# ─── 6. Start ML Pipeline ─────────────────────────────────────────────────────
Print-Header "Step $(if($WithMinikube){'7'}else{'5'}): Starting ML Pipeline"
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PWD'; pip install -q -r ml_pipeline/requirements.txt; python -m ml_pipeline.pipeline 2>&1" `
    -WindowStyle Normal
Print-OK "ML Pipeline starting (polls Prometheus → NATS)"

# ─── 7. Start Live Dashboard ──────────────────────────────────────────────────
Print-Header "Step $(if($WithMinikube){'8'}else{'6'}): Starting Live Dashboard"
Start-Sleep -Seconds 3
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PWD'; pip install -q -r dashboard/requirements.txt; python -m dashboard.live_dashboard 2>&1" `
    -WindowStyle Normal
Print-OK "Live Dashboard starting (Rich terminal + Matplotlib)"

# ─── Done ─────────────────────────────────────────────────────────────────────
Print-Header "DARWIN Platform Ready"
Write-Host ""
Write-Host "  Services:"         -ForegroundColor Cyan
Write-Host "    Prometheus:   http://localhost:9090"
Write-Host "    Grafana:      http://localhost:3000  (admin/admin)"
Write-Host "    Jaeger:       http://localhost:16686"
Write-Host "    Neo4j:        http://localhost:7474  (neo4j/chaospassword)"
Write-Host "    NATS Monitor: http://localhost:8222"
Write-Host "    WS Bridge:    http://localhost:8000"
Write-Host ""
Write-Host "  Run demo scenarios:"  -ForegroundColor Yellow
Write-Host "    python demo.py 1        # Gen1 immunity"
Write-Host "    python demo.py 2        # Gen2 timing attack"
Write-Host "    python demo.py 3        # Gen3 honeypot discovery"
Write-Host "    python demo.py full     # Full 5-min demo"
Write-Host "    python demo.py fallback # Offline simulation"
Write-Host ""
Write-Host "  Stop all: docker compose down" -ForegroundColor Red
Write-Host ""
