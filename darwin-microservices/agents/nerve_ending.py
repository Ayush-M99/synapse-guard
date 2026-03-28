"""
DARWIN Nerve Ending — CUSUM Sidecar (§5, Layer 0)

Deployed alongside each microservice.
Polls /metrics every 5 seconds, runs CUSUM drift detection.
Publishes alerts to NATS on nerve.{service}.alert.

Updated to use shared constants and correct NATS subjects.
"""

import os
import time
import json
import asyncio
import logging
from collections import defaultdict

import httpx
import nats
from prometheus_client.parser import text_string_to_metric_families

from constants import NATSSubjects, BrainEvents, MLConfig, DBConfig

logging.basicConfig(level=logging.INFO, format="[NERVE] %(message)s")
log = logging.getLogger("nerve_ending")

SERVICE_NAME = os.getenv("SERVICE_NAME", "api-gateway")
SERVICE_URL = os.getenv("SERVICE_URL", f"http://{SERVICE_NAME}:8000")
NATS_URL = os.getenv("NATS_URL", DBConfig.NATS_URL)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", str(MLConfig.IF_SCRAPE_INTERVAL)))


class CUSUMDetector:
    """Per-metric CUSUM change-point detection."""

    def __init__(self, threshold: float = 5.0, drift: float = 0.5):
        self.threshold = threshold
        self.drift = drift
        self.s_pos: dict[str, float] = defaultdict(float)
        self.s_neg: dict[str, float] = defaultdict(float)
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.sample_buffer: dict[str, list] = defaultdict(list)
        self.baseline_ready = False
        self.baseline_samples = 6  # 30s at 5s intervals

    def add_sample(self, metric_name: str, value: float):
        """Collect baseline samples or run CUSUM update."""
        if not self.baseline_ready:
            self.sample_buffer[metric_name].append(value)
            # Check if all metrics have enough samples
            if all(len(v) >= self.baseline_samples for v in self.sample_buffer.values()):
                for m, values in self.sample_buffer.items():
                    import numpy as np
                    self.means[m] = float(np.mean(values))
                    self.stds[m] = max(float(np.std(values)), 0.001)
                self.baseline_ready = True
                log.info(f"Baseline collected for {SERVICE_NAME} ({len(self.means)} metrics)")
            return False, 0.0

        return self._cusum_update(metric_name, value)

    def _cusum_update(self, metric: str, value: float) -> tuple[bool, float]:
        mean = self.means.get(metric, 0)
        std = self.stds.get(metric, 1)
        z = (value - mean) / std

        self.s_pos[metric] = max(0, self.s_pos[metric] + z - self.drift)
        self.s_neg[metric] = max(0, self.s_neg[metric] - z - self.drift)

        score = max(self.s_pos[metric], self.s_neg[metric])
        if score > self.threshold:
            self.s_pos[metric] = 0
            self.s_neg[metric] = 0
            return True, score
        return False, score


class NerveEnding:
    """Single-service nerve ending sidecar."""

    def __init__(self):
        self.nc = None
        self.cusum = CUSUMDetector()
        self.http_client = None

    async def connect(self):
        self.nc = await nats.connect(NATS_URL)
        self.http_client = httpx.AsyncClient(timeout=3.0)
        log.info(f"Nerve ending for {SERVICE_NAME} connected to NATS")

    async def poll_metrics(self) -> dict[str, float]:
        """Fetch /metrics and parse Prometheus exposition format."""
        metrics = {}
        try:
            resp = await self.http_client.get(f"{SERVICE_URL}/metrics")
            if resp.status_code == 200:
                for family in text_string_to_metric_families(resp.text):
                    for sample in family.samples:
                        key = sample.name
                        if sample.labels:
                            labels = ",".join(f"{k}={v}" for k, v in sample.labels.items()
                                              if k in ("service", "endpoint"))
                            key = f"{sample.name}{{{labels}}}"
                        metrics[key] = sample.value
        except Exception as e:
            log.warning(f"Metrics poll failed: {e}")
        return metrics

    async def run(self):
        await self.connect()
        log.info(f"Nerve ending ONLINE for {SERVICE_NAME} (poll every {POLL_INTERVAL}s)")

        while True:
            try:
                metrics = await self.poll_metrics()

                for metric_name, value in metrics.items():
                    fired, score = self.cusum.add_sample(metric_name, value)

                    if fired:
                        alert = {
                            "service": SERVICE_NAME,
                            "metric": metric_name,
                            "value": value,
                            "cusum_score": score,
                            "timestamp": time.time(),
                        }
                        subject = NATSSubjects.NERVE_ALERT.format(service=SERVICE_NAME)
                        await self.nc.publish(subject, json.dumps(alert).encode())
                        log.info(f"⚠️ CUSUM alert: {metric_name} (score={score:.2f})")

                # Publish periodic metrics to NATS
                subject = NATSSubjects.NERVE_METRICS.format(service=SERVICE_NAME)
                await self.nc.publish(subject, json.dumps({
                    "service": SERVICE_NAME,
                    "metrics_count": len(metrics),
                    "timestamp": time.time(),
                }).encode())

            except Exception as e:
                log.error(f"Poll loop error: {e}")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    nerve = NerveEnding()
    asyncio.run(nerve.run())
