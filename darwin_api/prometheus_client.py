"""
DARWIN Control Plane — Prometheus Client
Queries the real Prometheus HTTP API at localhost:9090
(port-forwarded from minikube: kubectl port-forward svc/prometheus 9090:9090 -n darwin)
"""

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
REQUEST_TIMEOUT = float(os.getenv("PROMETHEUS_TIMEOUT", "5"))

# The 7 features matching the trained IF/RF model feature vector
METRIC_QUERIES = {
    "cpu_usage_pct": (
        'rate(process_cpu_seconds_total{{job=~".*{service}.*"}}[1m]) * 100'
    ),
    "memory_usage_pct": (
        'process_resident_memory_bytes{{job=~".*{service}.*"}} / 1048576'
    ),
    "http_error_rate_5xx": (
        'sum(rate(http_requests_total{{job=~".*{service}.*",status=~"5.."}}[1m])) / '
        '(sum(rate(http_requests_total{{job=~".*{service}.*"}}[1m])) + 0.001)'
    ),
    "request_latency_p99": (
        'histogram_quantile(0.99,'
        'rate(http_request_duration_seconds_bucket{{job=~".*{service}.*"}}[1m]))'
    ),
    "pod_restart_count_delta": (
        'increase(kube_pod_container_status_restarts_total'
        '{{namespace="patient",pod=~".*{service}.*"}}[1m])'
    ),
    "network_rx_bytes_delta": (
        'rate(container_network_receive_bytes_total'
        '{{namespace="patient",pod=~".*{service}.*"}}[1m])'
    ),
    "network_tx_bytes_delta": (
        'rate(container_network_transmit_bytes_total'
        '{{namespace="patient",pod=~".*{service}.*"}}[1m])'
    ),
}

SERVICES = [
    "auth-service",
    "api-gateway",
    "order-service",
    "payment-service",
    "inventory-service",
    "notification-service",
]


def query(promql: str, at: Optional[float] = None) -> Optional[float]:
    """
    Execute a single instant PromQL query.
    Returns scalar float or None on error.
    """
    params = {"query": promql, "time": at or time.time()}
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if not results:
            return 0.0
        val = results[0].get("value", [None, "0"])[1]
        f = float(val)
        return 0.0 if (f != f) else f   # NaN guard
    except httpx.ConnectError:
        logger.debug(f"Prometheus unreachable at {PROMETHEUS_URL}")
        return None
    except Exception as e:
        logger.warning(f"Prometheus query error: {e}")
        return None


def query_range(promql: str, start: float, end: float, step: str = "5s") -> list[dict]:
    """
    Execute a range query. Returns list of {timestamp, value} dicts.
    """
    params = {"query": promql, "start": start, "end": end, "step": step}
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params=params,
            timeout=REQUEST_TIMEOUT * 2,
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("result", [])
        if not results:
            return []
        values = results[0].get("values", [])
        return [{"timestamp": v[0], "value": float(v[1])} for v in values]
    except Exception as e:
        logger.warning(f"Prometheus range query error: {e}")
        return []


def get_service_metrics(service: str) -> dict:
    """
    Poll all 7 feature metrics for one service.
    Returns dict matching baseline_metrics.csv column names exactly.
    """
    metrics = {}
    for metric_name, query_tpl in METRIC_QUERIES.items():
        promql = query_tpl.format(service=service)
        result = query(promql)
        metrics[metric_name] = result if result is not None else 0.0
    metrics["service"] = service
    metrics["timestamp"] = time.time()
    return metrics


def get_all_services_metrics() -> dict[str, dict]:
    """Poll all 6 patient services concurrently (synchronous version)."""
    return {svc: get_service_metrics(svc) for svc in SERVICES}


def is_prometheus_up() -> bool:
    """Quick health check — queries the built-in 'up' metric."""
    result = query("up")
    return result is not None


def get_targets() -> list[dict]:
    """Return Prometheus scrape targets and their health."""
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/targets",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        active = resp.json().get("data", {}).get("activeTargets", [])
        return [
            {
                "job":    t.get("labels", {}).get("job", "unknown"),
                "target": t.get("scrapeUrl", ""),
                "health": t.get("health", "unknown"),
                "last_scrape": t.get("lastScrape", ""),
            }
            for t in active
        ]
    except Exception as e:
        logger.warning(f"get_targets error: {e}")
        return []
