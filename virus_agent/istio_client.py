"""
Istio VirtualService Client
Manages chaos fault injection via Istio networking objects.
No privileged containers — uses Istio API instead of tc/netem.
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile

import yaml

logger = logging.getLogger(__name__)

NAMESPACE = os.getenv("PATIENT_NAMESPACE", "patient")


class IstioClient:
    """
    Manages Istio VirtualService objects for:
      - Latency injection (fixed delay on % of traffic)
      - Abort injection (HTTP 503 on % of traffic)
      - Traffic splitting to honeypot (80/20 weight)
      - Cleanup (delete VirtualService)
    """

    async def inject_latency(self, service: str, delay_ms: int, pct: int = 100) -> dict:
        """Inject fixed latency on pct% of traffic to service."""
        manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {
                "name": f"darwin-chaos-latency-{service}",
                "namespace": NAMESPACE,
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "fault": {
                        "delay": {
                            "percentage": {"value": float(pct)},
                            "fixedDelay": f"{delay_ms}ms",
                        }
                    },
                    "route": [{"destination": {"host": service}}],
                }],
            },
        }
        await self._kubectl_apply(manifest)
        logger.info(f"🌐 Istio latency: {service} +{delay_ms}ms ({pct}%)")
        return {"action": "inject_latency", "service": service,
                "delay_ms": delay_ms, "pct": pct}

    async def inject_fault(self, service: str, delay_ms: int = 500,
                           abort_pct: int = 30, abort_code: int = 503) -> dict:
        """Inject combined delay + HTTP abort fault."""
        manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {
                "name": f"darwin-chaos-fault-{service}",
                "namespace": NAMESPACE,
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "fault": {
                        "delay": {
                            "percentage": {"value": 100.0},
                            "fixedDelay": f"{delay_ms}ms",
                        },
                        "abort": {
                            "percentage": {"value": float(abort_pct)},
                            "httpStatus": abort_code,
                        },
                    },
                    "route": [{"destination": {"host": service}}],
                }],
            },
        }
        await self._kubectl_apply(manifest)
        logger.info(f"🌐 Istio fault: {service} delay={delay_ms}ms abort={abort_pct}%@{abort_code}")
        return {"action": "inject_fault", "service": service}

    async def split_traffic_to_honeypot(
        self, service: str, honeypot_weight: int = 20
    ) -> dict:
        """80/20 traffic split between real service and honeypot pod."""
        manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {
                "name": f"{service}-honeypot-split",
                "namespace": NAMESPACE,
            },
            "spec": {
                "hosts": [service],
                "http": [{
                    "route": [
                        {
                            "destination": {"host": service, "subset": "real"},
                            "weight": 100 - honeypot_weight,
                        },
                        {
                            "destination": {"host": service, "subset": "honeypot"},
                            "weight": honeypot_weight,
                        },
                    ]
                }],
            },
        }
        await self._kubectl_apply(manifest)
        logger.info(f"🪝 Istio split: {service} real={100-honeypot_weight}% honeypot={honeypot_weight}%")
        return {"action": "split_traffic", "service": service,
                "honeypot_weight": honeypot_weight}

    async def restore_circuit_breaker(self, service: str, max_connections: int = 1) -> dict:
        """Apply DestinationRule outlier detection for circuit breaking during recovery."""
        manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "DestinationRule",
            "metadata": {
                "name": f"darwin-cb-{service}",
                "namespace": NAMESPACE,
            },
            "spec": {
                "host": service,
                "trafficPolicy": {
                    "connectionPool": {
                        "tcp": {"maxConnections": max_connections},
                    },
                    "outlierDetection": {
                        "consecutive5xxErrors": 3,
                        "interval": "10s",
                        "baseEjectionTime": "30s",
                        "maxEjectionPercent": 100,
                    },
                },
            },
        }
        await self._kubectl_apply(manifest)
        logger.info(f"⚡ Circuit breaker applied to {service}")
        return {"action": "circuit_breaker", "service": service}

    async def remove_chaos(self, service: str) -> dict:
        """Remove all chaos VirtualServices for a service."""
        names = [
            f"darwin-chaos-latency-{service}",
            f"darwin-chaos-fault-{service}",
            f"{service}-honeypot-split",
        ]
        for name in names:
            subprocess.run(
                ["kubectl", "delete", "virtualservice", name,
                 "-n", NAMESPACE, "--ignore-not-found"],
                capture_output=True
            )
        # Remove circuit breaker DestinationRule too
        subprocess.run(
            ["kubectl", "delete", "destinationrule", f"darwin-cb-{service}",
             "-n", NAMESPACE, "--ignore-not-found"],
            capture_output=True
        )
        logger.info(f"🧹 Chaos removed for {service}")
        return {"action": "cleanup", "service": service}

    async def _kubectl_apply(self, manifest: dict):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(manifest, f)
            fname = f.name
        proc = subprocess.run(
            ["kubectl", "apply", "-f", fname],
            capture_output=True, text=True
        )
        import os
        os.unlink(fname)
        if proc.returncode != 0:
            logger.error(f"kubectl apply failed: {proc.stderr}")
        return proc.returncode == 0
