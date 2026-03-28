"""
DARWIN Platform — Shared Constants
Single source of truth for NATS subjects, service config, and attack families.
Imported by ALL agents. Section §13 of MASTER_SYSTEM_DESIGN.md.
"""

# ═══════════════════════════════════════════════════════════════
# NATS SUBJECT MAP — Final Version (§13)
# ═══════════════════════════════════════════════════════════════

class NATSSubjects:
    """Complete NATS subject hierarchy."""

    # Nerve endings → ML pipeline / Decision Engine
    NERVE_METRICS   = "nerve.{service}.metrics"
    NERVE_ALERT     = "nerve.{service}.alert"

    # Decision Engine listens on:
    LSTM_PREDICTION       = "lstm.prediction"
    HONEYPOT_CRYSTALLIZED = "honeypot.crystallized"

    # Decision Engine publishes:
    BRAIN_UPDATE        = "brain.update"
    RECOVERY_STARTED    = "recovery.{service}.started"
    DNA_LOG             = "dna.log"
    IMMUNITY_WRITE      = "immunity.write"

    # Virus Agent publishes:
    VIRUS_INJECT           = "virus.inject"
    VIRUS_GENERATION_EVENT = "virus.generation.event"

    # Dashboard subscriptions (via WebSocket bridge):
    SERVICES_HEALTH = "services.health"


# ═══════════════════════════════════════════════════════════════
# BRAIN UPDATE EVENT TYPES
# ═══════════════════════════════════════════════════════════════

class BrainEvents:
    ATTACK_DETECTED      = "attack_detected"
    RECOVERY_STARTED     = "recovery_started"
    RECOVERY_COMPLETE    = "recovery_complete"
    RECOVERY_PREEMPTED   = "recovery_preempted"
    PREEMPTIVE_ACTION    = "preemptive_action"
    NEW_STRAND_DISCOVERED = "new_strand_discovered"
    HONEYPOT_DEPLOYED    = "honeypot_deployed"
    HONEYPOT_OBSERVING   = "honeypot_observing"
    MUTATION             = "mutation"
    TCELL_HIT            = "tcell_hit"


# ═══════════════════════════════════════════════════════════════
# ATTACK FAMILIES & STRANDS — 5 Families, 18 Strands (§9)
# ═══════════════════════════════════════════════════════════════

class AttackFamily:
    POD_CRASH  = "pod_crash"
    NETWORK    = "network"
    RESOURCE   = "resource"
    TIMING     = "timing"
    COST       = "cost"

    ALL = [POD_CRASH, NETWORK, RESOURCE, TIMING, COST]


# 18 strands organized by family and generation
STRANDS = {
    # Family 1 — Pod Crash (Gen 1, 4 strands)
    "pod_crash_A": {"family": "pod_crash", "gen": 1, "description": "Single pod OOMKill"},
    "pod_crash_B": {"family": "pod_crash", "gen": 1, "description": "Cascade kill (payment → order)"},
    "pod_crash_C": {"family": "pod_crash", "gen": 1, "description": "Kill under high load"},
    "pod_crash_D": {"family": "pod_crash", "gen": 1, "description": "Kill + corrupt ConfigMap"},

    # Family 2 — Network (Gen 1, 4 strands)
    "network_A":   {"family": "network", "gen": 1, "description": "2000ms fixed latency (Istio)"},
    "network_B":   {"family": "network", "gen": 1, "description": "30% packet loss + 500ms latency"},
    "network_C":   {"family": "network", "gen": 1, "description": "DNS poisoning simulation"},
    "network_D":   {"family": "network", "gen": 1, "description": "Network partition (isolate services)"},

    # Family 3 — Resource Pressure (Gen 1, 4 strands)
    "resource_A":  {"family": "resource", "gen": 1, "description": "CPU stress pod"},
    "resource_B":  {"family": "resource", "gen": 1, "description": "Memory leak simulation"},
    "resource_C":  {"family": "resource", "gen": 1, "description": "Disk fill to 95%"},
    "resource_D":  {"family": "resource", "gen": 1, "description": "CPU + memory + fd exhaustion combo"},

    # Family 4 — Timing Attacks (Gen 2, 3 strands)
    "timing_A":    {"family": "timing", "gen": 2, "description": "Strike during 50% recovery window"},
    "timing_B":    {"family": "timing", "gen": 2, "description": "Attack failover target"},
    "timing_C":    {"family": "timing", "gen": 2, "description": "Blind monitoring, then attack"},

    # Family 5 — Cost / Camouflage (Gen 3, 3 strands)
    "cost_A":      {"family": "cost", "gen": 1, "description": "Resource waste via unnecessary scaling"},
    "cost_B":      {"family": "cost", "gen": 1, "description": "Trigger excessive logging"},
    "camouflage_A": {"family": "resource", "gen": 3, "description": "Slow burn CPU degradation 2%/5min"},
}


