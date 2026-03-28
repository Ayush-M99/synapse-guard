"""
DARWIN Chaos Engine
Injects faults into the patient Kubernetes workload.
Uses the real K8s client — no mocks.

Fault types:
  pod_crash   → delete pod (K8s restarts it via Deployment controller)
  cpu_stress  → deploy stress pod on same node
  memory_hog  → deploy memory stress pod
  network     → annotate pod for Istio fault injection (if Istio available)
  scale_down  → temporarily scale deployment to 0 replicas
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from . import k8s_client as k8s
from . import redis_client as redis_store

logger = logging.getLogger(__name__)

PATIENT_NS = os.getenv("PATIENT_NAMESPACE", "patient")

VALID_SERVICES = [
    "auth-service",
    "api-gateway",
    "order-service",
    "payment-service",
    "inventory-service",
    "notification-service",
]

VALID_FAULT_TYPES = [
    "pod_crash",
    "scale_down",
    "cpu_stress",
    "memory_hog",
    "network_latency",
]


class FaultInjectionResult:
    def __init__(self, fault_id: str, fault_type: str, service: str,
                 success: bool, details: dict = None):
        self.fault_id   = fault_id
        self.fault_type = fault_type
        self.service    = service
        self.success    = success
        self.details    = details or {}
        self.timestamp  = time.time()

    def to_dict(self) -> dict:
        return {
            "fault_id":   self.fault_id,
            "fault_type": self.fault_type,
            "service":    self.service,
            "success":    self.success,
            "details":    self.details,
            "timestamp":  self.timestamp,
        }


class ChaosEngine:
    """
    Injects controlled failures into the patient Kubernetes workload.
    All operations use the real kubernetes Python SDK.
    Results are logged to Redis for recovery engine + dashboard.
    """

    def __init__(self):
        self._active_faults: dict[str, dict] = {}   # fault_id → fault info

    # ─── Primary API ─────────────────────────────────────────────────────────

    def inject_fault(
        self,
        service: str,
        fault_type: str = "pod_crash",
        duration_seconds: int = 0,
        params: dict = None,
    ) -> FaultInjectionResult:
        """
        Inject a fault. Main entry point called by the FastAPI endpoint.
        Returns FaultInjectionResult immediately (fault is applied synchronously).
        """
        fault_id = str(uuid.uuid4())[:8]
        params   = params or {}

        if service not in VALID_SERVICES:
            return FaultInjectionResult(
                fault_id, fault_type, service, False,
                {"error": f"Unknown service '{service}'. Valid: {VALID_SERVICES}"}
            )

        if fault_type not in VALID_FAULT_TYPES:
            return FaultInjectionResult(
                fault_id, fault_type, service, False,
                {"error": f"Unknown fault type '{fault_type}'. Valid: {VALID_FAULT_TYPES}"}
            )

        logger.warning(f"🦠 [ChaosEngine] Injecting {fault_type} → {service} (id={fault_id})")

        handler = {
            "pod_crash":       self._inject_pod_crash,
            "scale_down":      self._inject_scale_down,
            "cpu_stress":      self._inject_cpu_stress,
            "memory_hog":      self._inject_memory_hog,
            "network_latency": self._inject_network_latency,
        }[fault_type]

        result = handler(service, fault_id, params)

        # Record in Redis
        redis_store.set_key(
            f"fault:{fault_id}",
            {**result.to_dict(), "duration": duration_seconds},
            ttl=3600,
        )
        redis_store.log_anomaly(
            service=service,
            anomaly_score=0.9,
            rf_label=_fault_to_attack_family(fault_type),
            rf_confidence=1.0,
            attack_state="KNOWN",
            strand_id=f"{fault_type}_{fault_id}",
        )

        # Track active fault
        if result.success:
            self._active_faults[fault_id] = result.to_dict()

        return result

    def list_active_faults(self) -> list[dict]:
        return list(self._active_faults.values())

    def clear_fault(self, fault_id: str):
        self._active_faults.pop(fault_id, None)

    # ─── Fault implementations ────────────────────────────────────────────────

    def _inject_pod_crash(self, service: str, fault_id: str, params: dict) -> FaultInjectionResult:
        """Delete pod — Deployment controller will restart it."""
        result = k8s.delete_pod_by_label(
            label_selector=f"app={service}",
            namespace=PATIENT_NS,
        )
        return FaultInjectionResult(
            fault_id, "pod_crash", service,
            result["success"],
            {**result, "method": "delete_pod"},
        )

    def _inject_scale_down(self, service: str, fault_id: str, params: dict) -> FaultInjectionResult:
        """Scale deployment to 0 replicas temporarily."""
        # Save current replica count for recovery
        status = k8s.get_deployment_status(service, PATIENT_NS)
        current = status["desired"] if status else 1
        redis_store.set_key(f"pre_fault_replicas:{service}", {"replicas": current})

        result = k8s.scale_deployment(service, replicas=0, namespace=PATIENT_NS)
        return FaultInjectionResult(
            fault_id, "scale_down", service,
            result["success"],
            {**result, "original_replicas": current},
        )

    def _inject_cpu_stress(self, service: str, fault_id: str, params: dict) -> FaultInjectionResult:
        """
        Deploy a stress pod on the cluster to compete for CPU.
        Uses busybox with a tight loop (no external image required).
        """
        from kubernetes import client as kclient, config as kconfig
        try:
            kconfig.load_kube_config()
            core = kclient.CoreV1Api()
            duration = params.get("duration_seconds", 60)
            pod_name = f"darwin-stress-{fault_id}"
            pod = kclient.V1Pod(
                metadata=kclient.V1ObjectMeta(
                    name=pod_name,
                    namespace=PATIENT_NS,
                    labels={"darwin-stress": "true"},
                ),
                spec=kclient.V1PodSpec(
                    restart_policy="Never",
                    containers=[kclient.V1Container(
                        name="stress",
                        image="busybox:1.36",
                        command=["sh", "-c", f"for i in $(seq 1 4); do yes > /dev/null & done; sleep {duration}; kill $(jobs -p)"],
                        resources=kclient.V1ResourceRequirements(
                            requests={"cpu": "500m", "memory": "64Mi"},
                            limits={"cpu": "1000m", "memory": "128Mi"},
                        ),
                    )],
                ),
            )
            core.create_namespaced_pod(namespace=PATIENT_NS, body=pod)
            logger.info(f"CPU stress pod created: {pod_name}")
            return FaultInjectionResult(
                fault_id, "cpu_stress", service, True,
                {"stress_pod": pod_name, "duration": duration},
            )
        except Exception as e:
            return FaultInjectionResult(fault_id, "cpu_stress", service, False, {"error": str(e)})

    def _inject_memory_hog(self, service: str, fault_id: str, params: dict) -> FaultInjectionResult:
        """Deploy a memory-consuming pod."""
        from kubernetes import client as kclient, config as kconfig
        try:
            kconfig.load_kube_config()
            core = kclient.CoreV1Api()
            mb  = params.get("memory_mb", 200)
            pod_name = f"darwin-memhog-{fault_id}"
            pod = kclient.V1Pod(
                metadata=kclient.V1ObjectMeta(
                    name=pod_name, namespace=PATIENT_NS,
                    labels={"darwin-stress": "true"},
                ),
                spec=kclient.V1PodSpec(
                    restart_policy="Never",
                    containers=[kclient.V1Container(
                        name="memhog",
                        image="busybox:1.36",
                        command=["sh", "-c", f"dd if=/dev/urandom bs=1M count={mb} | tail -c 1"],
                        resources=kclient.V1ResourceRequirements(
                            requests={"cpu": "50m", "memory": f"{mb+64}Mi"},
                            limits={"cpu": "100m", "memory": f"{mb+128}Mi"},
                        ),
                    )],
                ),
            )
            core.create_namespaced_pod(namespace=PATIENT_NS, body=pod)
            return FaultInjectionResult(
                fault_id, "memory_hog", service, True,
                {"stress_pod": pod_name, "memory_mb": mb},
            )
        except Exception as e:
            return FaultInjectionResult(fault_id, "memory_hog", service, False, {"error": str(e)})

    def _inject_network_latency(self, service: str, fault_id: str, params: dict) -> FaultInjectionResult:
        """
        Annotate pod for Istio fault injection via VirtualService.
        Falls back to logging-only if Istio is not available.
        """
        delay_ms = params.get("delay_ms", 2000)
        try:
            # Attempt Istio approach via subprocess kubectl
            import subprocess, tempfile, yaml
            manifest = {
                "apiVersion": "networking.istio.io/v1alpha3",
                "kind": "VirtualService",
                "metadata": {
                    "name":      f"darwin-chaos-{service}",
                    "namespace": PATIENT_NS,
                },
                "spec": {
                    "hosts": [service],
                    "http": [{
                        "fault": {
                            "delay": {
                                "percentage": {"value": 100.0},
                                "fixedDelay": f"{delay_ms}ms",
                            }
                        },
                        "route": [{"destination": {"host": service}}],
                    }],
                },
            }
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                yaml.dump(manifest, f)
                fname = f.name
            proc = subprocess.run(
                ["kubectl", "apply", "-f", fname],
                capture_output=True, text=True, timeout=10,
            )
            import os; os.unlink(fname)
            if proc.returncode == 0:
                return FaultInjectionResult(
                    fault_id, "network_latency", service, True,
                    {"delay_ms": delay_ms, "method": "istio_virtualservice"},
                )
            # Istio not available — log-only mode
            logger.warning(f"Istio not available ({proc.stderr.strip()}). Logging-only.")
            return FaultInjectionResult(
                fault_id, "network_latency", service, True,
                {"delay_ms": delay_ms, "method": "log_only", "note": "Istio not installed"},
            )
        except Exception as e:
            return FaultInjectionResult(fault_id, "network_latency", service, False, {"error": str(e)})


def _fault_to_attack_family(fault_type: str) -> str:
    return {
        "pod_crash":       "pod_crash",
        "scale_down":      "pod_crash",
        "cpu_stress":      "resource",
        "memory_hog":      "resource",
        "network_latency": "network",
    }.get(fault_type, "unknown")


# ─── Module-level singleton ───────────────────────────────────────────────────
engine = ChaosEngine()
