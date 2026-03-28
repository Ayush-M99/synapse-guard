"""
DARWIN LSTM Attack Predictor — Layer 3 (§5)

Temporal prediction: predicts next attack family from sequence history.
This is what enables the antibody to pre-scale BEFORE the strike lands — the Gen 3 demo moment.

Architecture: ~2 layer LSTM, lightweight PyTorch.
Pre-trained on synthetic sequences generated from known attack order patterns.

Input:  sequence of (attack_family_id, recovery_time_normalized, success_bool)
Output: predicted next attack family + estimated confidence
"""

import os
import json
import time
import asyncio
import logging
from collections import deque
from typing import Optional

import numpy as np

try:
    import torch
    import torch.nn as nn
    PYTORCH_AVAILABLE = True
except ImportError:
    PYTORCH_AVAILABLE = False

import nats

from constants import (
    NATSSubjects, BrainEvents, MLConfig, AttackState,
    ServiceConfig, DBConfig,
)

logging.basicConfig(level=logging.INFO, format="[LSTM] %(message)s")
log = logging.getLogger("lstm_predictor")

NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)
MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(os.path.dirname(__file__), "..", "models"))


# ═══════════════════════════════════════════════════════════════
# ATTACK ENCODING
# ═══════════════════════════════════════════════════════════════

ATTACK_FAMILIES = {
    "pod_crash": 0, "network": 1, "resource": 2,
    "timing": 3, "cost": 4,
}
FAMILY_NAMES = {v: k for k, v in ATTACK_FAMILIES.items()}
NUM_FAMILIES = len(ATTACK_FAMILIES)

SERVICE_ENCODING = {
    "auth-service": 0, "api-gateway": 1, "order-service": 2,
    "payment-service": 3, "inventory-service": 4, "notification-service": 5,
}
SERVICE_NAMES = {v: k for k, v in SERVICE_ENCODING.items()}
NUM_SERVICES = len(SERVICE_ENCODING)

# Input features per timestep: family_onehot(5) + recovery_time_norm(1) + success(1) + service_onehot(6) = 13
INPUT_SIZE = NUM_FAMILIES + 1 + 1 + NUM_SERVICES
HIDDEN_SIZE = 64
NUM_LAYERS = 2


# ═══════════════════════════════════════════════════════════════
# LSTM MODEL DEFINITION
# ═══════════════════════════════════════════════════════════════

if PYTORCH_AVAILABLE:
    class AttackLSTM(nn.Module):
        """Lightweight 2-layer LSTM for attack sequence prediction."""

        def __init__(self, input_size=INPUT_SIZE, hidden_size=HIDDEN_SIZE,
                     num_layers=NUM_LAYERS, num_families=NUM_FAMILIES,
                     num_services=NUM_SERVICES):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers

            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=0.2,
            )

            # Dual head: predict family + service
            self.family_head = nn.Sequential(
                nn.Linear(hidden_size, 32),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(32, num_families),
            )
            self.service_head = nn.Sequential(
                nn.Linear(hidden_size, 32),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(32, num_services),
            )

        def forward(self, x):
            # x: (batch, seq_len, input_size)
            lstm_out, _ = self.lstm(x)
            last_hidden = lstm_out[:, -1, :]  # Take last timestep

            family_logits = self.family_head(last_hidden)
            service_logits = self.service_head(last_hidden)

            return family_logits, service_logits


# ═══════════════════════════════════════════════════════════════
# LSTM PREDICTOR (RUNTIME INFERENCE)
# ═══════════════════════════════════════════════════════════════

