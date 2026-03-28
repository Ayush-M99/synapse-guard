"""
Nerve Ending - DARWIN Telemetry Sidecar
Collects metrics from target service and publishes to NATS message bus
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Any

import aiohttp
from nats.aio.client import Client as NATS

# ============================================================================
# Configure Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger("nerve-ending")

# ============================================================================
# Configuration
# ============================================================================

class Config:
    """Configuration for Nerve Ending sidecar"""

    MONITORED_SERVICE = os.getenv("MONITORED_SERVICE", "unknown-service")
    NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
    APP_METRICS_URL = os.getenv("APP_METRICS_URL", "http://localhost:9090/metrics")
    COLLECTION_INTERVAL_SECONDS = int(os.getenv("COLLECTION_INTERVAL_SECONDS", "2"))
    RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "5"))
    RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "2"))

# ============================================================================
# Telemetry Collector
# ============================================================================

class TelemetryCollector:
    """Collects metrics from target service"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        logger.info("HTTP session initialized")

    async def disconnect(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
        logger.info("HTTP session closed")

    async def fetch_metrics(self) -> Optional[str]:
        """Fetch /metrics endpoint from target service"""
        if not self.session:
            logger.error("Session not initialized")
            return None

        try:
            async with self.session.get(
                Config.APP_METRICS_URL,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.warning(f"Metrics endpoint returned {resp.status}")
                    return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching metrics from {Config.APP_METRICS_URL}")
            return None
        except aiohttp.ClientError as e:
            logger.warning(f"Failed to fetch metrics: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching metrics: {e}")
            return None

    @staticmethod
    def parse_prometheus_metrics(metrics_text: str) -> Dict[str, float]:
        """
        Parse Prometheus text format metrics

        Returns dict of metric_name -> value
        """
        metrics = {}

        for line in metrics_text.split('\n'):
            # Skip comments and empty lines
            if line.startswith('#') or not line.strip():
                continue

            # Parse metric line: metric_name{labels} value timestamp
            # Strip labels: http_requests_total{method="POST"} 100 → http_requests_total 100
            # Also handle: http_error_rate 0.05
            match = re.match(r'([a-zA-Z_:][a-zA-Z0-9_:]*)\{?[^}]*\}?\s+([\d.eE+-]+)', line)
            if match:
                metric_name = match.group(1)
                value = float(match.group(2))
                # Keep only the first occurrence of each metric (aggregated)
                if metric_name not in metrics:
                    metrics[metric_name] = value

        return metrics

    @staticmethod
    def extract_7_feature_vector(metrics: Dict[str, float]) -> Optional[List[float]]:
        """
        Extract 7-feature vector from Prometheus metrics

        Features:
        1. CPU usage (CPUs)
        2. Memory (MB)
        3. HTTP error rate (0-1)
        4. P99 latency (ms)
        5. Pod restart count
        6. Network RX (Mbps)
        7. Network TX (Mbps)
        """

        try:
            features = [
                metrics.get('cpu_usage', 0.0),  # CPU usage
                metrics.get('memory_mb', 0.0),  # Memory
                metrics.get('http_error_rate', 0.0),  # Error rate
                metrics.get('http_latency_p99_ms', 0.0),  # P99 latency
                metrics.get('pod_restart_count', 0.0),  # Restarts
                metrics.get('network_rx_bytes', 0.0) / 1_000_000,  # RX to Mbps
                metrics.get('network_tx_bytes', 0.0) / 1_000_000,  # TX to Mbps
            ]

            return features

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error extracting features: {e}")
            return None

# ============================================================================
# NATS Publisher
# ============================================================================

class NATSPublisher:
    """Publishes telemetry to NATS message bus"""

    def __init__(self):
        self.nc: Optional[NATS] = None
        self.connected = False

    async def connect(self) -> bool:
        """Connect to NATS server with retries"""
        self.nc = NATS()

        for attempt in range(Config.RETRY_ATTEMPTS):
            try:
                logger.info(f"Connecting to NATS at {Config.NATS_URL} (attempt {attempt + 1}/{Config.RETRY_ATTEMPTS})")
                await self.nc.connect(Config.NATS_URL)
                self.connected = True
                logger.info("✅ Connected to NATS message bus")
                return True

            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < Config.RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(Config.RETRY_DELAY_SECONDS)

        logger.error("❌ Failed to connect to NATS after all retries")
        return False

    async def disconnect(self):
        """Disconnect from NATS"""
        if self.nc and self.connected:
            await self.nc.close()
            self.connected = False
            logger.info("Disconnected from NATS")

    async def publish_telemetry(
        self,
        service_name: str,
        features: List[float]
    ) -> bool:
        """Publish telemetry to NATS"""
        if not self.connected or not self.nc:
            logger.error("Not connected to NATS")
            return False

        try:
            # Create telemetry message
            telemetry = {
                "service": service_name,
                "timestamp": datetime.utcnow().isoformat(),
                "features": {
                    "cpu_usage": features[0],
                    "memory_mb": features[1],
                    "error_rate": features[2],
                    "latency_p99_ms": features[3],
                    "pod_restarts": features[4],
                    "network_rx_mbps": features[5],
                    "network_tx_mbps": features[6],
                },
            }

            # Publish to NATS
            channel = f"darwin.telemetry.{service_name}"
            await self.nc.publish(
                channel,
                json.dumps(telemetry).encode()
            )

            return True

        except Exception as e:
            logger.error(f"Error publishing to NATS: {e}")
            return False

# ============================================================================
# Main Sidecar Loop
# ============================================================================

async def run_sidecar():
    """Main sidecar collection loop"""

    logger.info(f"""
╔════════════════════════════════════════════════════════════╗
║         DARWIN Nerve Ending (Telemetry Sidecar)           ║
║                                                            ║
║  Service: {Config.MONITORED_SERVICE:<42} ║
║  Metrics URL: {Config.APP_METRICS_URL:<36} ║
║  NATS Server: {Config.NATS_URL:<37} ║
║  Collection Interval: {Config.COLLECTION_INTERVAL_SECONDS}s                       ║
║                                                            ║
║  Collecting 7-feature telemetry vectors...                ║
╚════════════════════════════════════════════════════════════╝
    """)

    collector = TelemetryCollector()
    publisher = NATSPublisher()

    # Connect to HTTP and NATS
    await collector.connect()

    if not await publisher.connect():
        logger.error("Failed to connect to NATS - exiting")
        await collector.disconnect()
        return

    # Main collection loop
    collection_count = 0

    try:
        while True:
            # Fetch metrics from target service
            metrics_text = await collector.fetch_metrics()

            if metrics_text:
                # Parse Prometheus metrics
                metrics_dict = collector.parse_prometheus_metrics(metrics_text)

                # Extract 7-feature vector
                features = collector.extract_7_feature_vector(metrics_dict)

                if features:
                    # Publish to NATS
                    success = await publisher.publish_telemetry(
                        Config.MONITORED_SERVICE,
                        features
                    )

                    if success:
                        collection_count += 1
                        if collection_count % 10 == 0:  # Log every 10 collections
                            logger.info(
                                f"📤 Published {collection_count} telemetry updates | "
                                f"Features: CPU={features[0]:.2f}, "
                                f"Mem={features[1]:.0f}MB, "
                                f"Errors={features[2]*100:.1f}%, "
                                f"P99={features[3]:.0f}ms"
                            )
                    else:
                        logger.error("Failed to publish telemetry to NATS")
                else:
                    logger.warning("Could not extract feature vector from metrics")
            else:
                logger.warning("Could not fetch metrics from target service")

            # Wait for next collection interval
            await asyncio.sleep(Config.COLLECTION_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal - shutting down")
    except Exception as e:
        logger.error(f"Unexpected error in collection loop: {e}")
    finally:
        await publisher.disconnect()
        await collector.disconnect()
        logger.info("Nerve ending sidecar shut down")

# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    logger.info("Starting DARWIN Nerve Ending sidecar...")
    asyncio.run(run_sidecar())
