"""
DARWIN Locust Load Generator
============================
Simulates real e-commerce traffic against the patient application.
Designed to make Prometheus metrics meaningful for ML detection.

Usage (after patient app is deployed):
    locust -f locustfile.py --host http://localhost:30080 \
           --users 20 --spawn-rate 2 --headless --run-time 60s

Or with Web UI:
    locust -f locustfile.py --host http://localhost:30080
    → open http://localhost:8089

Profiles:
    LOAD_PROFILE=normal    → standard 20 users (baseline, IF should not fire)
    LOAD_PROFILE=stress    → 100 users, high error injection (IF should fire)
    LOAD_PROFILE=spike     → sudden burst to 200 users then drop (timing attack)
    LOAD_PROFILE=camouflage→ slow creep from 5→80 over 5 minutes (CUSUM detects)
"""
import os
import random
import time
import json

from locust import HttpUser, task, between, events, constant_pacing
from locust.exception import RescheduleTask

PROFILE = os.getenv("LOAD_PROFILE", "normal")

USERS = [f"user_{i:04d}" for i in range(1, 1001)]
ITEMS = [f"item_{i:03d}" for i in range(1, 50)]


# ── Utility ───────────────────────────────────────────────────────────────────

def random_user():
    return random.choice(USERS)


def random_item():
    return random.choice(ITEMS)


def random_price():
    return round(random.uniform(4.99, 199.99), 2)


# ── Normal E-Commerce Traffic ─────────────────────────────────────────────────

class ShopperUser(HttpUser):
    """
    Normal user: browse → add to cart → checkout → pay
    Wait time simulates real user think time.
    """
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.user_id = random_user()
        self.token   = None
        self._login()

    def _login(self):
        with self.client.post(
            "/api/login",
            json={"username": self.user_id, "password": "password123"},
            catch_response=True,
            name="/api/login",
        ) as r:
            if r.status_code == 200:
                self.token = r.json().get("token")
                r.success()
            else:
                r.failure(f"Login failed: {r.status_code}")

    @task(5)
    def browse_catalog(self):
        """Browse inventory — most common action."""
        with self.client.get(
            "/api/catalog",
            name="/api/catalog",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code in (502, 503, 504):
                r.failure(f"Gateway error {r.status_code}")
            else:
                r.failure(f"Unexpected {r.status_code}")

    @task(3)
    def check_stock(self):
        item = random_item()
        with self.client.get(
            f"/api/stock/{item}",
            name="/api/stock/{item_id}",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"{r.status_code}")

    @task(2)
    def place_order(self):
        """Place an order (calls auth + order + payment + inventory)."""
        with self.client.post(
            "/api/order",
            json={
                "user_id":  self.user_id,
                "item_id":  random_item(),
                "quantity": random.randint(1, 5),
                "price":    random_price(),
            },
            name="/api/order",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code in (502, 503, 504):
                r.failure(f"Gateway error {r.status_code}")
            else:
                r.failure(f"{r.status_code}: {r.text[:100]}")

    @task(1)
    def pay_direct(self):
        with self.client.post(
            "/api/pay",
            json={
                "order_id": f"ord_{random.randint(1000,9999)}",
                "amount":   random_price(),
                "currency": "USD",
            },
            name="/api/pay",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 500):  # 500 is expected 2% failure rate
                r.success()
            else:
                r.failure(f"{r.status_code}")


# ── Stress Profile ─────────────────────────────────────────────────────────────

class StressUser(HttpUser):
    """
    High throughput user — hammer the payment service.
    Designed to trigger Isolation Forest anomaly detection.
    """
    wait_time = between(0.05, 0.2)

    @task(10)
    def hammer_payment(self):
        self.client.post(
            "/api/pay",
            json={"order_id": f"stress_{random.randint(1,9999)}", "amount": 99.99},
            name="/api/pay [stress]",
        )

    @task(5)
    def hammer_order(self):
        self.client.post(
            "/api/order",
            json={
                "user_id":  random_user(),
                "item_id":  random_item(),
                "quantity": random.randint(1, 20),
                "price":    random_price(),
            },
            name="/api/order [stress]",
        )

    @task(2)
    def hammer_catalog(self):
        self.client.get("/api/catalog", name="/api/catalog [stress]")


# ── Health Check User ─────────────────────────────────────────────────────────

class HealthCheckUser(HttpUser):
    """
    Lightweight user that only pings /health to show baseline.
    Always runs alongside other profiles.
    """
    wait_time = between(5, 10)
    weight = 1

    @task
    def health_check(self):
        self.client.get("/health", name="/health")


# ── Profile selector ──────────────────────────────────────────────────────────

# Locust picks user classes based on `weight` or by naming them in --users flag.
# When LOAD_PROFILE=stress, stress users dominate.

if PROFILE == "stress":
    # StressUser dominates
    ShopperUser.weight = 1
    StressUser.weight  = 10
elif PROFILE == "camouflage":
    # Very slow ramp — only ShopperUser, but Locust is told to ramp over 5 mins
    ShopperUser.weight = 10
    StressUser.weight  = 0
else:
    # Normal
    ShopperUser.weight = 8
    StressUser.weight  = 1


# ── Event hooks for DARWIN integration ───────────────────────────────────────

@events.request.add_listener
def on_request(request_type, name, response_time, response_length,
               response, context, **kwargs):
    """Forward high-latency requests to DARWIN API for correlation."""
    if response_time > 2000:  # > 2s is anomalous
        try:
            import urllib.request, json as _json
            data = _json.dumps({
                "event":     "high_latency",
                "endpoint":  name,
                "latency_ms": response_time,
                "status":    getattr(response, "status_code", 0),
            }).encode()
            req = urllib.request.Request(
                "http://localhost:9000/anomalies",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=0.5)
        except Exception:
            pass  # DARWIN unavailable — don't break load test
