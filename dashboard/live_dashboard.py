"""
DARWIN Live Dashboard
=====================
Rich terminal UI + Matplotlib live graphs — no browser, no Node.js needed.

Two windows open simultaneously:
  1. Terminal: Rich live panel (Battle Feed, Status table, Score, Immunity cache)
  2. Matplotlib: 4-subplot live figure
     [Brain Map]  [Anomaly Scores]
     [Timeline]   [Resilience Score Gauge]

Subscribes to NATS subjects and updates in real time.
Run: python -m dashboard.live_dashboard
"""

import asyncio
import json
import math
import os
import sys
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

# ── Third-party ───────────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("TkAgg")   # works on Windows without display server
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.animation as animation
import networkx as nx
import nats
from rich import print as rprint
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
NATS_URL      = os.getenv("NATS_URL", "nats://localhost:4222")
REFRESH_HZ    = float(os.getenv("DASHBOARD_REFRESH", "1.0"))
MAX_FEED      = 30    # max lines in battle feed

SERVICES = [
    "auth-service",
    "api-gateway",
    "order-service",
    "payment-service",
    "inventory-service",
    "notification-service",
]

ATTACK_FAMILIES = ["pod_crash", "network", "resource", "timing", "camouflage"]

# Service dependency graph edges (for Brain Map)
SERVICE_EDGES = [
    ("api-gateway",     "auth-service"),
    ("api-gateway",     "payment-service"),
    ("payment-service", "order-service"),
    ("order-service",   "inventory-service"),
    ("order-service",   "notification-service"),
]

# ── Color maps ────────────────────────────────────────────────────────────────
NODE_COLORS = {
    "healthy":    "#22c55e",   # green
    "attacked":   "#ef4444",   # red
    "healing":    "#f59e0b",   # amber
    "preemptive": "#f97316",   # orange (LSTM prediction)
    "discovered": "#a855f7",   # purple (new honeypot strand)
    "unknown":    "#64748b",   # slate
}

FAMILY_COLORS = {
    "pod_crash":  "#ef4444",
    "network":    "#3b82f6",
    "resource":   "#f97316",
    "timing":     "#8b5cf6",
    "camouflage": "#10b981",
    "unknown":    "#64748b",
}

EVENT_ICONS = {
    "attack_detected":      "🦠",
    "cusum_drift":          "📡",
    "rf_classified":        "🧠",
    "recovery_started":     "💉",
    "recovery_complete":    "✅",
    "recovery_preempted":   "⚠️ ",
    "preemptive_action":    "🛡️ ",
    "lstm_prediction":      "🔮",
    "new_strand_discovered":"🍯",
    "honeypot_deployed":    "🪝",
    "t_cell_hit":           "⚡",
    "connected":            "🔌",
    "mutation":             "🧬",
    "virus_inject":         "🦠",
    "default":              "ℹ️ ",
}