# ═══════════════════════════════════════════════════════════════
# SERVICE REGISTRY — The 6 Microservices / The Patient (§4)
# ═══════════════════════════════════════════════════════════════

class ServiceConfig:
    """Service criticality and priority mapping from §8."""

    SERVICES = {
        "payment-service":      {"criticality": "critical", "priority": 1, "replicas_min": 2, "replicas_max": 6, "db": "postgresql"},
        "auth-service":         {"criticality": "critical", "priority": 1, "replicas_min": 2, "replicas_max": 6, "db": "postgresql"},
        "api-gateway":          {"criticality": "high",     "priority": 2, "replicas_min": 2, "replicas_max": 5, "db": None},
        "order-service":        {"criticality": "high",     "priority": 2, "replicas_min": 2, "replicas_max": 5, "db": "postgresql"},
        "inventory-service":    {"criticality": "medium",   "priority": 3, "replicas_min": 2, "replicas_max": 4, "db": "redis"},
        "notification-service": {"criticality": "low",      "priority": 4, "replicas_min": 1, "replicas_max": 3, "db": None},
    }

    SERVICE_NAMES = list(SERVICES.keys())

    @classmethod
    def get_priority(cls, service: str) -> int:
        return cls.SERVICES.get(service, {}).get("priority", 4)

    @classmethod
    def get_criticality(cls, service: str) -> str:
        return cls.SERVICES.get(service, {}).get("criticality", "low")


# ═══════════════════════════════════════════════════════════════
# ML MODEL CONFIGURATION (§5)
# ═══════════════════════════════════════════════════════════════

class MLConfig:
    # Isolation Forest
    IF_ANOMALY_THRESHOLD = 0.65
    IF_SUSTAINED_SCRAPES = 3        # 3 consecutive scrapes = 15 seconds
    IF_SCRAPE_INTERVAL = 5          # seconds

    # Random Forest confidence thresholds
    RF_KNOWN_THRESHOLD    = 0.85    # KNOWN state
    RF_PROBABLE_THRESHOLD = 0.60    # PROBABLE state
    # Below 0.60 = UNKNOWN state

    # LSTM
    LSTM_CONFIDENCE_THRESHOLD = 0.70
    LSTM_SEQUENCE_LENGTH = 10

    # Feature vector (7 features per service)
    FEATURE_NAMES = [
        "cpu_usage_pct",
        "memory_usage_pct",
        "http_error_rate_5xx",
        "request_latency_p99",
        "pod_restart_count_delta",
        "network_rx_bytes_delta",
        "network_tx_bytes_delta",
    ]


# ═══════════════════════════════════════════════════════════════
# ATTACK STATE MACHINE (§8)
# ═══════════════════════════════════════════════════════════════

class AttackState:
    KNOWN     = "KNOWN"      # RF >= 0.85 — execute playbook immediately
    PROBABLE  = "PROBABLE"   # RF 0.60-0.85 — playbook + partial honeypot
    UNKNOWN   = "UNKNOWN"    # RF < 0.60 — full honeypot path
    PREDICTED = "PREDICTED"  # LSTM fires — preemptive action


# ═══════════════════════════════════════════════════════════════
# MUTATION TRIGGERS (§9)
# ═══════════════════════════════════════════════════════════════

MUTATION_TRIGGERS = {
    "avg_recovery_time_ms < 3000":  "escalate_same_family",
    "avg_recovery_time_ms < 1000":  "switch_family",
    "honeypot_deployed == True":    "camouflage_mode",
    "preemptive_action == True":    "timing_attack",
    "unknown_strand_rate == 0.0":   "combo_attack",
}


# ═══════════════════════════════════════════════════════════════
# SYSTEM MODE (§11 — Demo Reliability Layer)
# ═══════════════════════════════════════════════════════════════

class SystemMode:
    LIVE     = "live"       # everything real
    DEMO     = "demo"       # scripted scenarios, real K8s but controlled
    FALLBACK = "fallback"   # pure simulation, no K8s needed


# ═══════════════════════════════════════════════════════════════
# DATABASE CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class DBConfig:
    PG_URL     = "postgres://chaos:chaospassword@localhost:5432/chaos_dna"
    REDIS_URL  = "redis://localhost:6379"
    NEO4J_URI  = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASS = "chaospassword"
    NATS_URL   = "nats://localhost:4222"
