"""
Unit tests for Nerve Ending Telemetry Sidecar
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sidecar import TelemetryCollector, NATSPublisher, Config


class TestTelemetryCollector:
    """Test telemetry collection and metric parsing"""

    def test_parse_prometheus_metrics_simple(self):
        """Test parsing simple Prometheus metrics"""
        metrics_text = """
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total 1000
http_error_rate 0.05
http_latency_p99_ms 150.5
"""
        parsed = TelemetryCollector.parse_prometheus_metrics(metrics_text)

        assert "http_requests_total" in parsed
        assert parsed["http_requests_total"] == 1000.0
        assert parsed["http_error_rate"] == 0.05
        assert parsed["http_latency_p99_ms"] == 150.5

    def test_parse_prometheus_metrics_with_labels(self):
        """Test parsing metrics with labels (aggregates same metric name)"""
        metrics_text = """
http_request_duration_seconds_bucket{le="0.1"} 50
http_request_duration_seconds_bucket{le="0.5"} 200
http_request_duration_seconds_bucket{le="1.0"} 300
"""
        parsed = TelemetryCollector.parse_prometheus_metrics(metrics_text)

        # Should extract and aggregate same metric names (strip labels)
        # All 3 lines are the same metric, so we get 1 aggregated entry
        assert len(parsed) == 1
        assert "http_request_duration_seconds_bucket" in parsed
        assert parsed["http_request_duration_seconds_bucket"] == 50.0  # First value

    def test_parse_prometheus_metrics_empty(self):
        """Test parsing empty metrics"""
        metrics_text = ""
        parsed = TelemetryCollector.parse_prometheus_metrics(metrics_text)

        assert parsed == {}

    def test_parse_prometheus_metrics_only_comments(self):
        """Test parsing metrics with only comments"""
        metrics_text = """
# HELP http_requests_total Total requests
# TYPE http_requests_total counter
"""
        parsed = TelemetryCollector.parse_prometheus_metrics(metrics_text)

        assert parsed == {}

    def test_extract_7_feature_vector_complete(self):
        """Test extracting 7-feature vector with all metrics"""
        metrics = {
            "cpu_usage": 2.5,
            "memory_mb": 512,
            "http_error_rate": 0.1,
            "http_latency_p99_ms": 500,
            "pod_restart_count": 2,
            "network_rx_bytes": 1_000_000,  # 1MB
            "network_tx_bytes": 2_000_000,  # 2MB
        }

        features = TelemetryCollector.extract_7_feature_vector(metrics)

        assert features is not None
        assert len(features) == 7
        assert features[0] == 2.5  # CPU
        assert features[1] == 512  # Memory
        assert features[2] == 0.1  # Error rate
        assert features[3] == 500  # Latency
        assert features[4] == 2  # Restarts
        assert features[5] == 1.0  # RX in Mbps
        assert features[6] == 2.0  # TX in Mbps

    def test_extract_7_feature_vector_partial(self):
        """Test extracting vector with missing metrics (should use defaults)"""
        metrics = {
            "cpu_usage": 1.5,
            "http_error_rate": 0.05,
        }

        features = TelemetryCollector.extract_7_feature_vector(metrics)

        assert features is not None
        assert len(features) == 7
        assert features[0] == 1.5
        assert features[1] == 0.0  # Default for missing memory_mb

    def test_extract_7_feature_vector_empty(self):
        """Test extracting vector from empty metrics"""
        metrics = {}

        features = TelemetryCollector.extract_7_feature_vector(metrics)

        assert features is not None
        assert len(features) == 7
        assert all(f == 0.0 for f in features)  # All should be 0

    def test_extract_7_feature_vector_network_conversion(self):
        """Test network bytes are converted to Mbps"""
        metrics = {
            "network_rx_bytes": 1_000_000,  # 1MB
            "network_tx_bytes": 5_000_000,  # 5MB
        }

        features = TelemetryCollector.extract_7_feature_vector(metrics)

        assert features[5] == 1.0  # RX: 1,000,000 / 1,000,000 = 1.0
        assert features[6] == 5.0  # TX: 5,000,000 / 1,000,000 = 5.0


class TestNATSPublisher:
    """Test NATS publishing"""

    @pytest.mark.asyncio
    async def test_publish_telemetry_format(self):
        """Test telemetry message format"""
        publisher = NATSPublisher()
        publisher.nc = AsyncMock()
        publisher.connected = True

        features = [1.5, 512, 0.1, 500, 2, 5.0, 10.0]

        success = await publisher.publish_telemetry("payment-service", features)

        assert success is True
        publisher.nc.publish.assert_called_once()

        # Verify message format
        call_args = publisher.nc.publish.call_args
        channel = call_args[0][0]
        message_bytes = call_args[0][1]

        assert channel == "darwin.telemetry.payment-service"

        # Decode and verify message
        message = json.loads(message_bytes.decode())
        assert message["service"] == "payment-service"
        assert "timestamp" in message
        assert "features" in message
        assert message["features"]["cpu_usage"] == 1.5
        assert message["features"]["memory_mb"] == 512

    @pytest.mark.asyncio
    async def test_publish_telemetry_not_connected(self):
        """Test publishing when not connected"""
        publisher = NATSPublisher()
        publisher.connected = False

        features = [1.5, 512, 0.1, 500, 2, 5.0, 10.0]

        success = await publisher.publish_telemetry("payment-service", features)

        assert success is False

    @pytest.mark.asyncio
    async def test_publish_telemetry_with_different_services(self):
        """Test publishing for different services"""
        publisher = NATSPublisher()
        publisher.nc = AsyncMock()
        publisher.connected = True

        features = [1.0, 256, 0.05, 300, 0, 2.0, 3.0]

        for service in ["payment-service", "auth-service", "order-service"]:
            await publisher.publish_telemetry(service, features)

        assert publisher.nc.publish.call_count == 3

        # Verify each call had correct channel
        calls = publisher.nc.publish.call_args_list
        channels = [call[0][0] for call in calls]

        assert "darwin.telemetry.payment-service" in channels
        assert "darwin.telemetry.auth-service" in channels
        assert "darwin.telemetry.order-service" in channels


class TestIntegration:
    """Integration tests"""

    def test_complete_metric_parsing_and_feature_extraction(self):
        """Test complete flow: Prometheus text → features"""

        # Realistic Prometheus output
        prometheus_output = """
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="POST",endpoint="/process-payment",status="200"} 1500
http_requests_total{method="GET",endpoint="/health",status="200"} 500
http_requests_total{method="POST",endpoint="/process-payment",status="503"} 75