# ── Shared state (written by NATS thread, read by render threads) ─────────────
class DarwinState:
    def __init__(self):
        self.lock = threading.Lock()

        # Per-service state
        self.service_state:  dict[str, str]   = {s: "healthy" for s in SERVICES}
        self.anomaly_scores: dict[str, float] = {s: 0.0 for s in SERVICES}
        self.rf_labels:      dict[str, str]   = {s: "—"   for s in SERVICES}

        # Battle feed
        self.battle_feed: deque[str] = deque(maxlen=MAX_FEED)

        # Evolutionary timeline data
        self.generations: list[dict] = [
            {"gen": 1, "avg_ms": 18000, "unknown_rate": 0.0},
        ]

        # Resilience score
        self.resilience_score = 0
        self.human_interventions = 0
        self.recovery_count = 0
        self.total_recovery_ms = 0.0
        self.successful_recoveries = 0

        # Virus / antibody generation
        self.virus_gen    = 1
        self.antibody_gen = 1

        # LSTM prediction
        self.lstm_prediction = None   # {"family": "...", "confidence": 0.78}

        # Immunity cache hits
        self.t_cell_hits = 0
        self.t_cell_misses = 0

        # Strand history (for brain map satellite nodes)
        self.discovered_strands: list[str] = []

        # Running avg recovery time per gen (updated on recovery_complete)
        self._gen_ms_acc: dict[int, list] = defaultdict(list)

    # ── Updaters called from NATS thread ─────────────────────────────────────

    def on_event(self, subject: str, data: dict):
        with self.lock:
            event = data.get("event", subject.split(".")[-1])
            service = data.get("service", "system")
            ts = datetime.now().strftime("%H:%M:%S")

            # Route event
            if event == "attack_detected":
                self.service_state[service] = "attacked"
                score = data.get("anomaly_score", 0.0)
                label = data.get("rf_label", "unknown")
                self.anomaly_scores[service] = score
                self.rf_labels[service]      = label
                conf = data.get("rf_confidence", 0.0)
                state = data.get("attack_state", "KNOWN")
                self._feed(ts, "attack_detected",
                    f"[bold red]{service}[/] attacked — [yellow]{label}[/] "
                    f"[dim]({conf:.0%} conf, {state})[/]")

            elif event == "cusum_drift":
                self._feed(ts, "cusum_drift",
                    f"[yellow]{service}[/] slow drift detected (CUSUM)")

            elif event in ("recovery_started", "recovery.started"):
                self.service_state[service] = "healing"
                self._feed(ts, "recovery_started",
                    f"[cyan]{service}[/] recovery started")

            elif event in ("recovery_complete", "recovery_complete"):
                self.service_state[service] = "healthy"
                self.anomaly_scores[service] = 0.0
                ms = data.get("recovery_time_ms", 0)
                self.recovery_count += 1
                self.total_recovery_ms += ms
                self.successful_recoveries += 1
                self._recalc_resilience()
                self._feed(ts, "recovery_complete",
                    f"[green]{service}[/] recovered in [bold]{ms/1000:.1f}s[/]")
                # Update generation stats
                gen = data.get("virus_gen", self.virus_gen)
                self._gen_ms_acc[gen].append(ms)
                self._refresh_timeline()

            elif event == "preemptive_action":
                self.lstm_prediction = {
                    "family":     data.get("predicted_family", "?"),
                    "confidence": data.get("lstm_confidence", 0.0),
                }
                targets = data.get("services", [service])
                for svc in targets:
                    if svc in self.service_state:
                        self.service_state[svc] = "preemptive"
                self._feed(ts, "preemptive_action",
                    f"[orange1]LSTM pre-scale[/] → [bold]{', '.join(targets)}[/] "
                    f"[dim]({data.get('lstm_confidence',0):.0%})[/]")

            elif event == "lstm_prediction":
                self.lstm_prediction = {
                    "family":     data.get("predicted_family", "?"),
                    "confidence": data.get("lstm_confidence", 0.0),
                }
                self._feed(ts, "lstm_prediction",
                    f"[magenta]LSTM[/] predicts [bold]{data.get('predicted_family')}[/] "
                    f"[dim]({data.get('lstm_confidence',0):.0%})[/]")

            elif event == "new_strand_discovered":
                sid = data.get("strand_id", "unknown")
                fam = data.get("family", "?")
                self.discovered_strands.append(sid)
                self._recalc_resilience()
                self._feed(ts, "new_strand_discovered",
                    f"[purple]New strand[/] crystallized: [bold]{sid}[/] → {fam}")

            elif event in ("honeypot_deployed", "honeypot_observing"):
                self._feed(ts, "honeypot_deployed",
                    f"[yellow]Honeypot deployed[/] for {service}")

            elif subject.startswith("virus.inject"):
                strand = data.get("strand", data.get("strand_id", "?"))
                tgt    = data.get("service", data.get("target", "?"))
                self.virus_gen = data.get("generation", self.virus_gen)
                self._feed(ts, "virus_inject",
                    f"[red]Virus[/] gen {self.virus_gen} — strand [bold]{strand}[/] → {tgt}")

            elif event == "mutation":
                self.virus_gen += 1
                self._feed(ts, "mutation",
                    f"[bold red]VIRUS MUTATED → Gen {self.virus_gen}[/] {data.get('reason','')}")

            elif event == "t_cell_hit":
                self.t_cell_hits += 1
                self._feed(ts, "t_cell_hit",
                    f"[bold cyan]T-CELL HIT[/] {service} — instant recovery [dim](<2s)[/]")

            elif event == "connected":
                self._feed(ts, "connected", "[green]Dashboard connected to NATS[/]")

            else:
                self._feed(ts, "default", f"[dim]{event}[/] — {service}")

    def _feed(self, ts: str, event_type: str, message: str):
        icon = EVENT_ICONS.get(event_type, EVENT_ICONS["default"])
        self.battle_feed.append(f"[dim]{ts}[/] {icon}  {message}")

    def _recalc_resilience(self):
        avg_ms = (self.total_recovery_ms / max(self.recovery_count, 1))
        recovery_score = max(0, 400 * (1 - avg_ms / 20000))
        discovery_score = 200 * (1 - len(self.discovered_strands) / max(len(self.discovered_strands)+1, 1))
        self.resilience_score = min(1000, int(recovery_score + discovery_score + self.t_cell_hits * 30))

    def _refresh_timeline(self):
        """Rebuild generations list from accumulated data."""
        gens = []
        for gen, ms_list in sorted(self._gen_ms_acc.items()):
            gens.append({
                "gen": gen,
                "avg_ms": sum(ms_list) / len(ms_list),
                "unknown_rate": 0.0,
            })
        if gens:
            self.generations = gens

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "service_state":      dict(self.service_state),
                "anomaly_scores":     dict(self.anomaly_scores),
                "rf_labels":          dict(self.rf_labels),
                "battle_feed":        list(self.battle_feed),
                "generations":        list(self.generations),
                "resilience_score":   self.resilience_score,
                "virus_gen":          self.virus_gen,
                "antibody_gen":       self.antibody_gen,
                "t_cell_hits":        self.t_cell_hits,
                "recovery_count":     self.recovery_count,
                "lstm_prediction":    self.lstm_prediction,
                "discovered_strands": list(self.discovered_strands),
            }


