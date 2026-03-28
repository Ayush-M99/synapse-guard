"""
DARWIN Virus Agent — Complete 18-Strand Attack Library
5 Families: pod_crash (4), network (4), resource (4), timing (3), camouflage (3)

All attacks use:
  - kubernetes Python SDK for pod/deployment operations
  - IstioClient for network fault injection
  - NATS publishing of virus.inject events
"""

import asyncio
import json
import logging
import os
import random
import subprocess
import tempfile
import time
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

NAMESPACE = os.getenv("PATIENT_NAMESPACE", "patient")


# ─── Helper: safe subprocess ──────────────────────────────────────────────────

def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=check)
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out: {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 1, "", "timeout")
    except Exception as e:
        logger.error(f"Command error: {e}")
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def _kubectl(*args) -> subprocess.CompletedProcess:
    return _run(["kubectl", *args])


# ─── Family 1: Pod Crash ──────────────────────────────────────────────────────

async def pod_crash_A(service: str, nc=None) -> dict:
    """Single OOMKill — delete pod with grace_period=0."""
    logger.warning(f"🦠 [pod_crash_A] Killing {service} pod in namespace {NAMESPACE}")
    pods = _kubectl("get", "pods", "-n", NAMESPACE,
                    "-l", f"app={service}", "-o", "jsonpath={.items[0].metadata.name}")
    pod_name = pods.stdout.strip()
    if pod_name:
        _kubectl("delete", "pod", pod_name, "-n", NAMESPACE,
                 "--grace-period=0", "--force")
    result = {"strand": "pod_crash_A", "service": service, "pod": pod_name}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def pod_crash_B(service: str, nc=None) -> dict:
    """Cascade crash: kill service then downstream after 3s delay."""
    DOWNSTREAM = {
        "payment-service": "order-service",
        "api-gateway":     "auth-service",
        "order-service":   "inventory-service",
    }
    await pod_crash_A(service, nc)
    downstream = DOWNSTREAM.get(service, "notification-service")
    await asyncio.sleep(3)
    await pod_crash_A(downstream, nc)
    result = {"strand": "pod_crash_B", "service": service, "downstream": downstream}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def pod_crash_C(service: str, nc=None) -> dict:
    """Kill under load — spike 500 rps for 10s then kill."""
    logger.warning(f"🦠 [pod_crash_C] Kill under load: {service}")
    # Stress the service with rapid curl calls for 10s
    svc_port = _get_service_port(service)
    if svc_port:
        stress_proc = subprocess.Popen([
            "kubectl", "run", "load-stressor", "--rm", "-it",
            "--image=busybox", "-n", NAMESPACE,
            "--restart=Never", "--",
            "sh", "-c",
            f"for i in $(seq 1 200); do wget -q -O /dev/null http://{service}:{svc_port}/process & done; wait"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(10)
        stress_proc.terminate()
    await pod_crash_A(service, nc)
    result = {"strand": "pod_crash_C", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def pod_crash_D(service: str, nc=None) -> dict:
    """Kill + corrupt ConfigMap (set DB_HOST to invalid)."""
    logger.warning(f"🦠 [pod_crash_D] ConfigMap corruption: {service}")
    _kubectl("patch", "configmap", f"{service}-config", "-n", NAMESPACE,
             "--type=merge", "-p", '{"data":{"DB_HOST":"invalid-host-darwin-chaos"}}')
    await asyncio.sleep(1)
    await pod_crash_A(service, nc)
    result = {"strand": "pod_crash_D", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def cleanup_pod_crash_D(service: str):
    """Restore ConfigMap after pod_crash_D."""
    _kubectl("patch", "configmap", f"{service}-config", "-n", NAMESPACE,
             "--type=merge", "-p", '{"data":{"DB_HOST":"postgres"}}')


# ─── Family 2: Network Attacks ────────────────────────────────────────────────

async def network_A(service: str, nc=None) -> dict:
    """Inject 2000ms fixed latency via Istio VirtualService."""
    from .istio_client import IstioClient
    istio = IstioClient()
    await istio.inject_latency(service, delay_ms=2000)
    result = {"strand": "network_A", "service": service, "latency_ms": 2000}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def network_B(service: str, nc=None) -> dict:
    """Packet loss 30% + 500ms latency combined."""
    from .istio_client import IstioClient
    istio = IstioClient()
    await istio.inject_fault(service, delay_ms=500, abort_pct=30, abort_code=503)
    result = {"strand": "network_B", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def network_C(service: str, nc=None) -> dict:
    """DNS poisoning simulation — extreme latency (10s) on service discovery."""
    from .istio_client import IstioClient
    istio = IstioClient()
    await istio.inject_latency(service, delay_ms=10000, pct=100)
    result = {"strand": "network_C", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def network_D(services: list[str], nc=None) -> dict:
    """Network partition — isolate services by injecting 99999ms latency."""
    from .istio_client import IstioClient
    istio = IstioClient()
    for svc in services:
        await istio.inject_latency(svc, delay_ms=99999, pct=100)
    result = {"strand": "network_D", "partitioned": services}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def cleanup_network(service: str):
    from .istio_client import IstioClient
    await IstioClient().remove_chaos(service)


# ─── Family 3: Resource Pressure ─────────────────────────────────────────────

async def resource_A(service: str, nc=None) -> dict:
    """Deploy stress pod on same node — CPU hog (2 cores, 60s)."""
    logger.warning(f"🦠 [resource_A] CPU stress on node hosting {service}")
    node = _get_service_node(service)
    stress_pod = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": f"darwin-stress-cpu-{int(time.time())}", "namespace": NAMESPACE},
        "spec": {
            "nodeName": node,
            "containers": [{
                "name": "stress",
                "image": "polinux/stress:latest",
                "args": ["stress", "--cpu", "2", "--timeout", "60s"],
                "resources": {
                    "requests": {"cpu": "1500m", "memory": "64Mi"},
                    "limits":   {"cpu": "2000m", "memory": "128Mi"},
                },
            }],
            "restartPolicy": "Never",
        },
    }
    await _kubectl_apply(stress_pod)
    result = {"strand": "resource_A", "service": service, "node": node}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def resource_B(service: str, nc=None) -> dict:
    """Memory leak simulation — vm stress."""
    node = _get_service_node(service)
    stress_pod = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": f"darwin-stress-mem-{int(time.time())}", "namespace": NAMESPACE},
        "spec": {
            "nodeName": node,
            "containers": [{
                "name": "stress",
                "image": "polinux/stress:latest",
                "args": ["stress", "--vm", "1", "--vm-bytes", "200M", "--vm-hang", "0"],
                "resources": {
                    "requests": {"cpu": "100m", "memory": "256Mi"},
                    "limits":   {"cpu": "200m", "memory": "400Mi"},
                },
            }],
            "restartPolicy": "Never",
        },
    }
    await _kubectl_apply(stress_pod)
    result = {"strand": "resource_B", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def resource_C(service: str, nc=None) -> dict:
    """Disk fill — write to /tmp until 95% full."""
    node = _get_service_node(service)
    fill_pod = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": f"darwin-diskfill-{int(time.time())}", "namespace": NAMESPACE},
        "spec": {
            "nodeName": node,
            "containers": [{
                "name": "diskfill",
                "image": "busybox:latest",
                "command": ["sh", "-c", "dd if=/dev/urandom of=/tmp/fill bs=10M count=500"],
            }],
            "restartPolicy": "Never",
        },
    }
    await _kubectl_apply(fill_pod)
    result = {"strand": "resource_C", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def resource_D(service: str, nc=None) -> dict:
    """Combo — CPU + memory + disk simultaneously."""
    await asyncio.gather(
        resource_A(service),
        resource_B(service),
        resource_C(service),
    )
    result = {"strand": "resource_D", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 1}).encode())
    return result


async def cleanup_stress_pods():
    _kubectl("delete", "pods", "-n", NAMESPACE,
             "-l", "app=darwin-stress", "--ignore-not-found")
    # Also clean up by name pattern
    pods_out = _kubectl("get", "pods", "-n", NAMESPACE, "-o", "name")
    for pod in pods_out.stdout.splitlines():
        if "darwin-stress" in pod or "darwin-diskfill" in pod:
            _kubectl("delete", pod, "-n", NAMESPACE, "--ignore-not-found")


# ─── Family 4: Timing Attacks ─────────────────────────────────────────────────

async def timing_A(service: str, nc, recovery_event_source) -> dict:
    """
    Watch antibody recovery state. Strike at 50% recovery midpoint.
    recovery_event_source: async callable that returns health score 0→1
    """
    logger.warning(f"🦠 [timing_A] Waiting for recovery midpoint of {service}")
    timeout = time.time() + 60   # give up after 60s
    while time.time() < timeout:
        score = await recovery_event_source(service)
        if 0.4 <= score <= 0.6:
            logger.warning(f"🦠 [timing_A] Recovery midpoint detected! Striking {service}")
            await pod_crash_A(service, nc)
            break
        await asyncio.sleep(1)
    result = {"strand": "timing_A", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 2}).encode())
    return result


async def timing_B(service: str, nc=None) -> dict:
    """Watch failover route — attack the failover target instead."""
    FAILOVER_TARGETS = {
        "payment-service": "order-service",
        "api-gateway":     "auth-service",
        "order-service":   "inventory-service",
    }
    target = FAILOVER_TARGETS.get(service, "notification-service")
    logger.warning(f"🦠 [timing_B] Attacking failover target: {target}")
    await asyncio.sleep(5)   # wait for failover to establish
    await pod_crash_A(target, nc)
    result = {"strand": "timing_B", "service": service, "target": target}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 2}).encode())
    return result