class LSTMPredictor:
    """
    Runtime inference engine for attack prediction.
    Falls back to transition-matrix heuristic if PyTorch unavailable.
    """

    def __init__(self):
        self.attack_history: deque = deque(maxlen=100)
        self.model: Optional[object] = None
        self.nc: Optional[nats.NATS] = None

        # Load PyTorch model if available
        model_path = os.path.join(MODEL_DIR, "lstm_predictor.pt")
        if PYTORCH_AVAILABLE and os.path.exists(model_path):
            try:
                self.model = AttackLSTM()
                state = torch.load(model_path, map_location="cpu", weights_only=False)
                if isinstance(state, dict) and "model_state_dict" in state:
                    self.model.load_state_dict(state["model_state_dict"])
                else:
                    self.model.load_state_dict(state)
                self.model.eval()
                log.info(f"LSTM model loaded from {model_path}")
            except Exception as e:
                log.warning(f"Could not load LSTM model: {e}. Using fallback.")
                self.model = None
        else:
            log.warning("PyTorch/model not available — using transition matrix fallback")

        # Transition probability matrix (fallback when no LSTM model)
        self.transition_matrix = np.array([
            # pc    net   res   tim   cost
            [0.10, 0.30, 0.25, 0.20, 0.15],  # pod_crash →
            [0.20, 0.10, 0.20, 0.30, 0.20],  # network →
            [0.15, 0.20, 0.10, 0.30, 0.25],  # resource →
            [0.10, 0.15, 0.25, 0.10, 0.40],  # timing →
            [0.15, 0.20, 0.30, 0.25, 0.10],  # cost →
        ])

        # Service targeting weights (updated from observations)
        self.service_weights = np.array([0.15, 0.15, 0.20, 0.25, 0.15, 0.10])

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        log.info(f"Connected to NATS at {NATS_URL}")

    def record_attack(self, attack_family: str, target_service: str,
                      recovery_time_ms: float, success: bool):
        """Record an observed attack event into the sequence history."""
        self.attack_history.append({
            "family": attack_family,
            "family_id": ATTACK_FAMILIES.get(attack_family, 0),
            "service": target_service,
            "service_id": SERVICE_ENCODING.get(target_service, 0),
            "recovery_time_ms": recovery_time_ms,
            "success": success,
            "timestamp": time.time(),
        })

        # Update service targeting weights
        sid = SERVICE_ENCODING.get(target_service, 0)
        self.service_weights[sid] += 0.05
        self.service_weights /= self.service_weights.sum()

    def _encode_history_to_tensor(self) -> Optional[object]:
        """Encode attack history into LSTM input tensor."""
        if not PYTORCH_AVAILABLE or len(self.attack_history) < 3:
            return None

        seq_len = min(len(self.attack_history), MLConfig.LSTM_SEQUENCE_LENGTH)
        recent = list(self.attack_history)[-seq_len:]

        sequence = []
        for event in recent:
            # One-hot encode family
            family_onehot = [0.0] * NUM_FAMILIES
            family_onehot[event["family_id"]] = 1.0

            # Normalize recovery time (0-1, max 30000ms)
            recovery_norm = min(event["recovery_time_ms"] / 30000.0, 1.0)

            # Success boolean
            success = 1.0 if event["success"] else 0.0

            # One-hot encode service
            service_onehot = [0.0] * NUM_SERVICES
            service_onehot[event["service_id"]] = 1.0

            timestep = family_onehot + [recovery_norm, success] + service_onehot
            sequence.append(timestep)

        tensor = torch.FloatTensor([sequence])  # (1, seq_len, input_size)
        return tensor

    def predict_next_attack(self) -> dict:
        """Predict the next most likely attack family and target service."""

        # Try PyTorch LSTM first
        if self.model is not None and PYTORCH_AVAILABLE:
            tensor = self._encode_history_to_tensor()
            if tensor is not None:
                return self._predict_with_lstm(tensor)

        # Fallback: transition matrix
        return self._predict_with_transition_matrix()

    def _predict_with_lstm(self, tensor) -> dict:
        """Predict using the trained LSTM model."""
        with torch.no_grad():
            family_logits, service_logits = self.model(tensor)

            family_probs = torch.softmax(family_logits, dim=-1)[0]
            service_probs = torch.softmax(service_logits, dim=-1)[0]

            predicted_family_id = int(torch.argmax(family_probs).item())
            predicted_service_id = int(torch.argmax(service_probs).item())

            family_confidence = float(family_probs[predicted_family_id].item())
            service_confidence = float(service_probs[predicted_service_id].item())

        predicted_family = FAMILY_NAMES.get(predicted_family_id, "pod_crash")
        predicted_service = SERVICE_NAMES.get(predicted_service_id, "payment-service")

        return {
            "predicted_family": predicted_family,
            "predicted_service": predicted_service,
            "lstm_confidence": round(family_confidence, 3),
            "service_confidence": round(service_confidence, 3),
            "source": "LSTM",
            "history_length": len(self.attack_history),
            "reasoning": (
                f"LSTM prediction from {len(self.attack_history)} attack sequence. "
                f"Next likely: {predicted_family} → {predicted_service} "
                f"(conf={family_confidence:.2%})"
            ),
        }

    def _predict_with_transition_matrix(self) -> dict:
        """Fallback prediction using Markov transition matrix."""
        if len(self.attack_history) == 0:
            return {
                "predicted_family": "pod_crash",
                "predicted_service": "payment-service",
                "lstm_confidence": 0.50,
                "source": "DEFAULT",
                "history_length": 0,
                "reasoning": "No attack history — defaulting to Gen 1 most common vector.",
            }

        last = self.attack_history[-1]
        last_fid = last["family_id"]

        probs = self.transition_matrix[last_fid].copy()

        # Reduce probability of recent repeats
        if len(self.attack_history) >= 3:
            recent_fids = [a["family_id"] for a in list(self.attack_history)[-3:]]
            for fid in recent_fids:
                probs[fid] *= 0.6
            unseen = set(range(NUM_FAMILIES)) - set(recent_fids)
            for fid in unseen:
                probs[fid] *= 1.4
        probs /= probs.sum()

        predicted_fid = int(np.argmax(probs))
        predicted_family = FAMILY_NAMES.get(predicted_fid, "pod_crash")
        confidence = float(probs[predicted_fid])

        predicted_sid = int(np.argmax(self.service_weights))
        predicted_service = SERVICE_NAMES.get(predicted_sid, "payment-service")

        return {
            "predicted_family": predicted_family,
            "predicted_service": predicted_service,
            "lstm_confidence": round(confidence, 3),
            "source": "TRANSITION_MATRIX",
            "history_length": len(self.attack_history),
            "reasoning": (
                f"Transition matrix prediction from {len(self.attack_history)} events. "
                f"Last: {last['family']} → {last['service']}. "
                f"Predicted: {predicted_family} → {predicted_service}."
            ),
        }

    async def publish_prediction(self, prediction: dict):
        """Publish LSTM prediction to NATS for Decision Engine."""
        if self.nc and prediction["lstm_confidence"] >= MLConfig.LSTM_CONFIDENCE_THRESHOLD:
            await self.nc.publish(
                NATSSubjects.LSTM_PREDICTION,
                json.dumps(prediction).encode()
            )
            log.info(
                f"🔮 PREDICTION: {prediction['predicted_family']} → "
                f"{prediction['predicted_service']} [{prediction['lstm_confidence']:.0%}]"
            )

    async def run_prediction_loop(self):
        """Continuous prediction loop — runs every 10 seconds."""
        await self.connect()

        # Subscribe to brain.update to record attacks as they happen
        async def on_brain_update(msg):
            data = json.loads(msg.data.decode())
            if data.get("event") == BrainEvents.RECOVERY_COMPLETE:
                self.record_attack(
                    attack_family=data.get("attack_family", "pod_crash"),
                    target_service=data.get("service", "unknown"),
                    recovery_time_ms=data.get("recovery_time_ms", 10000),
                    success=data.get("success", True),
                )

        await self.nc.subscribe(NATSSubjects.BRAIN_UPDATE, cb=on_brain_update)
        log.info("LSTM Predictor online — listening for attack sequences")

        while True:
            if len(self.attack_history) >= 3:
                prediction = self.predict_next_attack()
                await self.publish_prediction(prediction)
            await asyncio.sleep(10)


# Singleton for import
predictor = LSTMPredictor()


if __name__ == "__main__":
    asyncio.run(predictor.run_prediction_loop())