# HELP http_request_duration_seconds HTTP request duration
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds{method="POST",endpoint="/process-payment"} 0.15

# HELP http_error_rate Current HTTP error rate
# TYPE http_error_rate gauge
http_error_rate 0.05

# HELP http_latency_p99_ms P99 HTTP latency
# TYPE http_latency_p99_ms gauge
http_latency_p99_ms 450

# HELP pod_restart_count Pod restart count
# TYPE pod_restart_count gauge
pod_restart_count 1

# HELP network_rx_bytes Network received bytes
# TYPE network_rx_bytes gauge
network_rx_bytes 50000000

# HELP network_tx_bytes Network transmitted bytes
# TYPE network_tx_bytes gauge
network_tx_bytes 100000000

# CPU usage (simulated - not in real Prometheus)
cpu_usage 2.5
memory_mb 512
"""

        # Parse metrics
        parsed_metrics = TelemetryCollector.parse_prometheus_metrics(prometheus_output)

        # Verify parsing
        assert "http_requests_total" in parsed_metrics
        assert "http_error_rate" in parsed_metrics
        assert parsed_metrics["http_error_rate"] == 0.05

        # Extract features
        features = TelemetryCollector.extract_7_feature_vector(parsed_metrics)

        # Verify features
        assert features is not None
        assert len(features) == 7
        assert features[0] == 2.5  # CPU
        assert features[1] == 512  # Memory
        assert features[2] == 0.05  # Error rate
        assert features[3] == 450  # P99 latency
        assert features[4] == 1  # Restarts
        assert features[5] == 50.0  # RX in Mbps
        assert features[6] == 100.0  # TX in Mbps


class TestConfiguration:
    """Test configuration handling"""

    def test_config_defaults(self):
        """Test default configuration values"""
        # Config should use env vars or defaults
        assert Config.MONITORED_SERVICE != ""
        assert Config.NATS_URL != ""
        assert Config.COLLECTION_INTERVAL_SECONDS > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
