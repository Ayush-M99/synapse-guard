#!/bin/bash
# =============================================================================
# DARWIN — One-Shot WSL Setup & Launcher
# =============================================================================
# Prereqs (Windows side, one-time):
#   winget install OpenJS.NodeJS.LTS   ← for the React dashboard
#
# Run this script from WSL:
#   cd ~/darwin && bash SETUP.sh [command]
#
# Commands:
#   setup     — full first-time install (infra + venv + deps + seed)
#   run       — start API server (port-forwards + uvicorn)
#   dashboard — start React dashboard (copy to /tmp + npm run dev)
#   locust    — start Locust web UI on :8089
#   all       — run + dashboard + locust in the background
#   status    — show running services
#   stop      — stop all DARWIN processes
# =============================================================================

set -e

PROJ_WIN="e:/#EditorCodes/Hackthon_solistic"       # Windows path
PROJ="/mnt/${PROJ_WIN/://}"                          # WSL mount path
PROJ="/mnt/e/#EditorCodes/Hackthon_solistic"
VENV=~/darwin/venv
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
NS_INFRA="darwin"
NS_PATIENT="patient"
GATEWAY_PORT=30080
API_PORT=9000
DASH_PORT=3000
LOCUST_PORT=8089

# ── Colours ────────────────────────────────────────────────────────────────────
G='\033[0;32m' Y='\033[1;33m' C='\033[0;36m' R='\033[0;31m' N='\033[0m' B='\033[1m'

log()  { echo -e "${C}[DARWIN]${N} $*"; }
ok()   { echo -e "${G}  ✓ $*${N}"; }
warn() { echo -e "${Y}  ⚠ $*${N}"; }
err()  { echo -e "${R}  ✗ $*${N}"; }
hr()   { echo -e "${C}$(printf '─%.0s' {1..60})${N}"; }

CMD="${1:-help}"

# =============================================================================
# SETUP — one-time environment bootstrap
# =============================================================================
cmd_setup() {
    hr
    echo -e "${B}  DARWIN Platform — First-Time Setup${N}"
    hr

    # ── Python venv ────────────────────────────────────────────────────────────
    log "Creating Python venv at ~/darwin/venv ..."
    mkdir -p ~/darwin
    if [ ! -d "$VENV" ]; then
        python3 -m venv "$VENV"
        ok "venv created"
    else
        ok "venv already exists"
    fi

    log "Installing Python dependencies ..."
    "$PIP" install -q \
        fastapi "uvicorn[standard]" \
        kubernetes redis httpx pyyaml pydantic \
        "nats-py" rich matplotlib networkx numpy \
        asyncpg "neo4j" requests locust \
        prometheus-client "google-generativeai" 2>&1 | tail -3
    ok "Python packages installed"

    # ── Kubernetes namespaces ──────────────────────────────────────────────────
    log "Creating Kubernetes namespaces ..."
    kubectl create namespace $NS_INFRA   2>/dev/null && ok "namespace: $NS_INFRA"   || ok "namespace: $NS_INFRA (exists)"
    kubectl create namespace $NS_PATIENT 2>/dev/null && ok "namespace: $NS_PATIENT" || ok "namespace: $NS_PATIENT (exists)"

    # ── Deploy infra (Redis, Prometheus) ──────────────────────────────────────
    log "Deploying infrastructure to Kubernetes ..."
    kubectl apply -f "$PROJ/k8s/darwin/darwin-deployments.yaml" -n $NS_INFRA 2>/dev/null || true
    ok "Infrastructure manifests applied"

    # ── Deploy patient app ────────────────────────────────────────────────────
    log "Deploying patient microservices ..."
    kubectl apply -f "$PROJ/k8s/target/patient-services.yaml" -n $NS_PATIENT 2>/dev/null || true
    ok "Patient services manifests applied"

    # ── Wait for infra pods ────────────────────────────────────────────────────
    log "Waiting for Redis and Prometheus ..."
    kubectl wait pod -l app=redis      -n $NS_INFRA --for=condition=Ready --timeout=120s 2>/dev/null && ok "Redis ready" || warn "Redis not ready yet"
    kubectl wait pod -l app=prometheus -n $NS_INFRA --for=condition=Ready --timeout=120s 2>/dev/null && ok "Prometheus ready" || warn "Prometheus not ready yet"

    # ── Port-forwards ──────────────────────────────────────────────────────────
    _start_portforwards

    # ── Seed Neo4j graph (optional) ────────────────────────────────────────────
    if "$PY" -c "from neo4j import GraphDatabase; GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','password')).verify_connectivity()" 2>/dev/null; then
        log "Seeding Neo4j knowledge graph ..."
        PYTHONPATH="$PROJ" "$PY" "$PROJ/seed_graph.py" 2>&1 | tail -3
        ok "Neo4j seeded"
    else
        warn "Neo4j unavailable — skipping seed (rule-based fallback will be used)"
    fi

    hr
    echo -e "${G}${B}  Setup complete! Run: bash SETUP.sh run${N}"
    hr
}

