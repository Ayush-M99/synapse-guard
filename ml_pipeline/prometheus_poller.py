"""
Prometheus Poller — polls Prometheus HTTP API for patient service metrics.
Returns the exact 7-feature vector used to train the Isolation Forest & RF models.

Feature vector (matches baseline_metrics.csv schema exactly):
  cpu_usage_pct, memory_usage_pct, http_error_rate_5xx, request_latency_p99,
  pod_restart_count_delta, network_rx_bytes_delta, network_tx_bytes_delta
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── PromQL query templates ───────────────────────────────────────────────────
# These match what a real FastAPI service instrumented with prometheus_client reports.
# Adjust if your services use different metric names.

QUERIES = {
    # CPU: process_cpu_seconds_total rate × 100 (percentage)
    "cpu_usage_pct": 'rate(process_cpu_seconds_total{{job=~".*{service}.*"}}[1m]) * 100',

    # Memory: process_resident_memory_bytes in MB
    "memory_usage_pct": 'process_resident_memory_bytes{{job=~".*{service}.*"}} / 1048576',

    # HTTP 5xx error rate
    "http_error_rate_5xx": (
        'sum(rate(http_requests_total{{job=~".*{service}.*", status=~"5.."}}[1m])) / '
        '(sum(rate(http_requests_total{{job=~".*{service}.*"}}[1m])) + 0.001)'
    ),

    # P99 request latency seconds
    "request_latency_p99": (
        'histogram_quantile(0.99, '
        'rate(http_request_duration_seconds_bucket{{job=~".*{service}.*"}}[1m]))'
    ),

    # Pod restart delta (kube_pod_container_status_restarts_total)
    "pod_restart_count_delta": (
        'increase(kube_pod_container_status_restarts_total'
        '{{namespace="patient", pod=~".*{service}.*"}}[1m])'
    ),

    # Network RX delta bytes/s
    "network_rx_bytes_delta": (
        'rate(container_network_receive_bytes_total'
        '{{namespace="patient", pod=~".*{service}.*"}}[1m])'
    ),

    # Network TX delta bytes/s
    "network_tx_bytes_delta": (
        'rate(container_network_transmit_bytes_total'
        '{{namespace="patient", pod=~".*{service}.*"}}[1m])'
    ),
}


class PrometheusPoller:
    """
    Async Prometheus HTTP poller.
    Polls /api/v1/query for each service × metric, returns Dict[service, Dict[metric, float]].
    """

    def __init__(self, prometheus_url: str, timeout: float = 4.0):
        self.base_url  = prometheus_url.rstrip("/")
        self.timeout   = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def query(self, promql: str) -> Optional[float]:
        """Execute a single instant PromQL query. Returns scalar or None."""
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql, "time": time.time()},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return 0.0
            # Take first result's value
            val = results[0].get("value", [None, "0"])[1]
            f = float(val)
            return 0.0 if (f != f) else f  # NaN guard
        except Exception:
            return None  # Prometheus unreachable

    async def poll_service(self, service: str) -> Optional[dict]:
        """Poll all 7 features for one service. Returns dict or None."""
        metrics = {}
        tasks = {}

        for metric_name, query_template in QUERIES.items():
            promql = query_template.format(service=service)
            tasks[metric_name] = self.query(promql)

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for metric_name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception) or result is None:
                metrics[metric_name] = 0.0
            else:
                metrics[metric_name] = result

        return metrics

    async def poll_all_services(self, services: list[str]) -> dict[str, dict]:
        """Poll all services concurrently. Returns Dict[service, Dict[metric, float]]."""
        results = await asyncio.gather(
            *[self.poll_service(svc) for svc in services],
            return_exceptions=True,
        )
        snapshot = {}
        for service, result in zip(services, results):
            if isinstance(result, Exception):
                logger.warning(f"Poll failed for {service}: {result}")
                snapshot[service] = self._zero_metrics()
            elif result is not None:
                snapshot[service] = result
        return snapshot

    @staticmethod
    def _zero_metrics() -> dict:
        return {k: 0.0 for k in QUERIES}

    async def close(self):
        if self._client:
            await self._client.aclose()
