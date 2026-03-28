"""
Antibody Agent Main Application
Entry point for the RAG-based recovery orchestrator
"""

import asyncio
import os
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from antibody.agent import AntibodyAgent
from antibody.rag_engine import RAGRecoveryEngine
from antibody.recovery_executor import RecoveryExecutor
from antibody.learning_loop import LearningLoop
from antibody.connectors import RedisCacheTier, Neo4jGraphTier, PostgresDBTier


class AntibodyAgentApp:
    """Complete Antibody Agent application"""

    def __init__(self):
        self.agent = None
        self.rag_engine = None
        self.recovery_executor = None
        self.learning_loop = None

        # Load config from environment
        self.nats_url = os.getenv("NATS_URL", "nats://nats.darwin-infra:4222")
        self.redis_host = os.getenv("REDIS_HOST", "redis.darwin-infra")
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j.darwin-infra:7687")
        self.postgres_host = os.getenv("POSTGRES_HOST", "postgres.darwin-infra")
        self.k8s_namespace = os.getenv("K8S_NAMESPACE", "darwin-target")
        self.in_cluster = os.getenv("IN_CLUSTER", "false").lower() == "true"

    async def initialize(self) -> bool:
        """Initialize all components"""
        logger.info("🚀 Initializing Antibody Agent...")

        try:
            # ================================================================
            # Connect to Tier 1: Redis (Immunity Cache)
            # ================================================================
            logger.info("📦 Connecting to Redis Tier 1...")
            redis_tier = RedisCacheTier(host=self.redis_host)
            redis_connected = await redis_tier.connect()

            if not redis_connected:
                logger.error("❌ Failed to connect to Redis")
                return False

            # ================================================================
            # Connect to Tier 2: Neo4j (Knowledge Graph)
            # ================================================================
            logger.info("📊 Connecting to Neo4j Tier 2...")
            neo4j_tier = Neo4jGraphTier(uri=self.neo4j_uri)
            neo4j_connected = await neo4j_tier.connect()

            if not neo4j_connected:
                logger.error("❌ Failed to connect to Neo4j")
                return False

            # ================================================================
            # Connect to Tier 3: PostgreSQL (DNA Store)
            # ================================================================
            logger.info("🧬 Connecting to PostgreSQL Tier 3...")
            postgres_tier = PostgresDBTier(host=self.postgres_host)
            postgres_connected = await postgres_tier.connect()

            if not postgres_connected:
                logger.error("❌ Failed to connect to PostgreSQL")
                return False

            # ================================================================
            # Connect to Kubernetes
            # ================================================================
            logger.info("☸️  Connecting to Kubernetes...")
            recovery_executor = RecoveryExecutor(
                namespace=self.k8s_namespace,
                in_cluster=self.in_cluster,
            )
            k8s_connected = await recovery_executor.connect()

            if not k8s_connected:
                logger.error("❌ Failed to connect to Kubernetes")
                if not self.in_cluster:  # OK to fail if not in cluster
                    logger.warning("⚠️  Running without Kubernetes (local testing only)")

            # ================================================================
            # Create subsystems
            # ================================================================
            logger.info("🔧 Initializing subsystems...")

            self.rag_engine = RAGRecoveryEngine(
                redis_tier=redis_tier,
                neo4j_tier=neo4j_tier,
                postgres_tier=postgres_tier,
            )

            self.recovery_executor = recovery_executor

            self.learning_loop = LearningLoop(
                postgres_tier=postgres_tier,
                redis_tier=redis_tier,
                neo4j_tier=neo4j_tier,
            )

            # ================================================================
            # Create main agent
            # ================================================================
            self.agent = AntibodyAgent(
                nats_url=self.nats_url,
                rag_engine=self.rag_engine,
                recovery_executor=self.recovery_executor,
                learning_loop=self.learning_loop,
            )

            logger.info("✅ Antibody Agent initialized successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}")
            return False

    async def run(self):
        """Run the Antibody Agent"""
        logger.info(
            """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        🧬 DARWIN ANTIBODY AGENT Starting Up 🧬               ║
║                                                               ║
║  RAG-Based Autonomous Self-Healing System                     ║
║  Version 1.0                                                  ║
║  Generation 1                                                 ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """
        )

        # Initialize
        initialized = await self.initialize()

        if not initialized:
            logger.error("❌ Failed to initialize Antibody Agent")
            sys.exit(1)

        # Start agent
        logger.info("📡 Starting NATS listener...")
        started = await self.agent.start()

        if not started:
            logger.error("❌ Failed to start Antibody Agent")
            sys.exit(1)

        # Print status
        logger.info(
            """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║  ✅ ANTIBODY AGENT OPERATIONAL                                ║
║                                                               ║
║  Status: Waiting for failure events...                        ║
║  NATS Channel: brain.rf_classified                            ║
║  Listening for ML Pipeline failures                           ║
║                                                               ║
║  Recovery Modes:                                              ║
║  • Tier 1: Redis Cache (0.8s)   [O(1) lookups]               ║
║  • Tier 2: Neo4j Graph (2s)     [Similarity search]          ║
║  • Tier 3: PostgreSQL (18s)     [Historical + Learning]      ║
║  • Emergency: Hardcoded fallback [Always works]              ║
║                                                               ║
║  Health: Ready for chaos and recovery testing!               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """
        )

        # Run indefinitely
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏹️  Shutting down...")
            await self.agent.stop()


async def main():
    """Main entry point"""
    app = AntibodyAgentApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