# =============================================================================
# RUN — start the DARWIN API server
# =============================================================================
cmd_run() {
    hr
    echo -e "${B}  Starting DARWIN Control Plane${N}"
    hr

    _start_portforwards

    log "Pre-flight checks ..."
    _check_prometheus && ok "Prometheus: up" || warn "Prometheus: down"
    _check_redis      && ok "Redis: up"      || warn "Redis: down"
    _check_k8s        && ok "Kubernetes: connected" || warn "Kubernetes: unreachable"

    log "Starting DARWIN API on http://0.0.0.0:$API_PORT ..."
    echo -e "${C}  Swagger UI: http://localhost:$API_PORT/docs${N}"
    echo ""
    export PYTHONPATH="$PROJ"
    export PROMETHEUS_URL="http://localhost:9090"
    export REDIS_URL="redis://localhost:6379"
    export DARWIN_NAMESPACE="$NS_INFRA"
    export PATIENT_NAMESPACE="$NS_PATIENT"

    exec "$VENV/bin/uvicorn" darwin_api.main:app \
        --host 0.0.0.0 --port $API_PORT \
        --reload --reload-dir "$PROJ/darwin_api" \
        --log-level info
}

# =============================================================================
# DASHBOARD — build + start React dashboard
# =============================================================================
cmd_dashboard() {
    hr
    echo -e "${B}  Starting React Dashboard${N}"
    hr

    # Copy to /tmp to avoid '#' in path (Vite limitation)
    DASH_TMP="/tmp/darwin-dashboard"
    log "Copying dashboard to $DASH_TMP ..."
    rm -rf "$DASH_TMP"
    cp -r "$PROJ/darwin-dashboard" "$DASH_TMP"
    ok "Dashboard copied"

    cd "$DASH_TMP"

    if ! command -v npm &>/dev/null; then
        err "npm not found in WSL. Install Node.js:"
        echo "  Option A (Windows): winget install OpenJS.NodeJS.LTS"
        echo "  Option B (WSL):     sudo apt-get install -y nodejs npm"
        exit 1
    fi

    log "Installing npm packages ..."
    npm install --silent 2>&1 | tail -3
    ok "npm packages installed"

    echo ""
    echo -e "${G}  Dashboard: http://localhost:$DASH_PORT${N}"
    echo -e "${C}  API Docs:  http://localhost:$API_PORT/docs${N}"
    echo ""
    exec npm run dev -- --port $DASH_PORT
}

# =============================================================================
# LOCUST — start load generator web UI
# =============================================================================
cmd_locust() {
    hr
    echo -e "${B}  Starting Locust Load Generator${N}"
    hr
    log "Checking gateway ..."
    curl -sf "http://localhost:$GATEWAY_PORT/health" >/dev/null && ok "api-gateway up" || warn "api-gateway not reachable — ensure patient app is deployed"
    echo ""
    echo -e "${C}  Locust UI: http://localhost:$LOCUST_PORT${N}"
    echo -e "${Y}  Default host: http://localhost:$GATEWAY_PORT${N}"
    echo ""
    exec "$VENV/bin/locust" \
        -f "$PROJ/locust/locustfile.py" \
        --host "http://localhost:$GATEWAY_PORT" \
        --web-port $LOCUST_PORT
}

# =============================================================================
# ALL — start everything in background tabs
# =============================================================================
cmd_all() {
    hr
    echo -e "${B}  DARWIN — Starting All Services${N}"
    hr

    _start_portforwards

    log "Starting DARWIN API (background) ..."
    PYTHONPATH="$PROJ" PROMETHEUS_URL="http://localhost:9090" REDIS_URL="redis://localhost:6379" \
        DARWIN_NAMESPACE="$NS_INFRA" PATIENT_NAMESPACE="$NS_PATIENT" \
        "$VENV/bin/uvicorn" darwin_api.main:app \
        --host 0.0.0.0 --port $API_PORT --log-level warning \
        > /tmp/darwin-api.log 2>&1 &
    echo $! > /tmp/darwin-api.pid
    ok "API started (PID $(cat /tmp/darwin-api.pid))"
    sleep 2

    log "Starting Locust (background) ..."
    "$VENV/bin/locust" -f "$PROJ/locust/locustfile.py" \
        --host "http://localhost:$GATEWAY_PORT" \
        --web-port $LOCUST_PORT --headless \
        --users 0 > /tmp/darwin-locust.log 2>&1 &
    echo $! > /tmp/darwin-locust.pid
    ok "Locust started (PID $(cat /tmp/darwin-locust.pid))"

    hr
    echo -e "${G}${B}  All services started!${N}"
    echo ""
    echo -e "  ${B}API:${N}       http://localhost:$API_PORT/docs"
    echo -e "  ${B}Locust:${N}    http://localhost:$LOCUST_PORT"
    echo ""
    echo -e "  ${Y}Start dashboard separately (needs Windows Node or WSL npm):${N}"
    echo -e "  bash SETUP.sh dashboard"
    hr
}