async def timing_C(service: str, nc=None) -> dict:
    """Blind monitoring first — attack notification-service (metrics agent), then real target."""
    logger.warning(f"🦠 [timing_C] Blinding monitoring first...")
    await pod_crash_A("notification-service", nc)
    await asyncio.sleep(8)   # let detection be impaired
    await pod_crash_A(service, nc)
    result = {"strand": "timing_C", "service": service}
    if nc:
        await nc.publish("virus.inject", json.dumps({**result, "generation": 2}).encode())
    return result


# ─── Family 5: Camouflage Attacks ────────────────────────────────────────────

async def camouflage_A(service: str, nc=None) -> dict:
    """
    Slow burn — degrade CPU limits 2% every 5 minutes.
    Stays under IF threshold each step. Only CUSUM catches it.
    """
    logger.warning(f"🦠 [camouflage_A] Starting slow burn on {service}")
    degradation_pct  = 0.02
    current_cpu_limit = 1000    # millicores
    max_rounds        = 10      # max 10 rounds ≈ 50 minutes
    for _ in range(max_rounds):
        current_cpu_limit = int(current_cpu_limit * (1 - degradation_pct))
        patch = json.dumps({
            "spec": {"template": {"spec": {"containers": [{
                "name":      service,
                "resources": {"limits": {"cpu": f"{current_cpu_limit}m"}}
            }]}}}
        })
        _kubectl("patch", "deployment", service, "-n", NAMESPACE,
                 "--type=merge", "-p", patch)
        logger.info(f"  camouflage_A: {service} CPU limit → {current_cpu_limit}m")
        if nc:
            await nc.publish("virus.inject", json.dumps({
                "strand": "camouflage_A", "service": service,
                "cpu_limit_m": current_cpu_limit, "generation": 3,
            }).encode())
        await asyncio.sleep(300)   # 5 minutes between steps


