"""
DARWIN Istio Service Mesh Client (§10)

Handles:
1. Traffic splitting to honeypot (80/20 VirtualService weights)
2. Traffic rerouting during recovery (DestinationRule failover)
3. Latency injection — replaces tc netem privileged pods entirely
4. Circuit breaking (DestinationRule outlier detection)

All network attacks use Istio VirtualService objects instead of privileged containers.
"""

import os
import json
import time
import subprocess
import tempfile
import logging
from typing import Optional

import yaml

logging.basicConfig(level=logging.INFO, format="[ISTIO] %(message)s")
log = logging.getLogger("istio_client")


class IstioClient:
    """Runtime interface for Istio service mesh operations."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    async def _kubectl_apply(self, manifest: dict):
        """Apply a manifest via kubectl."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(manifest, f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["kubectl", "apply", "-f", tmp_path, "-n", self.namespace],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                log.error(f"kubectl apply failed: {result.stderr}")
            else:
                log.info(f"Applied: {manifest['metadata']['name']}")
        except subprocess.TimeoutExpired:
            log.error("kubectl apply timed out")
        except FileNotFoundError:
            log.warning("kubectl not found — running in simulation mode")
        finally:
            os.unlink(tmp_path)

    async def _kubectl_delete(self, resource_type: str, name: str):
        """Delete a resource via kubectl."""
        try:
            subprocess.run(
                ["kubectl", "delete", resource_type, name,
                 "-n", self.namespace, "--ignore-not-found"],
                capture_output=True, text=True, timeout=30
            )
            log.info(f"Deleted: {resource_type}/{name}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # ───────────────────────────────────────────────────────────
    # HONEYPOT TRAFFIC SPLITTING
    # ───────────────────────────────────────────────────────────

    async def split_traffic_to_honeypot(self, service: str, honeypot_weight: int = 20):
        """Redirect a percentage of traffic to honeypot pod via VirtualService.
        Used in §7 Honeypot System."""
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"{service}-honeypot-split"},
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

        dr_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "DestinationRule",
            "metadata": {"name": f"{service}-honeypot-dr"},
            "spec": {
                "host": service,
                "subsets": [
                    {
                        "name": "real",
                        "labels": {"role": "production"},
                    },
                    {
                        "name": "honeypot",
                        "labels": {"role": "honeypot"},
                    },
                ],
            },
        }

        await self._kubectl_apply(dr_manifest)
        await self._kubectl_apply(vs_manifest)
        log.info(f"🍯 Traffic split {100-honeypot_weight}/{honeypot_weight} for {service}")

    async def remove_honeypot_split(self, service: str):
        """Remove honeypot traffic split."""
        await self._kubectl_delete("virtualservice", f"{service}-honeypot-split")
        await self._kubectl_delete("destinationrule", f"{service}-honeypot-dr")

    # ───────────────────────────────────────────────────────────
    # LATENCY INJECTION (Network Attacks via Istio)
    # ───────────────────────────────────────────────────────────

    async def inject_latency(self, service: str, delay_ms: int,
                              percentage: int = 100):
        """Inject fixed latency delay via Istio fault injection.
        Replaces tc netem privileged pods entirely (§10)."""
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"chaos-latency-{service}"},
            "spec": {
                "hosts": [service],
                "http": [{
                    "fault": {
                        "delay": {
                            "percentage": {"value": percentage},
                            "fixedDelay": f"{delay_ms}ms",
                        }
                    },
                    "route": [{"destination": {"host": service}}],
                }],
            },
        }
        await self._kubectl_apply(vs_manifest)
        log.info(f"⏱️ Injected {delay_ms}ms latency on {service} ({percentage}%)")

    async def inject_packet_loss(self, service: str, loss_pct: int = 30,
                                  delay_ms: int = 500):
        """Combined packet loss + latency injection."""
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"chaos-network-{service}"},
            "spec": {
                "hosts": [service],
                "http": [{
                    "fault": {
                        "delay": {
                            "percentage": {"value": 100},
                            "fixedDelay": f"{delay_ms}ms",
                        },
                        "abort": {
                            "percentage": {"value": loss_pct},
                            "httpStatus": 503,
                        },
                    },
                    "route": [{"destination": {"host": service}}],
                }],
            },
        }
        await self._kubectl_apply(vs_manifest)
        log.info(f"📡 Injected {loss_pct}% packet loss + {delay_ms}ms on {service}")

    async def inject_network_partition(self, services: list[str]):
        """Network partition — isolate services from each other.
        Extreme latency = effective partition (§9 network_D)."""
        for service in services:
            await self.inject_latency(service, delay_ms=99999, percentage=100)
        log.info(f"🔇 Network partition: {services}")

    # ───────────────────────────────────────────────────────────
    # CIRCUIT BREAKING
    # ───────────────────────────────────────────────────────────

    async def enable_circuit_breaker(self, service: str,
                                      max_connections: int = 100,
                                      max_pending: int = 50,
                                      consecutive_errors: int = 5):
        """Enable circuit breaking via DestinationRule outlier detection."""
        dr_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "DestinationRule",
            "metadata": {"name": f"circuit-breaker-{service}"},
            "spec": {
                "host": service,
                "trafficPolicy": {
                    "connectionPool": {
                        "tcp": {"maxConnections": max_connections},
                        "http": {
                            "h2UpgradePolicy": "DEFAULT",
                            "http1MaxPendingRequests": max_pending,
                            "http2MaxRequests": max_connections,
                        },
                    },
                    "outlierDetection": {
                        "consecutive5xxErrors": consecutive_errors,
                        "interval": "10s",
                        "baseEjectionTime": "30s",
                        "maxEjectionPercent": 50,
                    },
                },
            },
        }
        await self._kubectl_apply(dr_manifest)
        log.info(f"🔌 Circuit breaker enabled on {service}")

    # ───────────────────────────────────────────────────────────
    # FAILOVER ROUTING (Recovery)
    # ───────────────────────────────────────────────────────────

    async def setup_failover_route(self, service: str, backup_service: str):
        """Route traffic to backup service during recovery."""
        vs_manifest = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"failover-{service}"},
            "spec": {
                "hosts": [service],
                "http": [{
                    "route": [
                        {
                            "destination": {"host": service},
                            "weight": 0,
                        },
                        {
                            "destination": {"host": backup_service},
                            "weight": 100,
                        },
                    ],
                }],
            },
        }
        await self._kubectl_apply(vs_manifest)
        log.info(f"🔀 Failover route: {service} → {backup_service}")

    # ───────────────────────────────────────────────────────────
    # CLEANUP
    # ───────────────────────────────────────────────────────────

    async def remove_chaos(self, service: str):
        """Remove all chaos-related Istio resources for a service."""
        await self._kubectl_delete("virtualservice", f"chaos-latency-{service}")
        await self._kubectl_delete("virtualservice", f"chaos-network-{service}")
        await self._kubectl_delete("virtualservice", f"{service}-honeypot-split")
        await self._kubectl_delete("virtualservice", f"failover-{service}")
        await self._kubectl_delete("destinationrule", f"{service}-honeypot-dr")
        await self._kubectl_delete("destinationrule", f"circuit-breaker-{service}")
        log.info(f"🧹 Cleaned all chaos resources for {service}")

    async def remove_all_chaos(self):
        """Nuclear cleanup — remove all chaos resources."""
        try:
            subprocess.run(
                ["kubectl", "delete", "virtualservice", "-l", "chaos=true",
                 "-n", self.namespace, "--ignore-not-found"],
                capture_output=True, text=True
            )
        except FileNotFoundError:
            pass
        log.info("🧹 All chaos resources cleaned")