# =============================================================================
# STATUS
# =============================================================================
cmd_status() {
    hr
    echo -e "${B}  DARWIN Status${N}"
    hr
    echo -e "${Y}Kubernetes pods:${N}"
    kubectl get pods -n $NS_INFRA   2>/dev/null | grep -v "^$" || echo "  (kubectl unavailable)"
    kubectl get pods -n $NS_PATIENT 2>/dev/null | grep -v "^$" || true
    echo ""
    echo -e "${Y}Services:${N}"
    _check_prometheus && echo -e "  ${G}✓ Prometheus${N} http://localhost:9090" || echo -e "  ${R}✗ Prometheus${N}"
    _check_redis      && echo -e "  ${G}✓ Redis${N}      localhost:6379"        || echo -e "  ${R}✗ Redis${N}"
    curl -sf "http://localhost:$API_PORT/health" >/dev/null && echo -e "  ${G}✓ DARWIN API${N} http://localhost:$API_PORT" || echo -e "  ${R}✗ DARWIN API${N}"
    curl -sf "http://localhost:$DASH_PORT"       >/dev/null && echo -e "  ${G}✓ Dashboard${N}  http://localhost:$DASH_PORT" || echo -e "  ${Y}⚠ Dashboard${N} (not started)"
    echo ""
    echo -e "${Y}Port-forwards:${N}"
    pgrep -a -f "kubectl port-forward" | grep -v grep || echo "  (none)"
    hr
}

# =============================================================================
# STOP
# =============================================================================
cmd_stop() {
    log "Stopping all DARWIN processes ..."
    pkill -f "kubectl port-forward" 2>/dev/null && ok "Port-forwards stopped" || true
    pkill -f "uvicorn darwin_api"   2>/dev/null && ok "DARWIN API stopped"    || true
    pkill -f "locust"               2>/dev/null && ok "Locust stopped"         || true
    pkill -f "vite"                 2>/dev/null && ok "Dashboard stopped"      || true
    rm -f /tmp/darwin-*.pid /tmp/darwin-*.log
    ok "Done"
}

# =============================================================================
# HELP
# =============================================================================
cmd_help() {
    hr
    echo -e "${B}  DARWIN Autonomous Chaos Platform — SETUP.sh${N}"
    hr
    echo ""
    echo -e "  ${C}bash SETUP.sh setup${N}     ← first-time setup (venv + K8s + deps)"
    echo -e "  ${C}bash SETUP.sh run${N}       ← start DARWIN API (foreground)"
    echo -e "  ${C}bash SETUP.sh dashboard${N} ← start React dashboard  → :$DASH_PORT"
    echo -e "  ${C}bash SETUP.sh locust${N}    ← start Locust UI         → :$LOCUST_PORT"
    echo -e "  ${C}bash SETUP.sh all${N}       ← start everything (background)"
    echo -e "  ${C}bash SETUP.sh status${N}    ← show service health"
    echo -e "  ${C}bash SETUP.sh stop${N}      ← kill all DARWIN processes"
    echo ""
    echo -e "  ${Y}Prerequisites:${N}"
    echo -e "    - minikube running in WSL with kubectl configured"
    echo -e "    - Redis + Prometheus pods in '$NS_INFRA' namespace"
    echo -e "    - Node.js for dashboard (winget install OpenJS.NodeJS.LTS)"
    hr
}

# =============================================================================
# Internal helpers
# =============================================================================
_start_portforwards() {
    pkill -f "kubectl port-forward" 2>/dev/null || true
    sleep 1
    kubectl port-forward svc/redis      6379:6379 -n $NS_INFRA >/tmp/pf-redis.log 2>&1 &
    kubectl port-forward svc/prometheus 9090:9090 -n $NS_INFRA >/tmp/pf-prom.log  2>&1 &
    sleep 3
    _check_prometheus && ok "Port-forward: Prometheus :9090" || warn "Port-forward: Prometheus not ready"
    ok "Port-forward: Redis :6379 (started)"
}

_check_prometheus() { curl -sf http://localhost:9090/-/healthy >/dev/null 2>&1; }
_check_redis()      { "$PY" -c "import redis; redis.from_url('redis://localhost:6379').ping()" 2>/dev/null; }
_check_k8s()        { kubectl cluster-info 2>/dev/null | grep -q "running"; }

# =============================================================================
# Dispatch
# =============================================================================
cd "$PROJ" 2>/dev/null || true

case "$CMD" in
    setup)     cmd_setup ;;
    run)       cmd_run ;;
    dashboard) cmd_dashboard ;;
    locust)    cmd_locust ;;
    all)       cmd_all ;;
    status)    cmd_status ;;
    stop)      cmd_stop ;;
    *)         cmd_help ;;
esac
