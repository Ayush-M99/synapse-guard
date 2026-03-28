"""
DARWIN WebSocket Bridge — NATS to Dashboard (§12)

Bridges NATS events to WebSocket clients for real-time dashboard updates.
Subscribes to brain.update, services.health, virus.inject, virus.generation.event.
Forwards all events to connected WebSocket clients.

Also serves as the Dashboard API backend:
    GET  /api/state     → current system state
    GET  /api/dna       → DNA evolution log
    GET  /api/predict   → LSTM prediction
    POST /api/inject    → manual chaos injection
    GET  /api/dna/replay/{gen} → replay generation events
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import nats

from constants import (
    NATSSubjects, BrainEvents, ServiceConfig, DBConfig
)

logging.basicConfig(level=logging.INFO, format="[WS-BRIDGE] %(message)s")
log = logging.getLogger("ws_bridge")

NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)

app = FastAPI(title="DARWIN WebSocket Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════════

class DashboardState:
    def __init__(self):
        self.nc: Optional[nats.NATS] = None
        self.connected_clients: list[WebSocket] = []

        # System metrics
        self.virus_gen = 1
        self.antibody_gen = 1
        self.resilience_score = 0
        self.total_healed = 0
        self.human_interventions = 0
        self.avg_recovery_ms = 0.0
        self.unknown_strand_rate = 0.0
        self.false_positive_rate = 0.0

        # Service health states
        self.service_states: dict[str, str] = {
            svc: "healthy" for svc in ServiceConfig.SERVICE_NAMES
        }

        # Event log for battle feed
        self.battle_feed: list[dict] = []

        # DNA log
        self.dna_log: list[dict] = []

        # Generation data for timeline
        self.generation_data: list[dict] = [
            {"gen": 0, "recovery_ms": 0, "unknown_rate": 0, "resilience_score": 0},
        ]

        # Recovery time tracking
        self.recovery_times: list[float] = []


state = DashboardState()


# ═══════════════════════════════════════════════════════════════
# RESILIENCE SCORE CALCULATOR (§12)
# ═══════════════════════════════════════════════════════════════

def calculate_resilience_score() -> int:
    """0-1000 score. Recalculated continuously."""
    if not state.recovery_times:
        return 0

    avg_recovery = sum(state.recovery_times[-10:]) / len(state.recovery_times[-10:])
    recovery_score = max(0, min(400, (1 - avg_recovery / 20000) * 400))
    unknown_score = (1 - state.unknown_strand_rate) * 200
    fp_score = (1 - state.false_positive_rate) * 200
    blast_score = 200  # Simplified
    return int(recovery_score + unknown_score + fp_score + blast_score)


# ═══════════════════════════════════════════════════════════════
# NATS EVENT HANDLERS
# ═══════════════════════════════════════════════════════════════

def format_battle_event(data: dict) -> dict:
    """Format event for battle feed with emoji icons."""
    event_type = data.get("event", "unknown")
    service = data.get("service", "")

    ICONS = {
        BrainEvents.ATTACK_DETECTED: "🦠",
        BrainEvents.RECOVERY_STARTED: "💉",
        BrainEvents.RECOVERY_COMPLETE: "✅",
        BrainEvents.RECOVERY_PREEMPTED: "⚡",
        BrainEvents.PREEMPTIVE_ACTION: "🔮",
        BrainEvents.NEW_STRAND_DISCOVERED: "🟣",
        BrainEvents.HONEYPOT_DEPLOYED: "🍯",
        BrainEvents.HONEYPOT_OBSERVING: "👁️",
        BrainEvents.MUTATION: "🧬",
        BrainEvents.TCELL_HIT: "⚡",
    }

    MESSAGES = {
        BrainEvents.ATTACK_DETECTED: f"Virus injected {data.get('attack_family', data.get('strand_id', '?'))} → {service}",
        BrainEvents.RECOVERY_STARTED: f"Recovery started: {data.get('playbook', '?')} on {service}",
        BrainEvents.RECOVERY_COMPLETE: f"Recovery complete: {service} in {data.get('recovery_time_ms', 0):.0f}ms",
        BrainEvents.RECOVERY_PREEMPTED: f"Recovery preempted on {service}",
        BrainEvents.PREEMPTIVE_ACTION: f"LSTM predicted: {data.get('family', '?')} → pre-scaling {service}",
        BrainEvents.NEW_STRAND_DISCOVERED: f"New strand discovered: {data.get('strand_id', '?')} → {data.get('family', '?')}",
        BrainEvents.HONEYPOT_DEPLOYED: f"Honeypot deployed for {service}",
        BrainEvents.HONEYPOT_OBSERVING: f"Observing honeypot for {service} (10s window)",
        BrainEvents.MUTATION: f"Virus mutating to Gen {data.get('virus_gen', '?')}",
        BrainEvents.TCELL_HIT: f"T-cell hit: {data.get('strand_id', '?')} → reflex recovery",
    }

    return {
        "icon": ICONS.get(event_type, "ℹ️"),
        "message": MESSAGES.get(event_type, f"{event_type}: {service}"),
        "event": event_type,
        "service": service,
        "timestamp": time.strftime("%H:%M:%S"),
        "data": data,
    }


async def handle_brain_update(msg):
    """Process brain.update events."""
    data = json.loads(msg.data.decode())
    event = data.get("event", "")

    # Update service states
    service = data.get("service", "")
    if event == BrainEvents.ATTACK_DETECTED:
        state.service_states[service] = "attacked"
    elif event == BrainEvents.RECOVERY_STARTED:
        state.service_states[service] = "healing"
    elif event == BrainEvents.RECOVERY_COMPLETE:
        state.service_states[service] = "healthy"
        recovery_ms = data.get("recovery_time_ms", 0)
        state.recovery_times.append(recovery_ms)
        state.total_healed += 1
        state.resilience_score = calculate_resilience_score()
        state.avg_recovery_ms = sum(state.recovery_times) / len(state.recovery_times)

        # Track DNA
        state.dna_log.append({
            "id": len(state.dna_log) + 1,
            "strand": data.get("strand_id", "?"),
            "family": data.get("attack_family", "?"),
            "service": service,
            "recovery_ms": recovery_ms,
            "success": data.get("success", True),
            "attack_state": data.get("attack_state", "KNOWN"),
            "gen": state.virus_gen,
            "timestamp": time.strftime("%H:%M:%S"),
        })
        if len(state.dna_log) > 100:
            state.dna_log = state.dna_log[-100:]

    elif event == BrainEvents.PREEMPTIVE_ACTION:
        state.service_states[service] = "preemptive"
    elif event == BrainEvents.NEW_STRAND_DISCOVERED:
        state.service_states[service] = "discovered"

    # Format and store battle feed event
    battle_event = format_battle_event(data)
    state.battle_feed.append(battle_event)
    if len(state.battle_feed) > 50:
        state.battle_feed = state.battle_feed[-50:]

    # Forward to all WebSocket clients
    await broadcast(battle_event)


async def handle_virus_event(msg):
    """Process virus.inject and virus.generation.event."""
    data = json.loads(msg.data.decode())

    if "virus_gen" in data:
        state.virus_gen = data["virus_gen"]

    battle_event = {
        "icon": "🦠",
        "message": f"Virus Gen {data.get('virus_gen', '?')}: injecting {data.get('strand', data.get('strands', '?'))}",
        "event": "virus_inject",
        "timestamp": time.strftime("%H:%M:%S"),
        "data": data,
    }
    state.battle_feed.append(battle_event)
    await broadcast(battle_event)


async def handle_services_health(msg):
    """Process services.health updates."""
    data = json.loads(msg.data.decode())
    for svc, status in data.items():
        if svc in state.service_states:
            state.service_states[svc] = status
    await broadcast({"event": "health_update", "services": state.service_states})


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET MANAGEMENT
# ═══════════════════════════════════════════════════════════════

async def broadcast(data: dict):
    """Broadcast event to all connected WebSocket clients."""
    message = json.dumps(data)
    disconnected = []
    for client in state.connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        state.connected_clients.remove(client)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for dashboard real-time updates."""
    await websocket.accept()
    state.connected_clients.append(websocket)
    log.info(f"Client connected ({len(state.connected_clients)} total)")

    # Send initial state
    await websocket.send_json({
        "event": "initial_state",
        "services": state.service_states,
        "battle_feed": state.battle_feed[-20:],
        "resilience_score": state.resilience_score,
        "virus_gen": state.virus_gen,
        "antibody_gen": state.antibody_gen,
        "total_healed": state.total_healed,
        "human_interventions": state.human_interventions,
        "generation_data": state.generation_data,
    })

    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Handle any client commands if needed
    except WebSocketDisconnect:
        state.connected_clients.remove(websocket)
        log.info(f"Client disconnected ({len(state.connected_clients)} total)")


