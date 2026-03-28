"""
DARWIN Control Plane — Kubernetes Client
Connects to the real cluster via in-cluster config or kubeconfig.
Namespace: darwin (and patient for the target app)
"""

import logging
import os
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

DARWIN_NS  = os.getenv("DARWIN_NAMESPACE",  "darwin")
PATIENT_NS = os.getenv("PATIENT_NAMESPACE", "patient")


def _load_kube_config():
    """Load kubectl config from kubeconfig (WSL / local dev)."""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster kubeconfig")
    except Exception:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig (~/.kube/config)")


_load_kube_config()

_core   = client.CoreV1Api()
_apps   = client.AppsV1Api()
_hpa    = client.AutoscalingV2Api()


# ─── Pod Operations ───────────────────────────────────────────────────────────

def list_pods(namespace: str = DARWIN_NS) -> list[dict]:
    """Return all pods in namespace with their status."""
    try:
        pods = _core.list_namespaced_pod(namespace=namespace)
        return [
            {
                "name":      p.metadata.name,
                "namespace": p.metadata.namespace,
                "phase":     p.status.phase,
                "ready":     _is_pod_ready(p),
                "restarts":  _get_restart_count(p),
                "node":      p.spec.node_name,
                "labels":    p.metadata.labels or {},
                "created":   p.metadata.creation_timestamp.isoformat()
                             if p.metadata.creation_timestamp else None,
            }
            for p in pods.items
        ]
    except ApiException as e:
        logger.error(f"list_pods error: {e}")
        return []


def get_pod(name: str, namespace: str = PATIENT_NS) -> Optional[dict]:
    """Get single pod by name."""
    try:
        p = _core.read_namespaced_pod(name=name, namespace=namespace)
        return {
            "name":      p.metadata.name,
            "phase":     p.status.phase,
            "ready":     _is_pod_ready(p),
            "restarts":  _get_restart_count(p),
            "node":      p.spec.node_name,
        }
    except ApiException:
        return None


def delete_pod(name: str, namespace: str = PATIENT_NS, grace_period: int = 0) -> dict:
    """
    Delete a pod (force if grace_period=0).
    K8s will restart it via the Deployment controller.
    This is the primary fault injection mechanism.
    """
    try:
        _core.delete_namespaced_pod(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=grace_period),
        )
        logger.warning(f"💀 Pod deleted: {name} (ns={namespace}, grace={grace_period}s)")
        return {"success": True, "action": "delete_pod", "pod": name, "namespace": namespace}
    except ApiException as e:
        logger.error(f"delete_pod error: {e.status} {e.reason}")
        return {"success": False, "error": e.reason, "pod": name}


def delete_pod_by_label(label_selector: str, namespace: str = PATIENT_NS) -> dict:
    """Delete first pod matching label selector — used by attack library."""
    try:
        pods = _core.list_namespaced_pod(
            namespace=namespace, label_selector=label_selector
        )
        if not pods.items:
            return {"success": False, "error": f"No pods matching {label_selector}"}
        target = pods.items[0].metadata.name
        return delete_pod(target, namespace)
    except ApiException as e:
        return {"success": False, "error": e.reason}


def restart_deployment(name: str, namespace: str = PATIENT_NS) -> dict:
    """
    Restart a deployment by patching its annotation (rolling restart).
    Safer than deleting individual pods — respects PodDisruptionBudget.
    """
    import datetime
    try:
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }
        _apps.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
        logger.info(f"♻️  Deployment restarted: {name}")
        return {"success": True, "action": "restart_deployment", "deployment": name}
    except ApiException as e:
        return {"success": False, "error": e.reason}


def scale_deployment(name: str, replicas: int, namespace: str = PATIENT_NS) -> dict:
    """Scale a deployment to specific replica count."""
    try:
        patch = {"spec": {"replicas": replicas}}
        _apps.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
        logger.info(f"📈 Scaled {name} → {replicas} replicas")
        return {"success": True, "action": "scale", "deployment": name, "replicas": replicas}
    except ApiException as e:
        return {"success": False, "error": e.reason, "deployment": name}


def get_deployment_status(name: str, namespace: str = PATIENT_NS) -> Optional[dict]:
    """Get deployment status including ready/desired replicas."""
    try:
        d = _apps.read_namespaced_deployment(name=name, namespace=namespace)
        return {
            "name":           name,
            "desired":        d.spec.replicas,
            "ready":          d.status.ready_replicas or 0,
            "available":      d.status.available_replicas or 0,
            "updated":        d.status.updated_replicas or 0,
        }
    except ApiException:
        return None


def list_deployments(namespace: str = PATIENT_NS) -> list[dict]:
    """List all deployments in namespace."""
    try:
        deploys = _apps.list_namespaced_deployment(namespace=namespace)
        return [
            {
                "name":      d.metadata.name,
                "desired":   d.spec.replicas,
                "ready":     d.status.ready_replicas or 0,
                "available": d.status.available_replicas or 0,
            }
            for d in deploys.items
        ]
    except ApiException as e:
        logger.error(f"list_deployments: {e}")
        return []


def patch_resource_limits(
    deployment: str, container: str,
    cpu_limit: str, mem_limit: str,
    namespace: str = PATIENT_NS
) -> dict:
    """Patch CPU/memory limits on a container (e.g. for camouflage attack simulation)."""
    patch = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": container,
                        "resources": {"limits": {"cpu": cpu_limit, "memory": mem_limit}}
                    }]
                }
            }
        }
    }
    try:
        _apps.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
        return {"success": True, "cpu_limit": cpu_limit, "mem_limit": mem_limit}
    except ApiException as e:
        return {"success": False, "error": e.reason}


# ─── Namespace helpers ────────────────────────────────────────────────────────

def ensure_namespace(name: str) -> bool:
    """Create namespace if it doesn't exist."""
    try:
        _core.read_namespace(name)
        return True
    except ApiException:
        pass
    try:
        _core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=name))
        )
        logger.info(f"Created namespace: {name}")
        return True
    except ApiException as e:
        logger.error(f"ensure_namespace {name}: {e}")
        return False


# ─── Private helpers ──────────────────────────────────────────────────────────

def _is_pod_ready(pod) -> bool:
    if not pod.status.conditions:
        return False
    for c in pod.status.conditions:
        if c.type == "Ready":
            return c.status == "True"
    return False


def _get_restart_count(pod) -> int:
    if not pod.status.container_statuses:
        return 0
    return sum(cs.restart_count for cs in pod.status.container_statuses)
