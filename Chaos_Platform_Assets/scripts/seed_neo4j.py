import os
import time
from neo4j import GraphDatabase

def wait_for_neo4j(uri, user, password, timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            print("Successfully connected to Neo4j!")
            return driver
        except Exception as e:
            print("Waiting for Neo4j to be ready...")
            time.sleep(5)
    raise Exception("Timeout waiting for Neo4j!")

def seed_knowledge_graph(driver):
    with driver.session() as session:
        # Clear existing
        session.run("MATCH (n) DETACH DELETE n")

        # 1. Attack Families
        families = ["pod_crash", "network", "resource", "timing", "camouflage"]
        for f in families:
            session.run("MERGE (:AttackFamily {name: $name, generation: 1})", name=f)

        # 2. Configured Strands
        strands = [
            {"id": "pod_crash_A", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_B", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_C", "family": "pod_crash", "gen": 1},
            {"id": "pod_crash_D", "family": "pod_crash", "gen": 1},
            {"id": "network_A",   "family": "network",   "gen": 1},
            {"id": "network_B",   "family": "network",   "gen": 1},
            {"id": "network_C",   "family": "network",   "gen": 1},
            {"id": "network_D",   "family": "network",   "gen": 1},
            {"id": "resource_A",  "family": "resource",  "gen": 1},
            {"id": "resource_B",  "family": "resource",  "gen": 1},
            {"id": "resource_C",  "family": "resource",  "gen": 1},
            {"id": "resource_D",  "family": "resource",  "gen": 1},
            {"id": "timing_A",    "family": "timing",    "gen": 2},
            {"id": "timing_B",    "family": "timing",    "gen": 2},
            {"id": "timing_C",    "family": "timing",    "gen": 2},
            {"id": "camouflage_A","family": "camouflage", "gen": 3},
            {"id": "camouflage_B","family": "camouflage", "gen": 3},
            {"id": "camouflage_C","family": "camouflage", "gen": 3},
        ]
        
        for s in strands:
            # Inject strand definition
            session.run("""
                MERGE (st:Strand {id: $id})
                SET st += $props, st.avg_recovery_time_ms = 18000
                WITH st
                MATCH (f:AttackFamily {name: $family})
                MERGE (st)-[:BELONGS_TO]->(f)
            """, id=s["id"], props=s, family=s["family"])

            # Create mock Signatures and Recoveries per strand
            session.run("""
                MATCH (st:Strand {id: $id})
                MERGE (sig:Signature {id: 'sig_' + $id, rf_label: $family})
                MERGE (st)-[:HAS_SIGNATURE]->(sig)
                
                MERGE (rec:Recovery {id: 'rec_' + $id})
                SET rec.actions = ['restart_pod', 'alert_brain'], rec.priority_order = [1, 2], rec.estimated_time_ms = 8000
                MERGE (sig)-[:TRIGGERS]->(rec)
                MERGE (st)-[:COUNTERED_BY]->(rec)
            """, id=s["id"], family=s["family"])

        # 3. Services and Blast Radius
        services = [
            {"name": "payment-service", "criticality": "critical", "priority": 1},
            {"name": "auth-service", "criticality": "critical", "priority": 1},
            {"name": "api-gateway", "criticality": "high", "priority": 2},
            {"name": "order-service", "criticality": "high", "priority": 2},
            {"name": "inventory-service", "criticality": "medium", "priority": 3},
            {"name": "notification-service", "criticality": "low", "priority": 4},
        ]
        for s in services:
            session.run("""
                MERGE (svc:Service {name: $name})
                SET svc.criticality = $criticality, svc.recovery_priority = $priority
            """, name=s["name"], criticality=s["criticality"], priority=s["priority"])

        # Add explicit dependencies for Graph Traversal via blast radius tracing
        session.run("MATCH (a:Service {name: 'api-gateway'}), (b:Service {name: 'auth-service'}) MERGE (a)-[:DEPENDS_ON]->(b)")
        session.run("MATCH (a:Service {name: 'api-gateway'}), (b:Service {name: 'payment-service'}) MERGE (a)-[:DEPENDS_ON]->(b)")
        session.run("MATCH (a:Service {name: 'payment-service'}), (b:Service {name: 'order-service'}) MERGE (a)-[:DEPENDS_ON]->(b)")
        session.run("MATCH (a:Service {name: 'order-service'}), (b:Service {name: 'inventory-service'}) MERGE (a)-[:DEPENDS_ON]->(b)")
        session.run("MATCH (a:Service {name: 'order-service'}), (b:Service {name: 'notification-service'}) MERGE (a)-[:DEPENDS_ON]->(b)")

    print("Brain Graph successfully injected!")

if __name__ == "__main__":
    URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    AUTH = ("neo4j", "chaospassword")
    try:
        driver = wait_for_neo4j(URI, AUTH[0], AUTH[1])
        seed_knowledge_graph(driver)
        driver.close()
    except Exception as e:
        print(f"Error seeding: {e}")