STATE = DarwinState()

# ── Rich Terminal Renderer ─────────────────────────────────────────────────────

console = Console()


def _make_status_table(snap: dict) -> Table:
    t = Table(
        title="⚙️  Service Status",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=True,
    )
    t.add_column("Service",      style="bold white", no_wrap=True)
    t.add_column("State",        justify="center")
    t.add_column("Anomaly",      justify="right")
    t.add_column("RF Label",     justify="center")

    STATE_STYLE = {
        "healthy":    "[bold green]● HEALTHY[/]",
        "attacked":   "[bold red]⚠ ATTACKED[/]",
        "healing":    "[bold yellow]⟳ HEALING[/]",
        "preemptive": "[bold orange1]⚡ PREDICTED[/]",
        "discovered": "[bold magenta]🍯 HONEYPOT[/]",
        "unknown":    "[dim]? UNKNOWN[/]",
    }
    for svc in SERVICES:
        state  = snap["service_state"].get(svc, "healthy")
        score  = snap["anomaly_scores"].get(svc, 0.0)
        label  = snap["rf_labels"].get(svc, "—")
        bar    = "█" * int(score * 10) + "░" * (10 - int(score * 10))
        score_color = "red" if score > 0.65 else "yellow" if score > 0.3 else "green"
        t.add_row(
            svc,
            STATE_STYLE.get(state, state),
            f"[{score_color}]{bar}[/] {score:.2f}",
            f"[yellow]{label}[/]" if label != "—" else "[dim]—[/]",
        )
    return t


def _make_battle_feed(snap: dict) -> Panel:
    lines = list(snap["battle_feed"])[-15:]   # last 15 events
    if not lines:
        lines = ["[dim]Waiting for events from NATS...[/]"]
    content = "\n".join(lines)
    return Panel(
        content,
        title="📡  Live Battle Feed",
        border_style="cyan",
        expand=True,
    )


