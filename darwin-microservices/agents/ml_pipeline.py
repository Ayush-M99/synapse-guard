"""
DARWIN ML Pipeline — Three-Layer Ensemble Detection System (§5)

Layer 0: CUSUM       — slow drift detection (catches camouflage attacks IF misses)
Layer 1: Isolation Forest — anomaly detection on 7-feature vector per service
Layer 2: Random Forest    — attack family classification
Layer 3: LSTM             — temporal prediction (separate module)

Polls Prometheus every 5 seconds (Option A — direct HTTP poll).
"""

import os
import time
import json
import asyncio
import logging
from collections import defaultdict
from typing import Optional

import numpy as np
import httpx
import nats
import joblib

from constants import (
    NATSSubjects, BrainEvents, MLConfig, AttackState,
    ServiceConfig, DBConfig,
)

logging.basicConfig(level=logging.INFO, format="[ML-PIPELINE] %(message)s")
log = logging.getLogger("ml_pipeline")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)
MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(os.path.dirname(__file__), "..", "models"))


# ═══════════════════════════════════════════════════════════════
# LAYER 0 — CUSUM (§5 — Classical Statistics Pre-filter)
# ═══════════════════════════════════════════════════════════════

class CUSUMDetector:
    """Catches slow-burn camouflage attacks that IF misses.
    Each individual reading looks normal, but cumulative drift is detectable."""

    def __init__(self, threshold: float = 5.0, drift: float = 0.5):
        self.threshold = threshold
        self.drift = drift
        # Per-service, per-metric CUSUM state
        self.state: dict[str, dict[str, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"s_pos": 0.0, "s_neg": 0.0, "mean": 0.0, "std": 1.0})
        )

    def set_baseline(self, service: str, metric: str, mean: float, std: float):
        self.state[service][metric]["mean"] = mean
        self.state[service][metric]["std"] = max(std, 0.001)

    def update(self, service: str, metric: str, value: float) -> tuple[bool, float]:
        """Returns (is_anomaly, cusum_score)."""
        s = self.state[service][metric]
        z = (value - s["mean"]) / s["std"]

        s["s_pos"] = max(0, s["s_pos"] + z - self.drift)
        s["s_neg"] = max(0, s["s_neg"] - z - self.drift)

        score = max(s["s_pos"], s["s_neg"])
        if score > self.threshold:
            s["s_pos"] = 0  # Reset after trigger
            s["s_neg"] = 0
            return True, score
        return False, score


# ═══════════════════════════════════════════════════════════════
# LAYER 1 — ISOLATION FOREST (§5 — Unsupervised Anomaly Detection)
# ═══════════════════════════════════════════════════════════════

class IsolationForestDetector:
    """Runs every 5 seconds on 7-feature vector per service.
    Threshold: score > 0.65, sustained for 3 consecutive scrapes (15s minimum)."""

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.consecutive_anomalies: dict[str, int] = defaultdict(int)

        if model_path and os.path.exists(model_path):
            self.model = joblib.load(model_path)
            log.info(f"Isolation Forest loaded from {model_path}")
        else:
            log.warning("No IF model found — using threshold-based fallback")

    def score(self, service: str, features: list[float]) -> tuple[bool, float]:
        """Returns (is_anomaly_sustained, anomaly_score)."""
        if self.model is not None:
            X = np.array(features).reshape(1, -1)
            # sklearn IF: decision_function returns negative for anomalies
            raw_score = -self.model.decision_function(X)[0]
            # Normalize to 0-1 range
            anomaly_score = min(max((raw_score + 0.5) / 1.0, 0.0), 1.0)
        else:
            # Fallback: simple z-score based anomaly scoring
            anomaly_score = self._fallback_score(features)

        if anomaly_score > MLConfig.IF_ANOMALY_THRESHOLD:
            self.consecutive_anomalies[service] += 1
        else:
            self.consecutive_anomalies[service] = 0

        is_sustained = self.consecutive_anomalies[service] >= MLConfig.IF_SUSTAINED_SCRAPES
        return is_sustained, anomaly_score

    def _fallback_score(self, features: list[float]) -> float:
        """Threshold-based scoring when no model is available."""
        cpu, mem, err_rate, latency, restarts, net_rx, net_tx = features
        score = 0.0
        if cpu > 80: score += 0.3
        if mem > 85: score += 0.2
        if err_rate > 0.1: score += 0.3
        if latency > 2.0: score += 0.2
        if restarts > 0: score += 0.3
        return min(score, 1.0)


