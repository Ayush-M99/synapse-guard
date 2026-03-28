"""
Virus Agent - Main Service
Subscribes to NATS for attack commands and injects chaos
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from nats.aio.client import Client as NATS
from registry import AttackPluginRegistry
from base import AttackResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger("virus-agent")

# ============================================================================
# Configuration
# ============================================================================

class Config:
    """Configuration for Virus Agent"""

    NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
    PLUGIN_DIR = os.getenv("PLUGIN_DIR", "plugins")
    RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "5"))
    RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "2"))

# ============================================================================
# Main Agent
# ============================================================================

class VirusAgent:
    """Chaos injection agent that subscribes to NATS"""

    def __init__(self):
        self.nc: NATS = NATS()
        self.registry = AttackPluginRegistry()
        self.logger = logger

    async def connect_to_nats(self) -> bool:
        """Connect to NATS with retries"""
        for attempt in range(Config.RETRY_ATTEMPTS):
            try:
                self.logger.info(
                    f"Connecting to NATS at {Config.NATS_URL} "
                    f"(attempt {attempt + 1}/{Config.RETRY_ATTEMPTS})"
                )
                await self.nc.connect(Config.NATS_URL)
                self.logger.info("✅ Connected to NATS")
                return True

            except Exception as e:
                self.logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < Config.RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(Config.RETRY_DELAY_SECONDS)

        self.logger.error("❌ Failed to connect to NATS after all retries")
        return False

    async def load_plugins(self) -> bool:
        """Load all attack plugins"""
        try:
            self.logger.info(f"Loading plugins from {Config.PLUGIN_DIR}")
            count = self.registry.load_plugins_from_directory(Config.PLUGIN_DIR)

            if not self.registry.validate_plugins():
                self.logger.error("Plugin validation failed")
                return False

            self.logger.info(f"✅ Loaded {count} attack plugins")
            return True

        except Exception as e:
            self.logger.error(f"Failed to load plugins: {e}")
            return False

    async def on_attack_command(self, msg):
        """Handle incoming attack command from NATS"""
        try:
            # Parse command
            command = json.loads(msg.data.decode())

            attack_id = command.get("attack_id")
            target_service = command.get("target_service", "payment-service")
            namespace = command.get("namespace", "darwin-target")

            self.logger.info(
                f"Received attack command: {attack_id} on {target_service}"
            )

            # Get plugin
            plugin = self.registry.get_plugin(attack_id)

            if not plugin:
                error_msg = f"Unknown attack: {attack_id}"
                self.logger.error(error_msg)
                result = AttackResult(
                    success=False,
                    attack_id=attack_id,
                    target_service=target_service,
                    error=error_msg,
                )
            else:
                # Execute attack
                self.logger.info(f"Executing attack: {attack_id}")
                result = await plugin.execute_attack(namespace, target_service)

                if result.success:
                    self.logger.info(
                        f"✅ Attack succeeded: {result.message}"
                    )
                else:
                    self.logger.error(f"❌ Attack failed: {result.error}")

            # Publish result to NATS
            await self.nc.publish(
                "darwin.attack.executed",
                json.dumps(result.to_dict()).encode()
            )

        except json.JSONDecodeError:
            self.logger.error("Invalid JSON in attack command")
        except Exception as e:
            self.logger.error(f"Error handling attack command: {e}")

    async def start(self):
        """Start the virus agent"""

        self.logger.info(f"""
╔════════════════════════════════════════════════════════════╗
║         DARWIN Virus Agent (Chaos Injector)               ║
║                                                            ║
║  NATS Server: {Config.NATS_URL:<38} ║
║  Plugin Directory: {Config.PLUGIN_DIR:<32} ║
║                                                            ║
║  Subscribing to: darwin.attack.schedule                   ║
║  Publishing to: darwin.attack.executed                    ║
║                                                            ║
║  6 Attack Families Ready:                                 ║
║  1. pod_crash (Gen 1)     4. timing_attack (Gen 2)        ║
║  2. network_latency (Gen 3)  5. amplification (Gen 1)     ║
║  3. resource_pressure (Gen 2) 6. camouflage (Gen 3)       ║
╚════════════════════════════════════════════════════════════╝
        """)

        # Load plugins
        if not await self.load_plugins():
            self.logger.error("Failed to load plugins - exiting")
            return

        # Connect to NATS
        if not await self.connect_to_nats():
            self.logger.error("Failed to connect to NATS - exiting")
            return

        # Subscribe to attack commands
        await self.nc.subscribe(
            "darwin.attack.schedule",
            cb=self.on_attack_command
        )

        self.logger.info("✅ Agent ready - waiting for attack commands")

        # Keep agent running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received interrupt - shutting down")
            await self.nc.close()

# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    agent = VirusAgent()
    asyncio.run(agent.start())