def _make_score_panel(snap: dict) -> Panel:
    score = snap["resilience_score"]
    vgen  = snap["virus_gen"]
    agen  = snap["antibody_gen"]
    hits  = snap["t_cell_hits"]
    rec   = snap["recovery_count"]
    lstm  = snap["lstm_prediction"]

    bar_width = 40
    filled = int((score / 1000) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    color = "green" if score > 700 else "yellow" if score > 400 else "red"

    lstm_line = ""
    if lstm:
        lstm_line = (
            f"\n🔮 LSTM → [bold magenta]{lstm['family']}[/] "
            f"[dim]({lstm['confidence']:.0%} confidence)[/]"
        )

    content = (
        f"[bold {color}]{score:>6}/1000[/]  [{color}]{bar}[/]\n"
        f"\n"
        f"  Virus Gen:     [red]{vgen}[/]      Antibody Gen: [cyan]{agen}[/]\n"
        f"  T-Cell Hits:   [cyan]{hits}[/]      Recoveries:   [green]{rec}[/]\n"
        f"  🚫 Human Interventions: [bold green]0[/]"
        f"{lstm_line}"
    )
    return Panel(content, title="🏆  Resilience Score", border_style="green")


def render_rich_once(snap: dict):
    """Called from main thread each refresh cycle."""
    layout = Layout()
    layout.split_column(
        Layout(name="top",    ratio=2),
        Layout(name="middle", ratio=3),
        Layout(name="bottom", ratio=2),
    )
    layout["top"].update(_make_score_panel(snap))
    layout["middle"].split_row(
        Layout(_make_status_table(snap), ratio=3),
        Layout(_make_battle_feed(snap), ratio=4),
    )
    # Generation summary
    gens = snap["generations"]
    gen_rows = "  ".join(
        f"Gen{g['gen']}: [cyan]{g['avg_ms']/1000:.1f}s[/]" for g in gens
    )
    layout["bottom"].update(
        Panel(gen_rows or "[dim]No generation data yet[/]",
              title="🧬  Evolutionary Timeline",
              border_style="magenta")
    )
    return layout


# ── Matplotlib Brain Map + Charts ─────────────────────────────────────────────

# Build fixed graph layout once
_G = nx.DiGraph()
_G.add_nodes_from(SERVICES)
_G.add_edges_from(SERVICE_EDGES)
_POS = nx.spring_layout(_G, seed=42, k=2.0)

_fig = None
_axes = {}


def _init_matplotlib():
    global _fig, _axes
    plt.style.use("dark_background")
    _fig = plt.figure(
        figsize=(14, 8),
        facecolor="#0f172a",
        num="DARWIN Live Monitor"
    )
    _fig.suptitle(
        "DARWIN  ·  Autonomous Chaos Engineering & Self-Healing Platform",
        color="#e2e8f0", fontsize=13, fontweight="bold", y=0.98
    )

    _axes["brain"]    = _fig.add_subplot(221)
    _axes["scores"]   = _fig.add_subplot(222)
    _axes["timeline"] = _fig.add_subplot(223)
    _axes["gauge"]    = _fig.add_subplot(224)

    for ax in _axes.values():
        ax.set_facecolor("#1e293b")
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.ion()
    plt.show(block=False)


def _draw_brain_map(ax, snap: dict):
    ax.clear()
    ax.set_facecolor("#1e293b")
    ax.set_title("🧠 Service Brain Map", color="#94a3b8", pad=6, fontsize=10)
    ax.axis("off")

    node_colors = [
        NODE_COLORS.get(snap["service_state"].get(n, "healthy"), "#64748b")
        for n in _G.nodes
    ]
    node_sizes = [
        2000 if snap["service_state"].get(n) in ("attacked", "healing") else 1400
        for n in _G.nodes
    ]

    nx.draw_networkx_edges(
        _G, _POS, ax=ax,
        edge_color="#475569", arrows=True,
        arrowsize=15, width=1.5,
        connectionstyle="arc3,rad=0.1",
    )
    nx.draw_networkx_nodes(
        _G, _POS, ax=ax,
        node_color=node_colors, node_size=node_sizes,
        alpha=0.92,
    )
    labels = {n: n.replace("-service", "\nsvc") for n in _G.nodes}
    nx.draw_networkx_labels(
        _G, _POS, labels, ax=ax,
        font_size=6.5, font_color="white", font_weight="bold",
    )

    # Legend
    legend = [
        mpatches.Patch(color=NODE_COLORS["healthy"],    label="Healthy"),
        mpatches.Patch(color=NODE_COLORS["attacked"],   label="Attacked"),
        mpatches.Patch(color=NODE_COLORS["healing"],    label="Healing"),
        mpatches.Patch(color=NODE_COLORS["preemptive"], label="Predicted"),
        mpatches.Patch(color=NODE_COLORS["discovered"], label="Honeypot"),
    ]
    ax.legend(handles=legend, loc="lower left", fontsize=6.5,
              facecolor="#0f172a", labelcolor="white", framealpha=0.8)


def _draw_anomaly_scores(ax, snap: dict):
    ax.clear()
    ax.set_facecolor("#1e293b")
    ax.set_title("📊 Anomaly Scores (IF)", color="#94a3b8", pad=6, fontsize=10)

    svcs   = SERVICES
    scores = [snap["anomaly_scores"].get(s, 0.0) for s in svcs]
    colors = [
        "#ef4444" if s > 0.65 else "#f59e0b" if s > 0.3 else "#22c55e"
        for s in scores
    ]
    short = [s.replace("-service", "") for s in svcs]

    bars = ax.barh(short, scores, color=colors, alpha=0.85, height=0.55)
    ax.set_xlim(0, 1.05)
    ax.axvline(0.65, color="#ef4444", linestyle="--", alpha=0.5, linewidth=1)
    ax.text(0.66, -0.5, "threshold", color="#ef4444", fontsize=7, alpha=0.7)

    for bar, score in zip(bars, scores):
        if score > 0.05:
            ax.text(
                score + 0.01, bar.get_y() + bar.get_height() / 2,
                f"{score:.2f}", va="center", fontsize=7.5,
                color="white", alpha=0.9,
            )

    ax.set_xlabel("Anomaly Score", color="#64748b", fontsize=8)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")


def _draw_timeline(ax, snap: dict):
    ax.clear()
    ax.set_facecolor("#1e293b")
    ax.set_title("📈 Evolutionary Timeline", color="#94a3b8", pad=6, fontsize=10)

    gens  = snap["generations"]
    if not gens:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color="#64748b", fontsize=10)
        return

    x     = [g["gen"] for g in gens]
    ms    = [g["avg_ms"] / 1000 for g in gens]   # convert to seconds

    ax.plot(x, ms, "o-", color="#3b82f6", linewidth=2, markersize=7,
            markerfacecolor="#60a5fa", label="Avg Recovery (s)")
    ax.fill_between(x, ms, alpha=0.15, color="#3b82f6")

    for xi, yi in zip(x, ms):
        ax.annotate(f"{yi:.1f}s", (xi, yi),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", color="#93c5fd", fontsize=8)

    ax.set_xlabel("Generation",       color="#64748b", fontsize=8)
    ax.set_ylabel("Recovery (s)",     color="#64748b", fontsize=8)
    ax.tick_params(colors="#94a3b8",  labelsize=8)
    ax.set_xticks(x)
    ax.legend(fontsize=7.5, facecolor="#0f172a", labelcolor="white", framealpha=0.8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")


def _draw_gauge(ax, snap: dict):
    ax.clear()
    ax.set_facecolor("#1e293b")
    ax.set_title("🏆 Resilience Score", color="#94a3b8", pad=6, fontsize=10)
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-0.3, 1.2)
    ax.axis("off")

    score = snap["resilience_score"]
    frac  = score / 1000.0
    color = "#22c55e" if frac > 0.7 else "#f59e0b" if frac > 0.4 else "#ef4444"

    # Background arc
    theta_bg = np.linspace(math.pi, 0, 100)
    ax.plot(np.cos(theta_bg), np.sin(theta_bg), color="#334155", linewidth=18, solid_capstyle="round")

    # Score arc
    theta_sc = np.linspace(math.pi, math.pi - frac * math.pi, 100)
    ax.plot(np.cos(theta_sc), np.sin(theta_sc), color=color, linewidth=18, solid_capstyle="round")

    # Score text
    ax.text(0, 0.25, f"{score}", ha="center", va="center",
            fontsize=34, fontweight="bold", color=color)
    ax.text(0, 0.05, "/ 1000", ha="center", va="center",
            fontsize=11, color="#64748b")
    ax.text(0, -0.15, "🚫 0 Human Interventions",
            ha="center", va="center", fontsize=9, color="#22c55e")

    vgen = snap["virus_gen"]
    ax.text(-1.1, -0.2, f"Virus\nGen {vgen}", ha="center",
            fontsize=8, color="#ef4444")
    ax.text(1.1, -0.2, f"Antibody\nGen {snap['antibody_gen']}", ha="center",
            fontsize=8, color="#22c55e")


def update_matplotlib(snap: dict):
    """Update all 4 subplots. Called from main thread."""
    try:
        _draw_brain_map(_axes["brain"],      snap)
        _draw_anomaly_scores(_axes["scores"], snap)
        _draw_timeline(_axes["timeline"],     snap)
        _draw_gauge(_axes["gauge"],           snap)
        _fig.canvas.draw_idle()
        _fig.canvas.flush_events()
    except Exception as e:
        pass  # Don't crash dashboard on render errors


# ── NATS async consumer (runs in a background thread with its own event loop) ──

def _nats_thread_main():
    async def _run():
        try:
            nc = await nats.connect(NATS_URL)
            print(f"\n✅ [DARWIN] Connected to NATS: {NATS_URL}")

            async def handler(msg):
                try:
                    data = json.loads(msg.data.decode())
                    STATE.on_event(msg.subject, data)
                except Exception:
                    pass

            subjects = [
                "brain.update", "brain.rf_classified",
                "lstm.prediction", "virus.inject",
                "services.health", "antibody.recovery_complete",
            ]
            for subj in subjects:
                await nc.subscribe(subj, cb=handler)

            print(f"📡 [DARWIN] Subscribed to {len(subjects)} NATS subjects")
            # Run forever
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"\n⚠️  [DARWIN] NATS unavailable: {e}")
            print("    Dashboard will show static/demo data.")
            # Inject demo data for offline testing
            await _inject_demo_data()

    asyncio.run(_run())