# ═══════════════════════════════════════════════════════════════
# LAYER 2 — RANDOM FOREST CLASSIFIER (§5 — Attack Classification)
# ═══════════════════════════════════════════════════════════════

class RandomForestClassifier:
    """Takes anomaly signal and classifies which attack family it belongs to.
    Feature vector: current 7 metrics + delta_30s + delta_60s + downstream_affected."""

    FAMILY_LABELS = ["pod_crash", "network", "resource", "timing", "cost"]

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        if model_path and os.path.exists(model_path):
            self.model = joblib.load(model_path)
            log.info(f"Random Forest loaded from {model_path}")
        else:
            log.warning("No RF model found — using rule-based fallback classifier")

    def classify(self, features: list[float], features_delta_30s: list[float],
                 features_delta_60s: list[float],
                 downstream_affected: bool = False) -> tuple[str, float]:
        """Returns (attack_family_label, confidence_score)."""
        if self.model is not None:
            X = np.array(
                features + features_delta_30s + features_delta_60s + [int(downstream_affected)]
            ).reshape(1, -1)
            prediction = self.model.predict(X)[0]
            probabilities = self.model.predict_proba(X)[0]
            confidence = float(max(probabilities))
            label = str(prediction)
            return label, confidence
        else:
            return self._rule_based_classify(features)

    def _rule_based_classify(self, features: list[float]) -> tuple[str, float]:
        """Rule-based fallback when no model is available."""
        cpu, mem, err_rate, latency, restarts, net_rx, net_tx = features

        if restarts > 0 and err_rate > 0.3:
            return "pod_crash", 0.88
        elif latency > 2.0 or (net_rx < 100 and net_tx < 100):
            return "network", 0.82
        elif cpu > 80 or mem > 85:
            return "resource", 0.85
        elif err_rate > 0.1 and latency > 1.0:
            return "timing", 0.70
        else:
            return "resource", 0.55


# ═══════════════════════════════════════════════════════════════
# PROMETHEUS POLLER — Feature Vector Extraction
# ═══════════════════════════════════════════════════════════════

class PrometheusPoller:
    """Queries Prometheus API every 5 seconds to build feature vectors."""

    QUERIES = {
        "cpu_usage_pct": 'sum(rate(container_cpu_usage_seconds_total{{pod=~"{service}-.*"}}[1m])) * 100',
        "memory_usage_pct": 'sum(container_memory_usage_bytes{{pod=~"{service}-.*"}}) / (256 * 1024 * 1024) * 100',
        "http_error_rate_5xx": 'sum(rate(http_errors_total{{service="{service}"}}[1m])) / clamp_min(sum(rate(http_requests_total{{service="{service}"}}[1m])), 0.001)',
        "request_latency_p99": 'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[1m])) by (le))',
        "pod_restart_count_delta": 'sum(increase(kube_pod_container_status_restarts_total{{pod=~"{service}-.*"}}[1m]))',
        "network_rx_bytes_delta": 'sum(rate(container_network_receive_bytes_total{{pod=~"{service}-.*"}}[1m]))',
        "network_tx_bytes_delta": 'sum(rate(container_network_transmit_bytes_total{{pod=~"{service}-.*"}}[1m]))',
    }

    def __init__(self, prometheus_url: str):
        self.url = prometheus_url

    async def fetch_features(self, service: str) -> list[float]:
        """Fetch 7-feature vector for a single service."""
        features = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            for metric_name in MLConfig.FEATURE_NAMES:
                query_template = self.QUERIES.get(metric_name, "")
                query = query_template.format(service=service)
                try:
                    resp = await client.get(
                        f"{self.url}/api/v1/query",
                        params={"query": query}
                    )
                    data = resp.json()
                    if data.get("data", {}).get("result"):
                        val = float(data["data"]["result"][0]["value"][1])
                        # Handle NaN/Inf
                        if np.isnan(val) or np.isinf(val):
                            val = 0.0
                    else:
                        val = 0.0
                except Exception:
                    val = 0.0
                features.append(val)
        return features


