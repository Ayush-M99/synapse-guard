"""
DARWIN Knowledge Graph Seed Script — Full Schema (§6)

6 Node Types: AttackFamily, Strand, Signature, Recovery, Service, Generation
10+ Relationship Types: BELONGS_TO, MUTATED_FROM, HAS_SIGNATURE, TRIGGERS,
    COUNTERED_BY, DEPENDS_ON, TARGETED_BY, APPLIES_TO, INTRODUCED, DEVELOPED, DEFEATED_IN

Pre-loads all 18 strands with full properties before hackathon.
"""

import os
import time
from neo4j import GraphDatabase

from constants import STRANDS, ServiceConfig, DBConfig


def wait_for_neo4j(uri, user, password, timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            print("✅ Connected to Neo4j!")
            return driver
        except Exception:
            print("⏳ Waiting for Neo4j to be ready...")
            time.sleep(5)
    raise Exception("Timeout waiting for Neo4j!")


def seed_knowledge_graph(driver):
    with driver.session() as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("🧹 Cleared existing graph data")

        # ─── 1. Attack Families (5 families from §6) ───────────
        families = [
            {"name": "pod_crash",  "generation": 1, "danger_level": "high"},
            {"name": "network",    "generation": 1, "danger_level": "high"},
            {"name": "resource",   "generation": 1, "danger_level": "medium"},
            {"name": "timing",     "generation": 2, "danger_level": "critical"},
            {"name": "cost",       "generation": 1, "danger_level": "low"},
        ]
        for f in families:
            session.run("""
                MERGE (:AttackFamily {
                    name: $name,
                    generation: $generation,
                    danger_level: $danger_level
                })
            """, **f)
        print(f"  ✓ {len(families)} AttackFamily nodes created")

        # ─── 2. Strands (18 strands from §9) ───────────────────
        # Full strand properties from §6
        strand_details = {
            "pod_crash_A": {"camouflage": False, "timing_dependent": False, "blast_radius": ["payment-service"],
                           "avg_detection_time_ms": 2000, "avg_recovery_time_ms": 18000},
            "pod_crash_B": {"camouflage": False, "timing_dependent": False, "blast_radius": ["payment-service", "order-service"],
                           "avg_detection_time_ms": 3000, "avg_recovery_time_ms": 22000},
            "pod_crash_C": {"camouflage": False, "timing_dependent": False, "blast_radius": ["payment-service"],
                           "avg_detection_time_ms": 5000, "avg_recovery_time_ms": 20000},
            "pod_crash_D": {"camouflage": False, "timing_dependent": False, "blast_radius": ["payment-service"],
                           "avg_detection_time_ms": 4000, "avg_recovery_time_ms": 25000},
            "network_A":   {"camouflage": False, "timing_dependent": False, "blast_radius": ["api-gateway"],
                           "avg_detection_time_ms": 3000, "avg_recovery_time_ms": 15000},
            "network_B":   {"camouflage": False, "timing_dependent": False, "blast_radius": ["api-gateway"],
                           "avg_detection_time_ms": 5000, "avg_recovery_time_ms": 18000},
            "network_C":   {"camouflage": False, "timing_dependent": False, "blast_radius": ["api-gateway"],
                           "avg_detection_time_ms": 8000, "avg_recovery_time_ms": 20000},
            "network_D":   {"camouflage": False, "timing_dependent": False, "blast_radius": ["payment-service", "inventory-service"],
                           "avg_detection_time_ms": 4000, "avg_recovery_time_ms": 25000},
            "resource_A":  {"camouflage": False, "timing_dependent": False, "blast_radius": ["auth-service"],
                           "avg_detection_time_ms": 5000, "avg_recovery_time_ms": 16000},
            "resource_B":  {"camouflage": False, "timing_dependent": False, "blast_radius": ["auth-service"],
                           "avg_detection_time_ms": 6000, "avg_recovery_time_ms": 18000},
            "resource_C":  {"camouflage": False, "timing_dependent": False, "blast_radius": ["auth-service"],
                           "avg_detection_time_ms": 8000, "avg_recovery_time_ms": 20000},
            "resource_D":  {"camouflage": False, "timing_dependent": False, "blast_radius": ["auth-service"],
                           "avg_detection_time_ms": 3000, "avg_recovery_time_ms": 22000},
            "timing_A":    {"camouflage": False, "timing_dependent": True, "blast_radius": ["payment-service"],
                           "avg_detection_time_ms": 2000, "avg_recovery_time_ms": 12000},
            "timing_B":    {"camouflage": False, "timing_dependent": True, "blast_radius": ["order-service"],
                           "avg_detection_time_ms": 3000, "avg_recovery_time_ms": 14000},
            "timing_C":    {"camouflage": False, "timing_dependent": True, "blast_radius": ["notification-service"],
                           "avg_detection_time_ms": 10000, "avg_recovery_time_ms": 20000},
            "cost_A":      {"camouflage": False, "timing_dependent": False, "blast_radius": ["inventory-service"],
                           "avg_detection_time_ms": 15000, "avg_recovery_time_ms": 10000},
            "cost_B":      {"camouflage": False, "timing_dependent": False, "blast_radius": ["notification-service"],
                           "avg_detection_time_ms": 12000, "avg_recovery_time_ms": 8000},
            "camouflage_A": {"camouflage": True, "timing_dependent": False, "blast_radius": ["auth-service"],
                           "avg_detection_time_ms": 30000, "avg_recovery_time_ms": 25000},
        }

        # Recovery actions per family
        recovery_map = {
            "pod_crash": {"actions": ["restart_pod", "scale_replicas", "alert_brain"],
                         "priority_order": [1, 2, 3], "estimated_time_ms": 8000,
                         "conflicts_with": ["rec_hpa_scale"]},
            "network":   {"actions": ["reroute_traffic", "restart_pod", "alert_brain"],
                         "priority_order": [1, 2, 3], "estimated_time_ms": 10000,
                         "conflicts_with": []},
            "resource":  {"actions": ["scale_replicas", "restart_pod", "alert_brain"],
                         "priority_order": [1, 2, 3], "estimated_time_ms": 12000,
                         "conflicts_with": ["rec_pod_crash"]},
            "timing":    {"actions": ["scale_replicas", "isolate_network", "restart_pod"],
                         "priority_order": [1, 2, 3], "estimated_time_ms": 6000,
                         "conflicts_with": []},
            "cost":      {"actions": ["scale_down", "alert_brain"],
                         "priority_order": [1, 2], "estimated_time_ms": 5000,
                         "conflicts_with": []},
        }

        # Signature patterns per family
        signature_patterns = {
            "pod_crash": {"cpu_delta": "low", "memory_delta": "spike", "error_rate_delta": "high",
                         "restart_count_delta": "high", "latency_delta": "medium"},
            "network":   {"cpu_delta": "low", "memory_delta": "low", "error_rate_delta": "high",
                         "restart_count_delta": "low", "latency_delta": "spike"},
            "resource":  {"cpu_delta": "spike", "memory_delta": "high", "error_rate_delta": "medium",
                         "restart_count_delta": "low", "latency_delta": "high"},
            "timing":    {"cpu_delta": "medium", "memory_delta": "medium", "error_rate_delta": "spike",
                         "restart_count_delta": "high", "latency_delta": "medium"},
            "cost":      {"cpu_delta": "medium", "memory_delta": "low", "error_rate_delta": "low",
                         "restart_count_delta": "low", "latency_delta": "low"},
        }

        for strand_id, base in STRANDS.items():
            details = strand_details.get(strand_id, {})
            family = base["family"]
            gen = base["gen"]
            desc = base.get("description", "")

            # Create Strand node with full properties (§6)
            session.run("""
                MERGE (st:Strand {id: $id})
                SET st.description = $description,
                    st.generation = $gen,
                    st.mutation_of = null,
                    st.camouflage = $camouflage,
                    st.timing_dependent = $timing_dependent,
                    st.blast_radius = $blast_radius,
                    st.avg_detection_time_ms = $avg_detection_time_ms,
                    st.avg_recovery_time_ms = $avg_recovery_time_ms
                WITH st
                MATCH (f:AttackFamily {name: $family})
                MERGE (st)-[:BELONGS_TO]->(f)
            """,
                id=strand_id, description=desc, gen=gen, family=family,
                camouflage=details.get("camouflage", False),
                timing_dependent=details.get("timing_dependent", False),
                blast_radius=details.get("blast_radius", []),
                avg_detection_time_ms=details.get("avg_detection_time_ms", 5000),
                avg_recovery_time_ms=details.get("avg_recovery_time_ms", 18000),
            )

            # Create Signature node (§6)
            sig_pattern = signature_patterns.get(family, {})
            session.run("""
                MATCH (st:Strand {id: $id})
                MERGE (sig:Signature {id: 'sig_' + $id})
                SET sig.rf_label = $family,
                    sig.rf_confidence_threshold = 0.85,
                    sig.cpu_delta = $cpu_delta,
                    sig.memory_delta = $memory_delta,
                    sig.error_rate_delta = $error_rate_delta,
                    sig.restart_count_delta = $restart_count_delta,
                    sig.latency_delta = $latency_delta
                MERGE (st)-[:HAS_SIGNATURE]->(sig)
            """,
                id=strand_id, family=family,
                **sig_pattern,
            )

            # Create Recovery node (§6)
            rec_info = recovery_map.get(family, {})
            session.run("""
                MATCH (st:Strand {id: $id})
                MATCH (sig:Signature {id: 'sig_' + $id})
                MERGE (rec:Recovery {id: 'rec_' + $id})
                SET rec.actions = $actions,
                    rec.priority_order = $priority_order,
                    rec.estimated_time_ms = $estimated_time_ms,
                    rec.conflicts_with = $conflicts_with,
                    rec.requires_services = ['k8s_api']
                MERGE (sig)-[:TRIGGERS]->(rec)
                MERGE (st)-[:COUNTERED_BY]->(rec)
            """,
                id=strand_id,
                actions=rec_info.get("actions", ["restart_pod"]),
                priority_order=rec_info.get("priority_order", [1]),
                estimated_time_ms=rec_info.get("estimated_time_ms", 8000),
                conflicts_with=rec_info.get("conflicts_with", []),
            )

        print(f"  ✓ {len(STRANDS)} Strand nodes + Signatures + Recoveries created")

        # ─── 3. Service nodes with criticality & priority (§6) ──
        for svc_name, svc_config in ServiceConfig.SERVICES.items():
            session.run("""
                MERGE (svc:Service {name: $name})
                SET svc.criticality = $criticality,
                    svc.replicas_min = $replicas_min,
                    svc.replicas_max = $replicas_max,
                    svc.recovery_priority = $priority
            """,
                name=svc_name,
                criticality=svc_config["criticality"],
                replicas_min=svc_config["replicas_min"],
                replicas_max=svc_config["replicas_max"],
                priority=svc_config["priority"],
            )

        # Service dependencies (blast radius traversal)
        deps = [
            ("api-gateway", "auth-service"),
            ("api-gateway", "payment-service"),
            ("api-gateway", "order-service"),
            ("payment-service", "order-service"),
            ("order-service", "inventory-service"),
            ("order-service", "notification-service"),
            ("payment-service", "notification-service"),
        ]
        for a, b in deps:
            session.run("""
                MATCH (a:Service {name: $a}), (b:Service {name: $b})
                MERGE (a)-[:DEPENDS_ON]->(b)
            """, a=a, b=b)

        # Link strands to target services (TARGETED_BY)
        for strand_id, details in strand_details.items():
            for svc in details.get("blast_radius", []):
                session.run("""
                    MATCH (svc:Service {name: $svc}), (st:Strand {id: $id})
                    MERGE (svc)-[:TARGETED_BY]->(st)
                """, svc=svc, id=strand_id)

        # Link recoveries to services (APPLIES_TO)
        for strand_id, details in strand_details.items():
            for svc in details.get("blast_radius", []):
                session.run("""
                    MATCH (rec:Recovery {id: 'rec_' + $id}), (svc:Service {name: $svc})
                    MERGE (rec)-[:APPLIES_TO]->(svc)
                """, id=strand_id, svc=svc)

        print(f"  ✓ {len(ServiceConfig.SERVICES)} Service nodes + dependencies created")

        # ─── 4. Generation snapshot nodes (§6) ──────────────────
        generations = [
            {"virus_gen": 1, "antibody_gen": 1, "avg_recovery_time_ms": 18000,
             "unknown_strand_rate": 0.0, "resilience_score": 340},
            {"virus_gen": 2, "antibody_gen": 2, "avg_recovery_time_ms": 8200,
             "unknown_strand_rate": 0.15, "resilience_score": 580},
            {"virus_gen": 3, "antibody_gen": 3, "avg_recovery_time_ms": 1800,
             "unknown_strand_rate": 0.0, "resilience_score": 847},
        ]
        for g in generations:
            session.run("""
                CREATE (gen:Generation {
                    virus_gen: $virus_gen,
                    antibody_gen: $antibody_gen,
                    avg_recovery_time_ms: $avg_recovery_time_ms,
                    unknown_strand_rate: $unknown_strand_rate,
                    resilience_score: $resilience_score,
                    timestamp: datetime()
                })
            """, **g)

        # Link generations to strands (INTRODUCED / DEVELOPED)
        session.run("""
            MATCH (gen:Generation {virus_gen: 1}), (st:Strand)
            WHERE st.generation = 1
            MERGE (gen)-[:INTRODUCED]->(st)
        """)
        session.run("""
            MATCH (gen:Generation {virus_gen: 2}), (st:Strand)
            WHERE st.generation = 2
            MERGE (gen)-[:INTRODUCED]->(st)
        """)
        session.run("""
            MATCH (gen:Generation {virus_gen: 3}), (st:Strand)
            WHERE st.generation = 3
            MERGE (gen)-[:INTRODUCED]->(st)
        """)

        # Link generations to recoveries (DEVELOPED)
        session.run("""
            MATCH (gen:Generation), (rec:Recovery)
            MERGE (gen)-[:DEVELOPED]->(rec)
        """)

        print(f"  ✓ {len(generations)} Generation nodes created")

    print("\n🧠 Brain Graph fully seeded!")
    print(f"   → {len(STRANDS)} strands across 5 families")
    print(f"   → {len(ServiceConfig.SERVICES)} services with dependency graph")
    print(f"   → {len(generations)} generation snapshots")
    print(f"   → Full Signature → Recovery → Service wiring")


if __name__ == "__main__":
    URI = os.getenv("NEO4J_URI", DBConfig.NEO4J_URI)
    try:
        driver = wait_for_neo4j(URI, DBConfig.NEO4J_USER, DBConfig.NEO4J_PASS)
        seed_knowledge_graph(driver)
        driver.close()
    except Exception as e:
        print(f"Error seeding: {e}")
