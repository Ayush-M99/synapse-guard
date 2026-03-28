"""
Nerve Ending Sidecar Agent
Per-pod agent that monitors metrics and triggers reflex responses

Responsibilities:
1. Monitor pod CPU, memory, error rate, latency
2. Publish alerts to NATS on nerve.{service}.alert
3. Trigger automatic reflex isolation when thresholds exceeded
4. Report telemetry to central nervous system
"""
import os
import time
import asyncio
import json
import signal
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

import httpx
import nats
from nats.aio.client import Client as NATS

# Configuration
SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown")
POD_NAME = os.getenv("POD_NAME", os.getenv("HOSTNAME", "unknown"))
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "darwin-microservices")
NODE_NAME = os.getenv("NODE_NAME", "unknown")

NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
TARGET_SERVICE_URL = os.getenv("TARGET_SERVICE_URL", "http://localhost:8000")
METRICS_ENDPOINT = os.getenv("METRICS_ENDPOINT", "/metrics")
HEALTH_ENDPOINT = os.getenv("HEALTH_ENDPOINT", "/health")

# Thresholds
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "80"))
MEMORY_THRESHOLD = float(os.getenv("MEMORY_THRESHOLD", "85"))
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "0.1"))
LATENCY_THRESHOLD_MS = float(os.getenv("LATENCY_THRESHOLD_MS", "1000"))

# Intervals
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "30"))

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

class AlertType(str, Enum):
    CPU_HIGH = "cpu_high"
    MEMORY_HIGH = "memory_high"
    ERROR_RATE_HIGH = "error_rate_high"
    LATENCY_HIGH = "latency_high"
    HEALTH_CHECK_FAILED = "health_check_failed"
    SERVICE_UNAVAILABLE = "service_unavailable"

@dataclass
class MetricSnapshot:
    timestamp: str
    service: str
    pod: str
    namespace: str
    node: str
    cpu_percent: float
    memory_percent: float
    request_count: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    health_status: str

@dataclass
class NerveAlert:
    timestamp: str
    service: str
    pod: str
    namespace: str
    node: str
    alert_type: str
    severity: str
    message: str
    metric_value: float
    threshold: float
    recommend_action: str

