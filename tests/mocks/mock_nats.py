"""
Mock NATS Message Bus for testing
In-memory pub/sub without real NATS server
"""

from typing import Dict, Any, Callable, List
from core.interfaces import IMessageBus
import asyncio
import json


class MockMessageBus(IMessageBus):
    """Mock implementation of NATS message bus for testing"""

    def __init__(self):
        self.subscribers = {}  # channel -> [callbacks]
        self.published_messages = []  # For testing
        self.connected = False

    async def connect(self) -> None:
        """Connect to message bus (mock)"""
        self.connected = True
        print("[MockMessageBus] Connected")

    async def disconnect(self) -> None:
        """Disconnect from message bus (mock)"""
        self.connected = False
        print("[MockMessageBus] Disconnected")

    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish message to channel"""
        if not self.connected:
            raise Exception("Not connected to message bus")

        # Record published message
        self.published_messages.append(
            {
                "channel": channel,
                "message": message,
                "timestamp": str(__import__("datetime").datetime.utcnow()),
            }
        )

        # Call all subscribers for this channel
        if channel in self.subscribers:
            for callback in self.subscribers[channel]:
                try:
                    # Support both sync and async callbacks
                    if asyncio.iscoroutinefunction(callback):
                        await callback(message)
                    else:
                        callback(message)
                except Exception as e:
                    print(f"[MockMessageBus] Callback error: {e}")

    async def subscribe(self, channel: str, callback: Callable) -> None:
        """Subscribe to channel with callback"""
        if not self.connected:
            raise Exception("Not connected to message bus")

        if channel not in self.subscribers:
            self.subscribers[channel] = []

        self.subscribers[channel].append(callback)
        print(f"[MockMessageBus] Subscribed to {channel}")

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from channel"""
        if channel in self.subscribers:
            del self.subscribers[channel]
            print(f"[MockMessageBus] Unsubscribed from {channel}")

    def get_published_messages(self, channel: str = None) -> List[Dict[str, Any]]:
        """Get published messages for testing"""
        if channel:
            return [m for m in self.published_messages if m["channel"] == channel]
        return self.published_messages

    def reset(self):
        """Reset mock state"""
        self.subscribers = {}
        self.published_messages = []
        self.connected = False
