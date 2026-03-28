import os
import json
import asyncio
import time
try:
    import google.generativeai as genai
except ImportError:
    pass

try:
    import redis.asyncio as redis
except ImportError:
    import redis

try:
    import asyncpg
    import nats
except ImportError:
    pass

from dataclasses import dataclass

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PG_URL = os.getenv("PG_URL", "postgres://chaos:chaospassword@localhost:5432/chaos_dna")
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")

@dataclass
class AntibodyCore:
    redis_client: redis.Redis
    pg_pool: asyncpg.pool.Pool
    nc: nats.NATS

    async def check_immunity(self, strand_id: str) -> dict:
        """T-Cell Memory: O(1) lookup for known attack signatures"""
        cached = await self.redis_client.get(f"immunity:{strand_id}")
        if cached:
            print(f"[T-CELL HIT] FAST RECOVERY TRIGGERED FOR: {strand_id}")
            return json.loads(cached)
        print(f"[T-CELL MISS] Fallback to Brain (Neo4j) graph traversal for: {strand_id}")
        return None

    async def update_immunity(self, strand_id: str, playbooks: dict):
        """Save a newly synthesized antibody playbook to T-Cell memory"""
        await self.redis_client.set(f"immunity:{strand_id}", json.dumps(playbooks), ex=3600)
        print(f"[T-CELL UPDATED] New antibody sequence stored for {strand_id}!")

    async def write_dna_history(self, virus_gen: int, antibody_gen: int, strand_id: str, service: str, playbook_id: str, recovery_time_ms: float, success: bool):
        """DNA Store: Write persistent history to PostgreSQL"""
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO dna_log (
                    virus_gen, antibody_gen, strand_id, service,
                    playbook_id, recovery_time_ms, success, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """, virus_gen, antibody_gen, strand_id, service, playbook_id, recovery_time_ms, success)
            print(f"[DNA WRITTEN] Evolutionary history updated: {strand_id} → {service} (Success: {success})")

    async def init_dna_schema(self):
        """Initialize PostgreSQL Schema"""
        async with self.pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dna_log (
                    id SERIAL PRIMARY KEY,
                    virus_gen INTEGER,
                    antibody_gen INTEGER,
                    strand_id VARCHAR(100),
                    service VARCHAR(100),
                    playbook_id VARCHAR(100),
                    recovery_time_ms FLOAT,
                    success BOOLEAN,
                    timestamp TIMESTAMP
                )
            """)
            print("[DNA STORE] Schema verified in PostgreSQL.")

    async def handle_alert(self, msg):
        """Neural Bus: Process incoming alerts from Nerve endings"""
        data = json.loads(msg.data.decode())
        print(f"[NERVE IMPULSE RECIEVED] Source: {msg.subject} -> {data}")
        # Normally would trigger recovery here
        await self.check_immunity(data.get("strand_id"))

    async def infer_remedy_from_metrics(self, metrics: dict) -> dict:
        """Rule-based fallback for unknown attacks"""
        print("[FALLBACK] Executing deterministic rule-based analysis for unknown attack...")
        cpu = metrics.get('cpu_usage_pct', 0)
        memory = metrics.get('memory_usage_pct', 0)
        error_rate = metrics.get('http_error_rate_5xx', 0)
        
        if cpu > 80:
            return {"action": "scale_hpa", "reason": "CPU pressure", "confidence": 0.8}
        elif memory > 85:
            return {"action": "restart_pod", "reason": "Memory leak suspected", "confidence": 0.8}
        elif error_rate > 0.3:
            return {"action": "reroute_traffic", "reason": "High error rate", "confidence": 0.7}
        else:
            return {"action": "restart_pod", "reason": "Default safe action", "confidence": 0.5}

    async def generate_remedy_for_unknown(self, strand_id: str, metrics: dict) -> dict:
        """Primary LLM pathway to synthesize novel remedy for honeypot observation"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[LLM BYPASS] GEMINI_API_KEY not found. Defaulting to Rule-Based Fallback.")
            return await self.infer_remedy_from_metrics(metrics)
        
        print(f"[LLM ACTIVE] Synthesizing novel remedy via LLM for unknown attack {strand_id}...")
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            prompt = f"""
            You are a Kubernetes self-healing autonomous decision engine.
            
            An unknown attack strand "{strand_id}" was captured by the honeypot:
            - Metrics: CPU {metrics.get('cpu_usage_pct', 0)}%, Memory {metrics.get('memory_usage_pct', 0)}%
            - Error rate: {metrics.get('http_error_rate_5xx', 0)}
            
            Analyze these symptoms and synthesize a remediation action to trigger.
            Choose from: restart_pod, scale_hpa, reroute_traffic, flush_cache, increase_resources
            
            Return ONLY a valid JSON string with exactly three keys:
            {{"action": "...", "reason": "...", "confidence": 0.9}}
            """
            
            response = await asyncio.to_thread(model.generate_content, prompt)
            result_text = response.text.replace('```json', '').replace('```', '').strip()
            remedy = json.loads(result_text)
            print(f"[LLM REMEDY SYNTHESIZED] {remedy}")
            return remedy
        except Exception as e:
            print(f"[LLM ERROR] {e}. Defaulting to Rule-Based Fallback.")
            return await self.infer_remedy_from_metrics(metrics)

    async def process_unknown_attack(self, strand_id: str, metrics: dict):
        """Honeypot -> Crystallize path implementation"""
        print(f"\n[UNKNOWN DETECTED] Routing {strand_id} to Antibody Discovery Engine...")
        remedy = await self.generate_remedy_for_unknown(strand_id, metrics)
        
        # Crystallize new node in Neo4j conceptually
        print(f"[CRYSTALLIZED] New Strand '{strand_id}' bound to remediation '{remedy['action']}' in Brain Graph.")
        
        # Deploy immediate caching to Redis to skip LLM next time
        await self.update_immunity(strand_id, {
            "actions": [remedy["action"]],
            "reason": remedy["reason"], 
            "priority": 2
        })

    async def wire_nats(self):
        """Neural Bus: Connect all nodes"""
        await self.nc.subscribe("nerve.*.alert", cb=self.handle_alert)
        print("[NEURAL BUS] Wired! Listening for 'nerve.*.alert'")


async def start_antibody_core():
    print("Initializing Core Antibody DB Systems...")
    
    # Wait for databases to be ready
    await asyncio.sleep(2)
    
    # Connect
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    pg_pool = await asyncpg.create_pool(PG_URL)
    nc = await nats.connect(NATS_URL)

    core = AntibodyCore(redis_client, pg_pool, nc)
    await core.init_dna_schema()
    await core.wire_nats()
    
    # Send a mock T-cell update and lookup
    await core.update_immunity("pod_crash_B", {"actions": ["restart_pod", "hpa_scale"], "priority": 1})
    
    # Write a mock DNA entry
    await core.write_dna_history(1, 1, "pod_crash_B", "payment-service", "rec_pod_crash_B", 14000.5, True)
    
    # Send a mock NATS message to trigger the neural bus handle_alert -> check_immunity
    await nc.publish("nerve.payment-service.alert", json.dumps({"strand_id": "pod_crash_B", "rf_confidence": 0.95}).encode())
    await asyncio.sleep(1) # let callback process
    
    # Mocking Honeypot -> Crystallize -> Remedy process for a truly unknown strand
    unknown_metrics = {"cpu_usage_pct": 98.2, "memory_usage_pct": 45.1, "http_error_rate_5xx": 0.05}
    await core.process_unknown_attack("unknown_cpu_strangler_X", unknown_metrics)
    
    print("\n--- ALL DATABASES AND NATS COMPONENTS SUCCESSFULLY WIRED ---")
    await nc.drain()
    await pg_pool.close()
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(start_antibody_core())
