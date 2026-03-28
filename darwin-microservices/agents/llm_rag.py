import os
import json
import logging
import google.generativeai as genai

logging.basicConfig(level=logging.INFO, format="[🤖 RAG LLM] %(message)s")
log = logging.getLogger("rag")

# Load environment logic manually to guarantee it reads .env
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v

load_env()
API_KEY = os.getenv("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)

async def synthesize_playbook(strand_id: str, service: str, signature: dict) -> dict:
    """Uses Google Gemini to synthesize a completely custom playbook based on honeypot signature."""
    if not API_KEY:
        log.warning("No LLM available, returning default fallback")
        return {"actions": ["restart_pod"], "reason": "No LLM available, default fallback"}
    
    try:
        log.info(f"Generating custom immune response for {strand_id} using Gemini...")
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        prompt = f"""
        You are DARWIN, an autonomous Chaos Engineering AI. 
        A completely unknown virus mutation '{strand_id}' just crippled the Kubernetes service '{service}'.
        
        Our Honeypot captured this attack signature:
        {json.dumps(signature, indent=2)}

        You must synthesize a Custom Healer Playbook.
        Valid Kubernetes actions you can choose from in an array: 
        ["restart_pod", "scale_replicas", "isolate_network", "flush_cache", "rollback"]
        
        Analyze the signature and return ONLY valid JSON with no markdown formatting whatsoever.
        Format:
        {{
            "actions": ["chosen_action_1", "chosen_action_2"],
            "reason": "Explain exactly why this unique combination counters the mutation."
        }}
        """
        response = await model.generate_content_async(prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
            
        playbook = json.loads(text)
        playbook["source"] = "llm_rag_synthesis"
        log.info(f"✨ Playbook synthesized successfully: {playbook['actions']}")
        return playbook
        
    except Exception as e:
        log.error(f"Failed to generate dynamic playbook: {e}")
        return {"actions": ["restart_pod", "scale_replicas"], "reason": "LLM Synthesis Failed - using conservative default"}
