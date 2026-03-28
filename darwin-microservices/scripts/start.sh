#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  DARWIN AUTONOMOUS CHAOS PLATFORM — ONE-COMMAND STARTUP (§11)
#  Usage: ./start.sh [live|demo|fallback]
# ═══════════════════════════════════════════════════════════════

set -e
MODE=${1:-"demo"}
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$PROJECT_DIR/agents"
DEMO="$PROJECT_DIR/demo"
SCRIPTS="$PROJECT_DIR/scripts"
PIDS=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════════════════════╗"
echo "  ║   ██████╗  █████╗ ██████╗ ██╗    ██╗██╗███╗   ██╗   ║"
echo "  ║   ██╔══██╗██╔══██╗██╔══██╗██║    ██║██║████╗  ██║   ║"
echo "  ║   ██║  ██║███████║██████╔╝██║ █╗ ██║██║██╔██╗ ██║   ║"
echo "  ║   ██║  ██║██╔══██║██╔══██╗██║███╗██║██║██║╚██╗██║   ║"
echo "  ║   ██████╔╝██║  ██║██║  ██║╚███╔███╔╝██║██║ ╚████║   ║"
echo "  ║   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚═╝╚═╝  ╚═══╝   ║"
echo "  ║   AUTONOMOUS CHAOS ENGINEERING & SELF-HEALING PLATFORM  ║"
echo "  ╚═══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "${YELLOW}  Mode: ${MODE}${NC}"
echo ""

cleanup() {
    echo -e "\n${RED}[SHUTDOWN] Terminating all agents...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    exit 0
}
trap cleanup INT TERM

# ─── Step 1: Check Infrastructure ──────────────────────────
echo -e "${CYAN}[1/6] Checking infrastructure...${NC}"

if [ "$MODE" == "fallback" ]; then
    echo -e "  ${YELLOW}→ Fallback mode — skipping infrastructure checks${NC}"
else
    # Check NATS
    if nc -z localhost 4222 2>/dev/null; then
        echo -e "  ${GREEN}✓ NATS${NC}"
    else
        echo -e "  ${RED}✗ NATS not running — starting docker-compose...${NC}"
        docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d nats 2>/dev/null || true
        sleep 3
    fi

    # Check Neo4j
    if nc -z localhost 7687 2>/dev/null; then
        echo -e "  ${GREEN}✓ Neo4j${NC}"
    else
        echo -e "  ${RED}✗ Neo4j not running — starting...${NC}"
        docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d neo4j 2>/dev/null || true
        sleep 5
    fi

    # Check Redis
    if nc -z localhost 6379 2>/dev/null; then
        echo -e "  ${GREEN}✓ Redis${NC}"
    else
        echo -e "  ${RED}✗ Redis not running — starting...${NC}"
        docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d redis 2>/dev/null || true
        sleep 2
    fi

    # Check Postgres
    if nc -z localhost 5432 2>/dev/null; then
        echo -e "  ${GREEN}✓ PostgreSQL${NC}"
    else
        echo -e "  ${RED}✗ PostgreSQL not running — starting...${NC}"
        docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d postgres 2>/dev/null || true
        sleep 3
    fi
fi

# ─── Step 2: Seed Knowledge Graph ──────────────────────────
if [ "$MODE" != "fallback" ]; then
    echo -e "${CYAN}[2/6] Seeding Neo4j brain...${NC}"
    PYTHONPATH="$AGENTS:$PYTHONPATH" python3 "$PROJECT_DIR/brain/seed_neo4j.py" 2>&1 | tail -5
fi

# ─── Step 3: Start WebSocket Bridge (Dashboard API) ────────
echo -e "${CYAN}[3/6] Starting WebSocket Bridge (port 8010)...${NC}"
PYTHONPATH="$AGENTS:$PYTHONPATH" python3 -m uvicorn agents.ws_bridge:app --host 0.0.0.0 --port 8010 \
    > /tmp/darwin_ws_bridge.log 2>&1 &
PIDS+=($!)
echo -e "  ${GREEN}✓ WS Bridge PID: $!${NC}"
sleep 2

# ─── Step 4: Start ML Pipeline ─────────────────────────────
if [ "$MODE" == "live" ]; then
    echo -e "${CYAN}[4/6] Starting ML Pipeline (IF + RF + CUSUM)...${NC}"
    PYTHONPATH="$AGENTS:$PYTHONPATH" python3 "$AGENTS/ml_pipeline.py" > /tmp/darwin_ml_pipeline.log 2>&1 &
    PIDS+=($!)
    echo -e "  ${GREEN}✓ ML Pipeline PID: $!${NC}"

    echo -e "${CYAN}[4.5/6] Starting LSTM Predictor...${NC}"
    PYTHONPATH="$AGENTS:$PYTHONPATH" python3 "$AGENTS/lstm_predictor.py" > /tmp/darwin_lstm.log 2>&1 &
    PIDS+=($!)
    echo -e "  ${GREEN}✓ LSTM PID: $!${NC}"
else
    echo -e "${YELLOW}[4/6] Skipping ML pipeline (not live mode)${NC}"
fi

# ─── Step 5: Start Antibody Engine ─────────────────────────
echo -e "${CYAN}[5/6] Starting Antibody Decision Engine...${NC}"
PYTHONPATH="$AGENTS:$PYTHONPATH" python3 "$AGENTS/antibody_agent.py" > /tmp/darwin_antibody.log 2>&1 &
PIDS+=($!)
echo -e "  ${GREEN}✓ Antibody PID: $!${NC}"
sleep 2

# ─── Step 6: Launch Attack / Demo ──────────────────────────
if [ "$MODE" == "live" ]; then
    echo -e "${CYAN}[6/6] Releasing VIRUS...${NC}"
    sleep 5
    PYTHONPATH="$AGENTS:$PYTHONPATH" python3 "$AGENTS/virus_agent.py" > /tmp/darwin_virus.log 2>&1 &
    PIDS+=($!)
    echo -e "  ${GREEN}✓ Virus PID: $!${NC}"
elif [ "$MODE" == "demo" ] || [ "$MODE" == "fallback" ]; then
    echo -e "${CYAN}[6/6] Starting Demo Fallback Simulator...${NC}"
    sleep 5
    PYTHONPATH="$AGENTS:$DEMO:$PYTHONPATH" python3 "$DEMO/demo.py" full > /tmp/darwin_demo.log 2>&1 &
    PIDS+=($!)
    echo -e "  ${GREEN}✓ Demo PID: $!${NC}"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ DARWIN IS LIVE!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "  ${CYAN}🌐 Dashboard:${NC}    http://localhost:5173"
echo -e "  ${CYAN}🧠 Brain API:${NC}    http://localhost:8010/api/state"
echo -e "  ${CYAN}🔌 WebSocket:${NC}    ws://localhost:8010/ws"
echo ""
echo -e "  ${YELLOW}Mode:${NC}    $MODE"
echo -e "  ${YELLOW}PIDs:${NC}    ${PIDS[*]}"
echo -e "  ${YELLOW}Logs:${NC}    /tmp/darwin_*.log"
echo ""
echo -e "  ${PURPLE}Press Ctrl+C to stop all agents${NC}"

wait