# ═══════════════════════════════════════════════════════════════
# REST API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/api/state")
async def get_state():
    """Current system state for dashboard."""
    return {
        "resilience_score": state.resilience_score,
        "virus_gen": state.virus_gen,
        "antibody_gen": state.antibody_gen,
        "total_healed": state.total_healed,
        "human_interventions": state.human_interventions,
        "avg_recovery_ms": round(state.avg_recovery_ms, 1),
        "services": state.service_states,
        "battle_feed": state.battle_feed[-20:],
        "generation_data": state.generation_data,
    }


@app.get("/api/dna")
async def get_dna():
    """DNA evolution log."""
    return {"logs": state.dna_log[-30:]}


@app.get("/api/dna/replay/{gen}")
async def replay_generation(gen: int):
    """Get events for a specific generation for replay."""
    events = [d for d in state.dna_log if d.get("gen") == gen]
    return {"generation": gen, "events": events}


@app.post("/api/inject/{service}")
async def inject_chaos(service: str, family: str = "pod_crash"):
    """Manual chaos injection from dashboard."""
    if state.nc:
        payload = json.dumps({
            "service": service,
            "attack_family": family,
            "rf_confidence": 0.90,
            "attack_state": "KNOWN",
            "source": "MANUAL",
            "timestamp": time.time(),
        }).encode()
        subject = NATSSubjects.NERVE_ALERT.format(service=service)
        await state.nc.publish(subject, payload)
        return {"status": "injected", "service": service, "family": family}
    return {"status": "error", "message": "NATS not connected"}


@app.get("/api/predict")
async def predict_next():
    """LSTM prediction endpoint."""
    try:
        from lstm_predictor import predictor
        prediction = predictor.predict_next_attack()
        return prediction
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# STARTUP — NATS SUBSCRIPTION
# ═══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    try:
        state.nc = await nats.connect(NATS_URL)
        await state.nc.subscribe(NATSSubjects.BRAIN_UPDATE, cb=handle_brain_update)
        await state.nc.subscribe(NATSSubjects.SERVICES_HEALTH, cb=handle_services_health)
        await state.nc.subscribe(NATSSubjects.VIRUS_INJECT, cb=handle_virus_event)
        await state.nc.subscribe(NATSSubjects.VIRUS_GENERATION_EVENT, cb=handle_virus_event)
        log.info(f"Connected to NATS at {NATS_URL}")
        log.info("Subscribed to: brain.update, services.health, virus.inject, virus.generation.event")
    except Exception as e:
        log.warning(f"NATS connection failed: {e} — running in standalone mode")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
