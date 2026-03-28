"""
DARWIN — Neo4j Knowledge Graph Seeder
Thin wrapper around Chaos_Platform_Assets/scripts/seed_neo4j.py
Adds DARWIN-specific extensions on top of the base seed.

Usage:
    python seed_graph.py
    python seed_graph.py --clear    (clear existing data first)
"""

import os
import sys
import time
import argparse
from pathlib import Path

# Add Chaos_Platform_Assets/scripts to path so we can import seed_neo4j directly
ASSETS_SCRIPTS = Path(__file__).parent / "Chaos_Platform_Assets" / "scripts"
sys.path.insert(0, str(ASSETS_SCRIPTS))

from seed_neo4j import wait_for_neo4j, seed_knowledge_graph

NEO4J_URI  = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "chaospassword")


def extend_knowledge_graph(driver):
    """
    Add DARWIN-specific extensions on top of the base seed:
      - Recovery time history nodes (Generation snapshots)
      - Immune system metadata
    """
    with driver.session() as session:
        # Create initial Generation node (Gen 1 baseline)
        session.run("""
            MERGE (g:Generation {virus_gen: 1})
            SET g.antibody_gen = 1,
                g.avg_recovery_time_ms = 18000,
                g.unknown_strand_rate = 0.0,
                g.resilience_score = 0,
                g.timestamp = datetime()
        """)

        # Link Gen1 to pod_crash family
        session.run("""
            MATCH (g:Generation {virus_gen: 1})
            MATCH (f:AttackFamily {name: 'pod_crash'})
            MERGE (g)-[:INTRODUCED]->(f)
        """)

        print("✅ DARWIN extensions seeded (Generation nodes, relationships)")


def seed_dna_schema(pg_url: str):
    """Ensure PostgreSQL dna_log schema exists (idempotent)."""
    try:
        import asyncio
        import asyncpg

        async def _create():
            pool = await asyncpg.create_pool(pg_url)
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS dna_log (
                        id               SERIAL PRIMARY KEY,
                        virus_gen        INTEGER,
                        antibody_gen     INTEGER,
                        strand_id        VARCHAR(100),
                        service          VARCHAR(100),
                        playbook_id      VARCHAR(100),
                        recovery_time_ms FLOAT,
                        success          BOOLEAN,
                        timestamp        TIMESTAMP DEFAULT NOW()
                    )
                """)
            await pool.close()
            print("✅ PostgreSQL dna_log schema verified")

        asyncio.run(_create())
    except Exception as e:
        print(f"⚠️  PostgreSQL not available: {e} — skipping schema creation")


def main():
    parser = argparse.ArgumentParser(description="DARWIN Knowledge Graph Seeder")
    parser.add_argument("--neo4j-uri",  default=NEO4J_URI)
    parser.add_argument("--user",       default=NEO4J_USER)
    parser.add_argument("--password",   default=NEO4J_PASS)
    parser.add_argument("--pg-url",     default=os.getenv("PG_URL", "postgres://chaos:chaospassword@localhost:5432/chaos_dna"))
    parser.add_argument("--no-pg",      action="store_true", help="Skip PostgreSQL schema")
    parser.add_argument("--clear",      action="store_true", help="Clear all graph data before seeding")
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  DARWIN Knowledge Graph Seeder")
    print("=" * 55)
    print(f"  Neo4j:     {args.neo4j_uri}")
    print(f"  Auth:      {args.user}/***")
    print("=" * 55 + "\n")

    # ── Seed Neo4j ────────────────────────────────────────────────────────────
    driver = wait_for_neo4j(args.neo4j_uri, args.user, args.password, timeout=60)

    if args.clear:
        print("🗑️  Clearing existing graph data...")
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    print("🧬 Seeding base knowledge graph (18 strands, 5 families)...")
    seed_knowledge_graph(driver)

    print("🔬 Adding DARWIN extensions...")
    extend_knowledge_graph(driver)

    driver.close()
    print("\n✅ Neo4j knowledge graph fully seeded!")

    # ── Seed PostgreSQL ───────────────────────────────────────────────────────
    if not args.no_pg:
        print("\n📊 Verifying PostgreSQL schema...")
        seed_dna_schema(args.pg_url)

    print("\n🚀 Ready! Run: python demo.py 1  (or 2, 3, full)")


if __name__ == "__main__":
    main()
