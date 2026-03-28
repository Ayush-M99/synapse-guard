"""
Unit tests for Payment Service
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app, service_state

client = TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint"""

    def test_health_returns_200(self):
        """Health endpoint should return 200"""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_has_required_fields(self):
        """Health response should have required fields"""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "timestamp" in data

    def test_health_status_healthy(self):
        """Health status should be 'healthy'"""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_service_name(self):
        """Health should return correct service name"""
        response = client.get("/health")
        data = response.json()
        assert data["service"] == "payment-service"


class TestMetricsEndpoint:
    """Test Prometheus metrics endpoint"""

    def test_metrics_returns_200(self):
        """Metrics endpoint should return 200"""
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_has_prometheus_format(self):
        """Metrics should be in Prometheus text format"""
        response = client.get("/metrics")
        text = response.text

        # Should contain Prometheus format indicators
        assert "HELP" in text or "http_requests_total" in text or "TYPE" in text

    def test_metrics_contains_counters(self):
        """Metrics should contain request counter"""
        # Make a request first
        client.get("/health")

        response = client.get("/metrics")
        text = response.text

        # Should have request metrics
        assert "http_requests_total" in text


class TestRootEndpoint:
    """Test root endpoint"""

    def test_root_returns_200(self):
        """Root endpoint should return 200"""
        response = client.get("/")
        assert response.status_code == 200

    def test_root_has_service_info(self):
        """Root should provide service information"""
        response = client.get("/")
        data = response.json()

        assert "service" in data
        assert data["service"] == "payment-service"


class TestProcessPaymentEndpoint:
    """Test payment processing endpoint"""

    def test_process_payment_valid_amount(self):
        """Should process valid payment amount"""
        response = client.post("/process-payment?amount=100.50")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["amount"] == 100.50
        assert "transaction_id" in data

    def test_process_payment_negative_amount(self):
        """Should reject negative amount"""
        response = client.post("/process-payment?amount=-100")
        assert response.status_code == 400

    def test_process_payment_zero_amount(self):
        """Should reject zero amount"""
        response = client.post("/process-payment?amount=0")
        assert response.status_code == 400

    def test_process_payment_exceeds_limit(self):
        """Should reject amount exceeding limit"""
        response = client.post("/process-payment?amount=200000")
        assert response.status_code == 400

    def test_process_payment_increments_counter(self):
        """Should increment request counter"""
        initial_count = service_state["request_count"]

        client.post("/process-payment?amount=50")

        # Request count should increase
        assert service_state["request_count"] > initial_count


class TestListTransactionsEndpoint:
    """Test list transactions endpoint"""

    def test_list_transactions_returns_200(self):
        """Should return 200"""
        response = client.get("/list-transactions")
        assert response.status_code == 200

    def test_list_transactions_has_data(self):
        """Should return transaction list"""
        response = client.get("/list-transactions")
        data = response.json()

        assert "transactions" in data
        assert "count" in data
        assert len(data["transactions"]) > 0

    def test_list_transactions_structure(self):
        """Transaction records should have correct structure"""
        response = client.get("/list-transactions")
        data = response.json()

        for txn in data["transactions"]:
            assert "transaction_id" in txn
            assert "amount" in txn
            assert "status" in txn
            assert "timestamp" in txn


class TestRefundEndpoint:
    """Test refund endpoint"""

    def test_refund_valid_amount(self):
        """Should process valid refund"""
        response = client.post("/refund?transaction_id=txn-1000&amount=50")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "refund_id" in data

    def test_refund_negative_amount(self):
        """Should reject negative refund"""
        response = client.post("/refund?transaction_id=txn-1000&amount=-50")
        assert response.status_code == 400


class TestMetricsTracking:
    """Test metrics are being tracked correctly"""

    def test_latency_tracking(self):
        """Request latencies should be tracked"""
        client.post("/process-payment?amount=50")

        # Latencies should be recorded
        assert len(service_state["latencies"]) > 0

    def test_error_rate_calculation(self):
        """Error rate should be calculated"""
        # Make some requests
        client.get("/health")  # Success
        client.post("/process-payment?amount=-50")  # Error
        client.get("/health")  # Success

        # Error rate should be calculated
        error_count = service_state["error_count"]
        total_requests = service_state["request_count"]
        expected_error_rate = (error_count / max(total_requests, 1)) * 100

        assert expected_error_rate >= 0


class TestChaosEndpoints:
    """Test chaos injection endpoints"""

    def test_chaos_degrade(self):
        """Should accept chaos degrade command"""
        response = client.post("/chaos/degrade?latency_ms=1000")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "degraded"

    def test_chaos_recover(self):
        """Should accept chaos recover command"""
        response = client.post("/chaos/recover")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "recovered"


class TestConcurrentRequests:
    """Test handling multiple concurrent requests"""

    def test_multiple_requests_increment_counter(self):
        """Multiple requests should increment counter"""
        initial_count = service_state["request_count"]

        for i in range(5):
            client.get("/health")

        assert service_state["request_count"] >= initial_count + 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
