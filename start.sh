#!/usr/bin/env bash
# DARWIN Platform — Linux/WSL2 One-Command Startup
# Usage:
#   ./start.sh              → infra + bridge + ml + dashboard only
#   ./start.sh --minikube   → also start minikube + patient services

set -e
MINIKUBE=false
SKIP_SEED=false

for arg in "$@"; do
    case $arg in
        --minikube)   MINIKUBE=true ;;
        --skip-seed)  SKIP_SEED=true ;;
    esac
done

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
header() { echo -e "\n${CYAN}══════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}══════════════════════════════════════════${NC}"; }
ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[!!]${NC} $1"; }
err()  { echo -e "  ${RED}[XX]${NC} $1"; }

header "DARWIN Platform — Startup ($(date +%H:%M:%S))"

# ─── 1. Docker Compose ────────────────────────────────────────────────────────
header "Step 1: Starting External Services"
docker compose -f docker-compose.yml up -d
ok "Redis, PostgreSQL, Neo4j, NATS, Prometheus, Loki, Grafana, Jaeger"

# ─── 2. Wait ──────────────────────────────────────────────────────────────────
header "Step 2: Waiting for databases (15s)"
sleep 15
docker exec darwin-redis redis-cli ping &>/dev/null && ok "Redis ready" || warn "Redis not ready"
docker exec darwin-postgres pg_isready -U chaos &>/dev/null && ok "PostgreSQL ready" || warn "PostgreSQL warming up"

# ─── 3. Seed ──────────────────────────────────────────────────────────────────
if [ "$SKIP_SEED" = false ]; then
    header "Step 3: Seeding Knowledge Graph"
    python seed_graph.py && ok "Knowledge graph seeded" || warn "Seed errors — retry: python seed_graph.py"
else
    ok "Skip seed (--skip-seed)"
fi

# ─── 4. minikube (optional) ───────────────────────────────────────────────────
if [ "$MINIKUBE" = true ]; then
    header "Step 4: minikube"
    minikube status | grep -q "Running" && ok "minikube already running" || {
        minikube start --memory=8192 --cpus=4 --driver=docker
        ok "minikube started"
    }
    kubectl apply -f k8s/namespaces.yaml
    kubectl apply -f k8s/target/
    ok "Patient app applied"

    header "Step 5: Port-forwarding patient services"
    declare -A PORTS=([auth-service]=8010 [api-gateway]=8011 [order-service]=8012 [payment-service]=8013 [inventory-service]=8014 [notification-service]=8015)
    for svc in "${!PORTS[@]}"; do
        port="${PORTS[$svc]}"
        kubectl port-forward svc/$svc ${port}:80 -n patient &>/dev/null &
        echo "  port-forward: $svc → :$port [PID $!]"
    done
    sleep 3
    ok "Port-forwards running"
fi

# ─── 5. WS Bridge ─────────────────────────────────────────────────────────────
header "Step $([ "$MINIKUBE" = true ] && echo 6 || echo 4): WS Bridge"
pip install -q -r ws_bridge/requirements.txt
uvicorn ws_bridge.main:app --port 8000 --host 0.0.0.0 --reload &
WS_PID=$!
ok "WS Bridge started on :8000 [PID $WS_PID]"

# ─── 6. ML Pipeline ───────────────────────────────────────────────────────────
header "Step $([ "$MINIKUBE" = true ] && echo 7 || echo 5): ML Pipeline"
pip install -q -r ml_pipeline/requirements.txt
python -m ml_pipeline.pipeline &
ML_PID=$!
ok "ML Pipeline started [PID $ML_PID]"

sleep 3

# ─── 7. Live Dashboard ────────────────────────────────────────────────────────
header "Step $([ "$MINIKUBE" = true ] && echo 8 || echo 6): Live Dashboard"
pip install -q -r dashboard/requirements.txt
python -m dashboard.live_dashboard &
DASH_PID=$!
ok "Dashboard started [PID $DASH_PID]"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
header "DARWIN Platform Ready"
echo -e "  ${CYAN}Services:${NC}"
echo "    Prometheus:   http://localhost:9090"
echo "    Grafana:      http://localhost:3000  (admin/admin)"
echo "    Jaeger:       http://localhost:16686"
echo "    Neo4j:        http://localhost:7474  (neo4j/chaospassword)"
echo "    NATS Monitor: http://localhost:8222"
echo "    WS Bridge:    http://localhost:8000"
echo ""
echo -e "  ${YELLOW}Run demo:${NC}"
echo "    python demo.py 1        # Gen1 immunity"
echo "    python demo.py 2        # Gen2 timing + LSTM"
echo "    python demo.py 3        # Gen3 honeypot"
echo "    python demo.py full     # 5-min full demo"
echo "    python demo.py fallback # Offline simulation"
echo ""
echo -e "  ${RED}Stop:${NC} docker compose down && kill $WS_PID $ML_PID $DASH_PID"
echo ""

# Keep alive (wait for dashboard to run in foreground)
wait $DASH_PID