class NerveEnding:
    def __init__(self):
        self.nc: Optional[NATS] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.running = False
        
        # Tracking
        self.last_alert_times: Dict[str, float] = {}
        self.consecutive_failures = 0
        self.metrics_history: list = []
        
        # Parsed metrics cache
        self.last_metrics: Dict[str, float] = {}
        
    async def connect(self):
        """Connect to NATS and initialize HTTP client"""
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        for attempt in range(30):
            try:
                self.nc = await nats.connect(NATS_URL)
                print(f"[NerveEnding:{POD_NAME}] Connected to NATS at {NATS_URL}")
                return True
            except Exception as e:
                print(f"[NerveEnding:{POD_NAME}] NATS connection attempt {attempt + 1}/30 failed: {e}")
                await asyncio.sleep(2)
        
        print(f"[NerveEnding:{POD_NAME}] WARNING: Running without NATS connection")
        return False
    
    async def disconnect(self):
        """Clean shutdown"""
        self.running = False
        if self.nc:
            await self.nc.drain()
        if self.http_client:
            await self.http_client.aclose()
    
    async def fetch_metrics(self) -> Optional[str]:
        """Fetch Prometheus metrics from target service"""
        try:
            response = await self.http_client.get(f"{TARGET_SERVICE_URL}{METRICS_ENDPOINT}")
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            print(f"[NerveEnding:{POD_NAME}] Failed to fetch metrics: {e}")
            return None
    
    async def check_health(self) -> tuple[bool, str]:
        """Check health endpoint of target service"""
        try:
            response = await self.http_client.get(f"{TARGET_SERVICE_URL}{HEALTH_ENDPOINT}")
            if response.status_code == 200:
                data = response.json()
                return True, data.get("status", "healthy")
            return False, f"status_code:{response.status_code}"
        except Exception as e:
            return False, str(e)
    
    def parse_prometheus_metrics(self, metrics_text: str) -> Dict[str, float]:
        """Parse Prometheus text format metrics"""
        parsed = {}
        
        for line in metrics_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            try:
                # Handle metrics with labels
                if "{" in line:
                    metric_name = line.split("{")[0]
                    value_str = line.split("}")[-1].strip()
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        value_str = parts[1]
                    else:
                        continue
                
                try:
                    value = float(value_str)
                    # Aggregate metrics (sum if multiple with same name)
                    if metric_name in parsed:
                        parsed[metric_name] += value
                    else:
                        parsed[metric_name] = value
                except ValueError:
                    pass
                    
            except Exception:
                continue
        
        return parsed
    
    def extract_service_metrics(self, parsed: Dict[str, float]) -> Dict[str, float]:
        """Extract key metrics for monitoring"""
        prefix = SERVICE_NAME.replace("-", "_")
        
        # Common metric patterns to look for
        cpu_keys = [f"{prefix}_cpu_usage_pct", "cpu_usage_pct", "process_cpu_seconds_total"]
        mem_keys = [f"{prefix}_memory_usage_pct", "memory_usage_pct", "process_resident_memory_bytes"]
        request_keys = [f"{prefix}_requests_total", "http_requests_total", "requests_total"]
        latency_keys = [f"{prefix}_request_latency_seconds_sum", "request_latency_seconds_sum"]
        latency_count_keys = [f"{prefix}_request_latency_seconds_count", "request_latency_seconds_count"]
        
        def find_metric(keys):
            for key in keys:
                for metric_name, value in parsed.items():
                    if key in metric_name:
                        return value
            return 0.0
        
        cpu = find_metric(cpu_keys)
        memory = find_metric(mem_keys)
        
        # Calculate request metrics
        total_requests = find_metric(request_keys)
        
        # Calculate error rate from status labels
        error_count = 0
        for key, value in parsed.items():
            if "requests_total" in key and ("500" in key or "502" in key or "503" in key or "504" in key):
                error_count += value
        
        error_rate = error_count / total_requests if total_requests > 0 else 0.0
        
        # Calculate average latency
        latency_sum = find_metric(latency_keys)
        latency_count = find_metric(latency_count_keys)
        avg_latency_ms = (latency_sum / latency_count * 1000) if latency_count > 0 else 0.0
        
        return {
            "cpu_percent": cpu,
            "memory_percent": memory,
            "request_count": int(total_requests),
            "error_count": int(error_count),
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency_ms
        }
    
    async def publish_alert(self, alert: NerveAlert):
        """Publish alert to NATS"""
        # Check cooldown
        alert_key = f"{alert.alert_type}:{alert.pod}"
        now = time.time()
        
        if alert_key in self.last_alert_times:
            if now - self.last_alert_times[alert_key] < ALERT_COOLDOWN:
                return  # Still in cooldown
        
        self.last_alert_times[alert_key] = now
        
        # Publish to NATS
        subject = f"nerve.{SERVICE_NAME}.alert"
        payload = json.dumps(asdict(alert)).encode()
        
        if self.nc:
            try:
                await self.nc.publish(subject, payload)
                print(f"[NerveEnding:{POD_NAME}] Alert published: {alert.alert_type} - {alert.message}")
            except Exception as e:
                print(f"[NerveEnding:{POD_NAME}] Failed to publish alert: {e}")
        else:
            print(f"[NerveEnding:{POD_NAME}] ALERT (no NATS): {alert.alert_type} - {alert.message}")
    
    async def publish_telemetry(self, snapshot: MetricSnapshot):
        """Publish telemetry data to NATS"""
        subject = f"nerve.{SERVICE_NAME}.telemetry"
        payload = json.dumps(asdict(snapshot)).encode()
        
        if self.nc:
            try:
                await self.nc.publish(subject, payload)
            except Exception as e:
                print(f"[NerveEnding:{POD_NAME}] Failed to publish telemetry: {e}")
    
    def determine_severity(self, value: float, threshold: float, metric_type: str) -> AlertSeverity:
        """Determine alert severity based on how far over threshold"""
        ratio = value / threshold if threshold > 0 else 1.0
        
        if ratio >= 1.5:
            return AlertSeverity.EMERGENCY
        elif ratio >= 1.25:
            return AlertSeverity.CRITICAL
        elif ratio >= 1.0:
            return AlertSeverity.WARNING
        else:
            return AlertSeverity.INFO
    
    def recommend_action(self, alert_type: AlertType, severity: AlertSeverity) -> str:
        """Recommend remediation action"""
        actions = {
            AlertType.CPU_HIGH: {
                AlertSeverity.WARNING: "scale_horizontal",
                AlertSeverity.CRITICAL: "scale_horizontal_urgent",
                AlertSeverity.EMERGENCY: "isolate_and_scale"
            },
            AlertType.MEMORY_HIGH: {
                AlertSeverity.WARNING: "investigate_leak",
                AlertSeverity.CRITICAL: "restart_pod",
                AlertSeverity.EMERGENCY: "isolate_and_restart"
            },
            AlertType.ERROR_RATE_HIGH: {
                AlertSeverity.WARNING: "enable_circuit_breaker",
                AlertSeverity.CRITICAL: "partial_traffic_shift",
                AlertSeverity.EMERGENCY: "full_traffic_shift"
            },
            AlertType.LATENCY_HIGH: {
                AlertSeverity.WARNING: "cache_warmup",
                AlertSeverity.CRITICAL: "scale_horizontal",
                AlertSeverity.EMERGENCY: "traffic_shed"
            },
            AlertType.HEALTH_CHECK_FAILED: {
                AlertSeverity.WARNING: "restart_pod",
                AlertSeverity.CRITICAL: "restart_pod",
                AlertSeverity.EMERGENCY: "isolate_pod"
            },
            AlertType.SERVICE_UNAVAILABLE: {
                AlertSeverity.WARNING: "restart_pod",
                AlertSeverity.CRITICAL: "isolate_and_restart",
                AlertSeverity.EMERGENCY: "failover"
            }
        }
        
        return actions.get(alert_type, {}).get(severity, "investigate")
    
    async def analyze_and_alert(self, metrics: Dict[str, float], health_ok: bool, health_status: str):
        """Analyze metrics and generate alerts if needed"""
        timestamp = datetime.utcnow().isoformat()
        
        # CPU Alert
        if metrics["cpu_percent"] > CPU_THRESHOLD:
            severity = self.determine_severity(metrics["cpu_percent"], CPU_THRESHOLD, "cpu")
            alert = NerveAlert(
                timestamp=timestamp,
                service=SERVICE_NAME,
                pod=POD_NAME,
                namespace=POD_NAMESPACE,
                node=NODE_NAME,
                alert_type=AlertType.CPU_HIGH.value,
                severity=severity.value,
                message=f"CPU usage at {metrics['cpu_percent']:.1f}% (threshold: {CPU_THRESHOLD}%)",
                metric_value=metrics["cpu_percent"],
                threshold=CPU_THRESHOLD,
                recommend_action=self.recommend_action(AlertType.CPU_HIGH, severity)
            )
            await self.publish_alert(alert)
        
        # Memory Alert
        if metrics["memory_percent"] > MEMORY_THRESHOLD:
            severity = self.determine_severity(metrics["memory_percent"], MEMORY_THRESHOLD, "memory")
            alert = NerveAlert(
                timestamp=timestamp,
                service=SERVICE_NAME,
                pod=POD_NAME,
                namespace=POD_NAMESPACE,
                node=NODE_NAME,
                alert_type=AlertType.MEMORY_HIGH.value,
                severity=severity.value,
                message=f"Memory usage at {metrics['memory_percent']:.1f}% (threshold: {MEMORY_THRESHOLD}%)",
                metric_value=metrics["memory_percent"],
                threshold=MEMORY_THRESHOLD,
                recommend_action=self.recommend_action(AlertType.MEMORY_HIGH, severity)
            )
            await self.publish_alert(alert)
        
        # Error Rate Alert
        if metrics["error_rate"] > ERROR_RATE_THRESHOLD:
            severity = self.determine_severity(metrics["error_rate"], ERROR_RATE_THRESHOLD, "error_rate")
            alert = NerveAlert(
                timestamp=timestamp,
                service=SERVICE_NAME,
                pod=POD_NAME,
                namespace=POD_NAMESPACE,
                node=NODE_NAME,
                alert_type=AlertType.ERROR_RATE_HIGH.value,
                severity=severity.value,
                message=f"Error rate at {metrics['error_rate']*100:.1f}% (threshold: {ERROR_RATE_THRESHOLD*100}%)",
                metric_value=metrics["error_rate"],
                threshold=ERROR_RATE_THRESHOLD,
                recommend_action=self.recommend_action(AlertType.ERROR_RATE_HIGH, severity)
            )
            await self.publish_alert(alert)
        
        # Latency Alert
        if metrics["avg_latency_ms"] > LATENCY_THRESHOLD_MS:
            severity = self.determine_severity(metrics["avg_latency_ms"], LATENCY_THRESHOLD_MS, "latency")
            alert = NerveAlert(
                timestamp=timestamp,
                service=SERVICE_NAME,
                pod=POD_NAME,
                namespace=POD_NAMESPACE,
                node=NODE_NAME,
                alert_type=AlertType.LATENCY_HIGH.value,
                severity=severity.value,
                message=f"Average latency at {metrics['avg_latency_ms']:.0f}ms (threshold: {LATENCY_THRESHOLD_MS}ms)",
                metric_value=metrics["avg_latency_ms"],
                threshold=LATENCY_THRESHOLD_MS,
                recommend_action=self.recommend_action(AlertType.LATENCY_HIGH, severity)
            )
            await self.publish_alert(alert)
        
        # Health Check Alert
        if not health_ok:
            self.consecutive_failures += 1
            
            if self.consecutive_failures >= 3:
                severity = AlertSeverity.EMERGENCY if self.consecutive_failures >= 5 else AlertSeverity.CRITICAL
                alert = NerveAlert(
                    timestamp=timestamp,
                    service=SERVICE_NAME,
                    pod=POD_NAME,
                    namespace=POD_NAMESPACE,
                    node=NODE_NAME,
                    alert_type=AlertType.HEALTH_CHECK_FAILED.value,
                    severity=severity.value,
                    message=f"Health check failed {self.consecutive_failures} times: {health_status}",
                    metric_value=float(self.consecutive_failures),
                    threshold=3.0,
                    recommend_action=self.recommend_action(AlertType.HEALTH_CHECK_FAILED, severity)
                )
                await self.publish_alert(alert)
        else:
            self.consecutive_failures = 0
    
    async def run(self):
        """Main monitoring loop"""
        await self.connect()
        self.running = True
        
        print(f"[NerveEnding:{POD_NAME}] Started monitoring {SERVICE_NAME}")
        print(f"[NerveEnding:{POD_NAME}] Thresholds - CPU: {CPU_THRESHOLD}%, Memory: {MEMORY_THRESHOLD}%, Error Rate: {ERROR_RATE_THRESHOLD*100}%, Latency: {LATENCY_THRESHOLD_MS}ms")
        
        while self.running:
            try:
                # Check health
                health_ok, health_status = await self.check_health()
                
                # Fetch and parse metrics
                metrics_text = await self.fetch_metrics()
                
                if metrics_text:
                    parsed = self.parse_prometheus_metrics(metrics_text)
                    metrics = self.extract_service_metrics(parsed)
                else:
                    # Use fallback metrics if we can't fetch
                    metrics = {
                        "cpu_percent": 0.0,
                        "memory_percent": 0.0,
                        "request_count": 0,
                        "error_count": 0,
                        "error_rate": 0.0,
                        "avg_latency_ms": 0.0
                    }
                
                # Create snapshot
                snapshot = MetricSnapshot(
                    timestamp=datetime.utcnow().isoformat(),
                    service=SERVICE_NAME,
                    pod=POD_NAME,
                    namespace=POD_NAMESPACE,
                    node=NODE_NAME,
                    cpu_percent=metrics["cpu_percent"],
                    memory_percent=metrics["memory_percent"],
                    request_count=metrics["request_count"],
                    error_count=metrics["error_count"],
                    error_rate=metrics["error_rate"],
                    avg_latency_ms=metrics["avg_latency_ms"],
                    health_status=health_status if health_ok else "unhealthy"
                )
                
                # Publish telemetry
                await self.publish_telemetry(snapshot)
                
                # Analyze and alert
                await self.analyze_and_alert(metrics, health_ok, health_status)
                
                # Store in history
                self.metrics_history.append(snapshot)
                if len(self.metrics_history) > 100:
                    self.metrics_history.pop(0)
                
            except Exception as e:
                print(f"[NerveEnding:{POD_NAME}] Error in monitoring loop: {e}")
            
            await asyncio.sleep(POLL_INTERVAL)
        
        await self.disconnect()

async def main():
    nerve = NerveEnding()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(nerve.disconnect()))
    
    await nerve.run()

if __name__ == "__main__":
    asyncio.run(main())