# ═══════════════════════════════════════════════════════════════
# ML PIPELINE — Ensemble Orchestrator
# ═══════════════════════════════════════════════════════════════

class MLPipeline:
    """Orchestrates the three-layer ML ensemble.

    Flow:
        CUSUM fires (slow drift) OR IF fires (anomaly > 0.65, 3x sustained)
            ↓
        RF Classifier → "network_partition, 91% confidence"
            ↓
        Publish alert → Decision Engine
    """

    def __init__(self):
        self.nc: Optional[nats.NATS] = None
        self.cusum = CUSUMDetector(threshold=5.0, drift=0.5)
        self.isolation_forest = IsolationForestDetector(
            model_path=os.path.join(MODEL_DIR, "isolation_forest.joblib")
        )
        self.random_forest = RandomForestClassifier(
            model_path=os.path.join(MODEL_DIR, "random_forest.joblib")
        )
        self.prometheus = PrometheusPoller(PROMETHEUS_URL)

        # History buffers for RF windowed features
        self.history: dict[str, list[tuple[float, list[float]]]] = defaultdict(list)
        self.baseline_collected: dict[str, bool] = {}

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        log.info(f"Connected to NATS at {NATS_URL}")

    async def collect_baseline(self, duration_seconds: int = 30):
        """Collect baseline metrics (30 seconds) to calibrate CUSUM."""
        log.info(f"Collecting baseline for {duration_seconds}s...")
        samples: dict[str, list[list[float]]] = defaultdict(list)

        for _ in range(duration_seconds // MLConfig.IF_SCRAPE_INTERVAL):
            for service in ServiceConfig.SERVICE_NAMES:
                features = await self.prometheus.fetch_features(service)
                samples[service].append(features)
            await asyncio.sleep(MLConfig.IF_SCRAPE_INTERVAL)

        # Set CUSUM baselines
        for service, feature_lists in samples.items():
            arr = np.array(feature_lists)
            for i, metric_name in enumerate(MLConfig.FEATURE_NAMES):
                mean = float(np.mean(arr[:, i]))
                std = float(np.std(arr[:, i]))
                self.cusum.set_baseline(service, metric_name, mean, std)
            self.baseline_collected[service] = True

        log.info("Baseline collection complete")

    def _get_deltas(self, service: str, current: list[float], seconds_ago: int) -> list[float]:
        """Get feature deltas from N seconds ago."""
        history = self.history[service]
        now = time.time()
        target_time = now - seconds_ago

        closest = None
        for ts, features in reversed(history):
            if ts <= target_time:
                closest = features
                break

        if closest is None:
            return [0.0] * len(current)

        return [c - p for c, p in zip(current, closest)]

    def _check_downstream_affected(self, service: str,
                                    all_scores: dict[str, float]) -> bool:
        """Check if downstream services are also showing anomalies."""
        # Simple check: are any other services also anomalous?
        for svc, score in all_scores.items():
            if svc != service and score > MLConfig.IF_ANOMALY_THRESHOLD:
                return True
        return False

    async def _publish_alert(self, service: str, attack_family: str,
                             confidence: float, anomaly_score: float,
                             attack_state: str, source: str):
        """Publish detection alert to NATS for Decision Engine."""
        subject = NATSSubjects.NERVE_ALERT.format(service=service)
        payload = {
            "service": service,
            "attack_family": attack_family,
            "rf_confidence": confidence,
            "anomaly_score": anomaly_score,
            "attack_state": attack_state,
            "source": source,
            "timestamp": time.time(),
        }

        if self.nc:
            await self.nc.publish(subject, json.dumps(payload).encode())

        # Also publish to brain.update for dashboard
        brain_payload = {
            "event": BrainEvents.ATTACK_DETECTED,
            "service": service,
            "attack_family": attack_family,
            "confidence": confidence,
            "anomaly_score": anomaly_score,
            "attack_state": attack_state,
            "timestamp": time.time(),
        }
        if self.nc:
            await self.nc.publish(NATSSubjects.BRAIN_UPDATE, json.dumps(brain_payload).encode())

        log.info(f"🔍 ALERT: {service} | {attack_family} | conf={confidence:.2f} | state={attack_state} | source={source}")

    async def run_detection_loop(self):
        """Main detection loop — runs every 5 seconds."""
        await self.connect()
        await self.collect_baseline()

        log.info("═" * 50)
        log.info(" ML PIPELINE ONLINE — Three-Layer Ensemble Active")
        log.info("═" * 50)

        while True:
            try:
                all_scores: dict[str, float] = {}

                # Phase 1: Collect all features
                service_features: dict[str, list[float]] = {}
                for service in ServiceConfig.SERVICE_NAMES:
                    features = await self.prometheus.fetch_features(service)
                    service_features[service] = features

                    # Store in history for delta calculations
                    self.history[service].append((time.time(), features))
                    # Keep only last 2 minutes of history
                    cutoff = time.time() - 120
                    self.history[service] = [
                        (t, f) for t, f in self.history[service] if t > cutoff
                    ]

                # Phase 2: Run IF on all services to get scores
                for service, features in service_features.items():
                    _, score = self.isolation_forest.score(service, features)
                    all_scores[service] = score

                # Phase 3: For each service, run detection ensemble
                for service, features in service_features.items():
                    # Layer 0: CUSUM check per metric
                    cusum_fired = False
                    cusum_metric = ""
                    cusum_score = 0.0
                    for i, metric_name in enumerate(MLConfig.FEATURE_NAMES):
                        fired, score = self.cusum.update(service, metric_name, features[i])
                        if fired:
                            cusum_fired = True
                            cusum_metric = metric_name
                            cusum_score = score

                    # Layer 1: IF sustained detection
                    if_sustained, if_score = self.isolation_forest.score(service, features)

                    # If either CUSUM or IF fires → run RF classifier
                    if cusum_fired or if_sustained:
                        source = "CUSUM" if cusum_fired else "IF"
                        if cusum_fired:
                            log.info(f"⚠️ CUSUM fired on {service}/{cusum_metric} (score={cusum_score:.2f})")
                        if if_sustained:
                            log.info(f"⚠️ IF sustained anomaly on {service} (score={if_score:.2f})")

                        # Layer 2: RF Classification
                        deltas_30s = self._get_deltas(service, features, 30)
                        deltas_60s = self._get_deltas(service, features, 60)
                        downstream = self._check_downstream_affected(service, all_scores)

                        family, confidence = self.random_forest.classify(
                            features, deltas_30s, deltas_60s, downstream
                        )

                        # Determine attack state based on RF confidence
                        if confidence >= MLConfig.RF_KNOWN_THRESHOLD:
                            state = AttackState.KNOWN
                        elif confidence >= MLConfig.RF_PROBABLE_THRESHOLD:
                            state = AttackState.PROBABLE
                        else:
                            state = AttackState.UNKNOWN

                        await self._publish_alert(
                            service=service,
                            attack_family=family,
                            confidence=confidence,
                            anomaly_score=if_score,
                            attack_state=state,
                            source=source,
                        )

            except Exception as e:
                log.error(f"Detection loop error: {e}")

            await asyncio.sleep(MLConfig.IF_SCRAPE_INTERVAL)


# ═══════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pipeline = MLPipeline()
    asyncio.run(pipeline.run_detection_loop())
