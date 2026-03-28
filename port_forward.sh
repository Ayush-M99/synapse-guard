#!/usr/bin/env bash
# DARWIN — Port-Forward Helper for WSL2
# Sets up all required port-forwards from minikube to localhost.
# Run this in a separate terminal, keep it alive.
#
# Usage: ./port_forward.sh [--namespace darwin]

NS="${1:-darwin}"
echo "Setting up DARWIN port-forwards from minikube namespace: $NS"
echo "Press Ctrl+C to stop all."

trap 'kill $(jobs -p) 2>/dev/null; echo "Port-forwards stopped."' EXIT

# ── DARWIN internal services ───────────────────────────────────────────────
kubectl port-forward svc/redis      6379:6379 -n "$NS" &
echo "  Redis      → localhost:6379"

kubectl port-forward svc/prometheus 9090:9090 -n "$NS" &
echo "  Prometheus → localhost:9090"

# ── Patient services (for Prometheus scraping) ─────────────────────────────
kubectl port-forward svc/auth-service          8010:80 -n patient &
kubectl port-forward svc/api-gateway           8011:80 -n patient &
kubectl port-forward svc/order-service         8012:80 -n patient &
kubectl port-forward svc/payment-service       8013:80 -n patient &
kubectl port-forward svc/inventory-service     8014:80 -n patient &
kubectl port-forward svc/notification-service  8015:80 -n patient &
echo "  Patient services → :8010-8015"

echo ""
echo "All port-forwards active. Waiting..."
wait
