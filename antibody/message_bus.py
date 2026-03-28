"""
NATS Message Bus Integration for Antibody Agent
"""

import asyncio
import json
import logging
from typing import Callable, Optional
from nats.aio.client import Client as NATS
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageBusClient:
    """NATS message bus client for Antibody Agent"""

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = NATS()
        self.connected = False

    async def connect(self) -> bool:
        """Connect to NATS"""
        try:
            await self.nc.connect(self.nats_url)
            self.connected = True
            logger.info(f"✅ Connected to NATS at {self.nats_url}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to connect to NATS: {e}")
            return False

    async def disconnect(self):
        """Disconnect from NATS"""
        if self.connected:
            await self.nc.close()
            self.connected = False
            logger.info("Disconnected from NATS")

    async def subscribe(self, subject: str, callback: Callable) -> Optional[object]:
        """Subscribe to NATS subject"""
        if not self.connected:
            logger.error("Not connected to NATS")
            return None

        try:
            subscription = await self.nc.subscribe(subject)
            logger.info(f"📡 Subscribed to: {subject}")

            async def handler():
                async for msg in subscription.inbox:
                    try:
                        await callback(msg)
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")

            asyncio.create_task(handler())
            return subscription
        except Exception as e:
            logger.error(f"Failed to subscribe to {subject}: {e}")
            return None

    async def publish(self, subject: str, data: dict) -> bool:
        """Publish message to NATS"""
        if not self.connected:
            logger.error("Not connected to NATS")
            return False

        try:
            payload = json.dumps(data).encode()
            await self.nc.publish(subject, payload)
            logger.debug(f"📤 Published to {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish to {subject}: {e}")
            return False

    async def health_check(self) -> bool:
        """Check if connected to NATS"""
        return self.connected