async def _inject_demo_data():
    """Simulated event stream when NATS is offline — for demo rehearsal."""
    scenarios = [
        ("brain.update",   {"event": "attack_detected",   "service": "payment-service",  "rf_label": "pod_crash", "rf_confidence": 0.94, "anomaly_score": 0.87, "attack_state": "KNOWN"}),
        ("brain.update",   {"event": "recovery_started",  "service": "payment-service"}),
        ("brain.update",   {"event": "recovery_complete", "service": "payment-service",  "recovery_time_ms": 18200, "virus_gen": 1}),
        ("brain.update",   {"event": "t_cell_hit",        "service": "payment-service"}),
        ("brain.update",   {"event": "attack_detected",   "service": "order-service",    "rf_label": "network",   "rf_confidence": 0.73, "anomaly_score": 0.71, "attack_state": "PROBABLE"}),
        ("brain.update",   {"event": "recovery_started",  "service": "order-service"}),
        ("brain.update",   {"event": "recovery_complete", "service": "order-service",    "recovery_time_ms": 8100, "virus_gen": 2}),
        ("lstm.prediction",{"event": "lstm_prediction",   "service": "auth-service",     "predicted_family": "timing", "lstm_confidence": 0.78}),
        ("brain.update",   {"event": "preemptive_action", "service": "payment-service",  "predicted_family": "timing", "lstm_confidence": 0.78, "services": ["payment-service"]}),
        ("brain.update",   {"event": "new_strand_discovered", "service": "auth-service", "strand_id": f"unknown_{int(time.time())}", "family": "resource", "confidence": 0.71}),
        ("brain.update",   {"event": "recovery_complete", "service": "auth-service",     "recovery_time_ms": 1800, "virus_gen": 3}),
    ]
    for subj, data in scenarios:
        STATE.on_event(subj, data)
        await asyncio.sleep(3)
    # Loop forever with small idle events
    while True:
        await asyncio.sleep(10)


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  DARWIN  —  Autonomous Chaos Engineering Platform")
    print("  Live Dashboard (Terminal + Matplotlib)")
    print("=" * 60)
    print(f"  NATS:      {NATS_URL}")
    print(f"  Refresh:   {REFRESH_HZ}s")
    print("=" * 60 + "\n")

    # Initialize matplotlib
    _init_matplotlib()

    # Start NATS consumer in background thread
    nats_thread = threading.Thread(target=_nats_thread_main, daemon=True, name="nats-consumer")
    nats_thread.start()

    # Rich live terminal loop
    try:
        with Live(console=console, refresh_per_second=int(1 / REFRESH_HZ), screen=False) as live:
            while True:
                snap = STATE.snapshot()

                # Update rich terminal
                live.update(render_rich_once(snap))

                # Update matplotlib (must be on main thread)
                update_matplotlib(snap)

                time.sleep(REFRESH_HZ)

    except KeyboardInterrupt:
        print("\n\n👋 DARWIN Dashboard stopped.")
    finally:
        plt.close("all")


if __name__ == "__main__":
    main()
