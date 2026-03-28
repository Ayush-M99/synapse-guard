"""
DARWIN ML Pipeline — Main Orchestrator
Polls Prometheus → CUSUM + Isolation Forest → Random Forest → LSTM → NATS
Uses pre-trained models from Chaos_Platform_Assets/models/ (DO NOT MODIFY MODELS)
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import nats
from prometheus_client import start_http_server, Counter, Gauge, Histogram

from .cusum import CUSUMDetector
from .model_loader import ModelLoader
from .prometheus_poller import PrometheusPoller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ML-BRAIN] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
PROMETHEUS_URL   = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
NATS_URL         = os.getenv("NATS_URL",        "nats://localhost:4222")
SCRAPE_INTERVAL  = float(os.getenv("SCRAPE_INTERVAL", "5"))
IF_THRESHOLD     = float(os.getenv("IF_THRESHOLD",    "0.65"))
IF_SUSTAIN_COUNT = int(os.getenv("IF_SUSTAIN_COUNT",  "3"))
RF_KNOWN_THRESH  = float(os.getenv("RF_KNOWN_THRESH",  "0.85"))
RF_PROB_THRESH   = float(os.getenv("RF_PROB_THRESH",   "0.60"))
LSTM_CONF_THRESH = float(os.getenv("LSTM_CONF_THRESH", "0.70"))
LSTM_SEQ_LEN     = int(os.getenv("LSTM_SEQ_LEN",       "7"))

SERVICES = [
    "auth-service",
    "api-gateway",
    "order-service",
    "payment-service",
    "inventory-service",
    "notification-service",
]

# ─── Prometheus Metrics (for Prometheus to scrape this module itself) ─────────
anomaly_counter   = Counter("darwin_anomalies_total",   "Total anomalies detected",    ["service"])
recovery_counter  = Counter("darwin_recoveries_total",  "Total recovery events",       ["service", "attack_family"])
anomaly_score_g   = Gauge("darwin_anomaly_score",        "Current IF anomaly score",    ["service"])
rf_confidence_g   = Gauge("darwin_rf_confidence",        "RF classifier confidence",    ["service", "attack_family"])
pipeline_latency  = Histogram("darwin_pipeline_latency_seconds", "ML pipeline loop latency")


class DarwinMLPipeline:
    """
    DARWIN ML Brain — closed-loop detection pipeline.

    Layer 0 (CUSUM)      → slow drift detection per service/metric
    Layer 1 (IF)         → fast unsupervised anomaly score
    Layer 2 (RF)         → attack family classification
    Layer 3 (LSTM)       → temporal next-attack prediction
    """

    def __init__(self):
        self.models       = ModelLoader()
        self.poller       = PrometheusPoller(PROMETHEUS_URL)
        self.cusum        = {svc: CUSUMDetector() for svc in SERVICES}
        self.nc           = None

        # Rolling state per service
        self.anomaly_streak: dict[str, int]         = defaultdict(int)   # consecutive IF hits
        self.attack_history: dict[str, deque]       = defaultdict(lambda: deque(maxlen=LSTM_SEQ_LEN))
        self.feature_buffer: dict[str, list]        = defaultdict(list)

        self.running = False

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self):
        logger.info("🧠 DARWIN ML Pipeline starting...")
        self.models.load_all()

        # Connect to NATS
        self.nc = await nats.connect(NATS_URL)
        logger.info(f"📡 NATS connected: {NATS_URL}")

        # Expose own /metrics for Prometheus
        start_http_server(8001)
        logger.info("📊 ML pipeline metrics on :8001/metrics")

        self.running = True
        await self._run_loop()

    async def stop(self):
        self.running = False
        if self.nc:
            await self.nc.drain()
        logger.info("🛑 ML Pipeline stopped")

    # ─── Main loop ───────────────────────────────────────────────────────────

    async def _run_loop(self):
        logger.info(f"🔄 Polling Prometheus every {SCRAPE_INTERVAL}s...")
        while self.running:
            tick_start = time.monotonic()
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"❌ Pipeline tick error: {e}", exc_info=True)
            elapsed = time.monotonic() - tick_start
            pipeline_latency.observe(elapsed)
            await asyncio.sleep(max(0, SCRAPE_INTERVAL - elapsed))

    async def _tick(self):
        """Single pipeline iteration across all services."""
        metrics_snapshot = await self.poller.poll_all_services(SERVICES)
        if not metrics_snapshot:
            logger.warning("⚠️  No metrics from Prometheus — is it running?")
            return

        for service, features in metrics_snapshot.items():
            await self._process_service(service, features)

    # ─── Per-service processing ───────────────────────────────────────────────

    async def _process_service(self, service: str, features: dict):
        """
        Run CUSUM → IF → (maybe) RF → (maybe) LSTM for one service.
        """
        feature_vec = self._to_feature_vector(features)
        if feature_vec is None:
            return

        # ── Layer 0: CUSUM slow drift ─────────────────────────────────────
        cusum_fired = self.cusum[service].update(features["cpu_usage_pct"])
        if cusum_fired:
            logger.warning(f"⚡ CUSUM DRIFT [{service}] — slow degradation detected")
            await self._publish_brain_update("cusum_drift", service, {
                "detection_path": "cusum", "metric": "cpu_usage_pct"
            })

        # ── Layer 1: Isolation Forest ─────────────────────────────────────
        anomaly_score = self.models.if_score(feature_vec)
        anomaly_score_g.labels(service=service).set(anomaly_score)

        if anomaly_score > IF_THRESHOLD:
            self.anomaly_streak[service] += 1
            logger.info(f"🔍 IF [{service}] score={anomaly_score:.3f} streak={self.anomaly_streak[service]}")
        else:
            self.anomaly_streak[service] = 0

        # Must sustain for IF_SUSTAIN_COUNT consecutive scrapes
        if self.anomaly_streak[service] < IF_SUSTAIN_COUNT:
            return

        # Anomaly confirmed — reset streak
        self.anomaly_streak[service] = 0
        anomaly_counter.labels(service=service).inc()
        logger.warning(f"🚨 ANOMALY CONFIRMED [{service}] score={anomaly_score:.3f}")

        # ── Layer 2: Random Forest classification ─────────────────────────
        rf_label, rf_confidence = self.models.rf_classify(feature_vec)
        rf_confidence_g.labels(service=service, attack_family=rf_label).set(rf_confidence)
        logger.info(f"🧠 RF [{service}] label={rf_label} confidence={rf_confidence:.3f}")

        # Determine attack state
        if rf_confidence >= RF_KNOWN_THRESH:
            attack_state = "KNOWN"
        elif rf_confidence >= RF_PROB_THRESH:
            attack_state = "PROBABLE"
        else:
            attack_state = "UNKNOWN"

        # Record attack in history for LSTM
        self.attack_history[service].append({
            "family": rf_label,
            "recovery_time": 0,      # will be updated by antibody
            "success": True,          # optimistic default
            "timestamp": time.time(),
        })

        # Publish classified event to NATS → Antibody picks it up
        event = {
            "event":          "attack_detected",
            "service":        service,
            "anomaly_score":  round(anomaly_score, 4),
            "rf_label":       rf_label,
            "rf_confidence":  round(rf_confidence, 4),
            "attack_state":   attack_state,
            "detection_path": "cusum+if+rf" if cusum_fired else "if+rf",
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }
        await self.nc.publish("brain.rf_classified", json.dumps(event).encode())
        await self._publish_brain_update("attack_detected", service, event)
        logger.info(f"📤 Published brain.rf_classified [{service}] state={attack_state}")

        # ── Layer 3: LSTM next-attack prediction ──────────────────────────
        await self._run_lstm_prediction(service)

    async def _run_lstm_prediction(self, service: str):
        """
        Run LSTM on the attack history window.
        Publishes lstm.prediction if confidence >= threshold.
        """
        history = list(self.attack_history[service])
        if len(history) < 2:
            return  # Need at least 2 events for meaningful sequence

        predicted_family, lstm_confidence = self.models.lstm_predict(history)
        if predicted_family is None:
            return

        logger.info(f"🔮 LSTM [{service}] predicts={predicted_family} confidence={lstm_confidence:.3f}")

        if lstm_confidence >= LSTM_CONF_THRESH:
            prediction_event = {
                "event":            "lstm_prediction",
                "source_service":   service,
                "predicted_family": predicted_family,
                "predicted_service": service,       # same service most likely target
                "lstm_confidence":  round(lstm_confidence, 4),
                "timestamp":        datetime.now(timezone.utc).isoformat(),
            }
            await self.nc.publish("lstm.prediction", json.dumps(prediction_event).encode())
            await self._publish_brain_update("preemptive_action", service, prediction_event)
            logger.warning(f"🛡️  LSTM PREDICTION FIRED [{service}] — {predicted_family} ({lstm_confidence:.0%} conf)")

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _to_feature_vector(self, features: dict) -> list | None:
        """Convert Prometheus metric dict to IF/RF feature vector."""
        FEATURE_KEYS = [
            "cpu_usage_pct",
            "memory_usage_pct",
            "http_error_rate_5xx",
            "request_latency_p99",
            "pod_restart_count_delta",
            "network_rx_bytes_delta",
            "network_tx_bytes_delta",
        ]
        try:
            vec = [float(features.get(k, 0.0) or 0.0) for k in FEATURE_KEYS]
            return vec
        except Exception as e:
            logger.warning(f"Feature vector error: {e}")
            return None

    async def _publish_brain_update(self, event_type: str, service: str, payload: dict):
        """Publish to brain.update → picked up by ws_bridge → dashboard."""
        msg = {"event": event_type, "service": service, **payload}
        await self.nc.publish("brain.update", json.dumps(msg).encode())


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main():
    pipeline = DarwinMLPipeline()
    try:
        await pipeline.start()
    except KeyboardInterrupt:
        await pipeline.stop()


if __name__ == "__main__":
    asyncio.run(main())
