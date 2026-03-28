"""
Antibody Agent Main Orchestrator
Listens for failures and orchestrates 3-tier RAG recovery
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

from .message_bus import MessageBusClient
from .models import FailureEvent, RecoveryContext, RecoveryOutcome
from .signature_hasher import SignatureHasher

logger = logging.getLogger(__name__)


class AntibodyAgent:
    """
    Main Antibody Agent orchestrator

    Flow:
    1. Listen to NATS: brain.rf_classified (from ML Pipeline)
    2. Create signature hash from failure event
    3. Call RAG Engine for recovery playbook
    4. Execute recovery actions via Kubernetes API
    5. Track recovery time
    6. Learn: Update caches and databases
    7. Publish: antibody.recovery_complete to NATS
    """

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        rag_engine=None,  # Will be injected
        recovery_executor=None,  # Will be injected
        learning_loop=None,  # Will be injected
    ):
        self.service_name = "antibody-agent"
        self.nats_url = nats_url
        self.message_bus = MessageBusClient(nats_url)
        self.rag_engine = rag_engine
        self.recovery_executor = recovery_executor
        self.learning_loop = learning_loop

        # State tracking
        self.is_running = False
        self.recovery_count = 0
        self.successful_recoveries = 0
        self.failed_recoveries = 0
        self.total_recovery_time_ms = 0.0

    async def start(self):
        """Start the Antibody Agent"""
        logger.info("🚀 Antibody Agent starting...")

        # Connect to NATS
        connected = await self.message_bus.connect()
        if not connected:
            logger.error("❌ Failed to connect to NATS")
            return False

        # Subscribe to ML Pipeline failure events
        self.is_running = True
        await self.message_bus.subscribe(
            "brain.rf_classified",
            self._handle_failure_event,
        )
        logger.info("📡 Listening for failures on brain.rf_classified")

        return True

    async def stop(self):
        """Stop the Antibody Agent"""
        self.is_running = False
        await self.message_bus.disconnect()
        logger.info("🛑 Antibody Agent stopped")

    async def _handle_failure_event(self, msg):
        """
        Handle failure event from ML Pipeline

        Called when ML pipeline publishes:
        brain.rf_classified → {service, rf_label, rf_confidence, anomaly_score, ...}
        """
        try:
            # Parse message
            data = json.loads(msg.data.decode())
            logger.info(f"📨 Received failure event: {data}")

            # Create FailureEvent
            failure_event = FailureEvent(
                service=data["service"],
                attack_family=data.get("rf_label", "unknown"),
                rf_confidence=data.get("rf_confidence", 0.0),
                anomaly_score=data.get("anomaly_score", 0.0),
                detection_path=data.get("detection_path", "unknown"),
                timestamp=datetime.fromisoformat(
                    data.get("timestamp", datetime.utcnow().isoformat())
                ),
            )

            # Process recovery
            await self._process_recovery(failure_event)

        except Exception as e:
            logger.error(f"❌ Error handling failure event: {e}")

    async def _process_recovery(self, failure_event: FailureEvent):
        """
        Process complete recovery flow for a failure

        1. Create signature hash
        2. Get recovery playbook (RAG Tiers 1,2,3)
        3. Execute recovery actions
        4. Learn from outcome
        5. Publish completion
        """
        recovery_start = time.time()
        self.recovery_count += 1

        try:
            # Step 1: Create signature hash
            signature_hash = SignatureHasher.create_signature_hash(failure_event)
            logger.info(f"🔐 Signature hash: {signature_hash}")

            # Step 2: Get recovery playbook (3-tier RAG)
            logger.info("🔍 Retrieving recovery playbook via RAG...")
            playbook = await self.rag_engine.retrieve_recovery_playbook(
                failure_event, signature_hash
            )

            if playbook is None:
                logger.error("❌ Failed to retrieve recovery playbook")
                self.failed_recoveries += 1
                return

            # Step 3: Create recovery context
            recovery_context = RecoveryContext(
                failure_event=failure_event,
                signature_hash=signature_hash,
                playbook=playbook,
            )

            # Step 4: Execute recovery actions
            logger.info("⚡ Executing recovery actions...")
            outcome = await self.recovery_executor.execute_recovery(recovery_context)

            if outcome.success:
                self.successful_recoveries += 1
                logger.info(f"✅ Recovery successful in {outcome.recovery_time_ms:.1f}ms")
            else:
                self.failed_recoveries += 1
                logger.error(
                    f"❌ Recovery failed: {outcome.error_message} ({outcome.recovery_time_ms:.1f}ms)"
                )

            # Step 5: Learn from outcome
            self.total_recovery_time_ms += outcome.recovery_time_ms
            logger.info("📚 Storing learning record...")
            await self.learning_loop.record_recovery(outcome)

            # Step 6: Publish completion event
            await self._publish_recovery_complete(outcome)

        except Exception as e:
            logger.error(f"❌ Recovery process failed: {e}")
            self.failed_recoveries += 1

    async def _publish_recovery_complete(self, outcome: RecoveryOutcome):
        """Publish recovery completion event to NATS"""
        try:
            event = outcome.to_dict()
            await self.message_bus.publish("antibody.recovery_complete", event)
            logger.info(f"📤 Published recovery_complete event")
        except Exception as e:
            logger.error(f"Failed to publish recovery_complete: {e}")

    async def health(self) -> dict:
        """Health check endpoint"""
        return {
            "service": self.service_name,
            "status": "healthy" if self.is_running else "degraded",
            "nats_connected": await self.message_bus.health_check(),
            "recovery_count": self.recovery_count,
            "successful_recoveries": self.successful_recoveries,
            "failed_recoveries": self.failed_recoveries,
            "success_rate": (
                self.successful_recoveries / self.recovery_count
                if self.recovery_count > 0
                else 0.0
            ),
            "avg_recovery_time_ms": (
                self.total_recovery_time_ms / self.successful_recoveries
                if self.successful_recoveries > 0
                else 0.0
            ),
        }