async def camouflage_B(service: str, nc=None) -> dict:
    """Gradually increase Istio latency from 100ms to 3000ms over 10 minutes."""
    from .istio_client import IstioClient
    istio = IstioClient()
    steps = 10
    for i in range(steps + 1):
        delay_ms = int(100 + (3000 - 100) * i / steps)
        await istio.inject_latency(service, delay_ms=delay_ms, pct=100)
        logger.info(f"  camouflage_B: {service} latency → {delay_ms}ms")
        if nc:
            await nc.publish("virus.inject", json.dumps({
                "strand": "camouflage_B", "service": service,
                "latency_ms": delay_ms, "generation": 3,
            }).encode())
        await asyncio.sleep(60)   # 1 minute per step
    return {"strand": "camouflage_B", "service": service}


async def camouflage_C(service: str, nc=None) -> dict:
    """Attack monitoring service first to blind antibody, then real target."""
    logger.warning(f"🦠 [camouflage_C] Monkey-wrenching monitoring for {service}")
    # Inject latency on notification-service (metrics proxy)
    from .istio_client import IstioClient
    istio = IstioClient()
    await istio.inject_latency("notification-service", delay_ms=5000, pct=100)
    await asyncio.sleep(30)
    # Now attack the real target
    await pod_crash_A(service, nc)
    return {"strand": "camouflage_C", "service": service}


# ─── Utility helpers ──────────────────────────────────────────────────────────

def _get_service_node(service: str) -> Optional[str]:
    result = _kubectl(
        "get", "pods", "-n", NAMESPACE,
        "-l", f"app={service}",
        "-o", "jsonpath={.items[0].spec.nodeName}"
    )
    return result.stdout.strip() or None


def _get_service_port(service: str) -> Optional[str]:
    PORTS = {
        "auth-service":         "8000",
        "api-gateway":          "8000",
        "order-service":        "8000",
        "payment-service":      "8000",
        "inventory-service":    "8000",
        "notification-service": "8000",
    }
    return PORTS.get(service)


async def _kubectl_apply(manifest: dict):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.dump(manifest, f)
        fname = f.name
    _run(["kubectl", "apply", "-f", fname])
    os.unlink(fname)


# ─── Attack dispatch table ────────────────────────────────────────────────────

ATTACK_REGISTRY = {
    "pod_crash_A":  pod_crash_A,
    "pod_crash_B":  pod_crash_B,
    "pod_crash_C":  pod_crash_C,
    "pod_crash_D":  pod_crash_D,
    "network_A":    network_A,
    "network_B":    network_B,
    "network_C":    network_C,
    "resource_A":   resource_A,
    "resource_B":   resource_B,
    "resource_C":   resource_C,
    "resource_D":   resource_D,
    "timing_B":     timing_B,
    "timing_C":     timing_C,
    "camouflage_B": camouflage_B,
    "camouflage_C": camouflage_C,
}


async def dispatch(strand_id: str, service: str, nc=None, **kwargs) -> dict:
    """Execute any attack strand by ID."""
    fn = ATTACK_REGISTRY.get(strand_id)
    if fn is None:
        logger.error(f"Unknown strand: {strand_id}")
        return {"error": f"unknown strand {strand_id}"}
    try:
        return await fn(service, nc, **kwargs)
    except Exception as e:
        logger.error(f"Attack {strand_id} failed: {e}")
        return {"strand": strand_id, "service": service, "error": str(e)}
