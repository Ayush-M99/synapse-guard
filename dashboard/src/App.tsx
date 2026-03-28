import { useState, useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { motion, AnimatePresence } from 'framer-motion';

/* ═══════════════════════════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════════════════════════ */

interface ServiceNode {
  id: string;
  name: string;
  status: 'healthy' | 'attacked' | 'healing' | 'preemptive' | 'discovered';
  x?: number;
  y?: number;
}

interface BattleEvent {
  icon: string;
  message: string;
  event: string;
  service?: string;
  timestamp: string;
  data?: any;
}

interface GenerationData {
  gen: number;
  recovery_ms: number;
  unknown_rate: number;
  resilience_score: number;
}

interface DnaEntry {
  id: number;
  strand: string;
  family: string;
  service: string;
  recovery_ms: number;
  success: boolean;
  gen: number;
  timestamp: string;
}

/* ═══════════════════════════════════════════════════════════════
   CONSTANTS
   ═══════════════════════════════════════════════════════════════ */

const NODE_COLORS: Record<string, string> = {
  healthy: '#22c55e',
  attacked: '#ef4444',
  healing: '#f59e0b',
  preemptive: '#f97316',
  discovered: '#a855f7',
};

const WS_URL = 'ws://localhost:8010/ws';
const API_URL = 'http://localhost:8010';

const SERVICE_NAMES = [
  'payment-service', 'auth-service', 'api-gateway',
  'order-service', 'inventory-service', 'notification-service',
];

const SERVICE_DEPS = [
  ['api-gateway', 'auth-service'],
  ['api-gateway', 'payment-service'],
  ['api-gateway', 'order-service'],
  ['payment-service', 'order-service'],
  ['order-service', 'inventory-service'],
  ['order-service', 'notification-service'],
  ['payment-service', 'notification-service'],
];

/* ═══════════════════════════════════════════════════════════════
   BRAIN MAP COMPONENT (Panel 1 — D3 Force Graph) §12
   ═══════════════════════════════════════════════════════════════ */

function BrainMap({ services }: { services: Record<string, string> }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<any, any> | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    const width = svgRef.current.clientWidth || 500;
    const height = svgRef.current.clientHeight || 400;

    const nodes = SERVICE_NAMES.map((name, i) => ({
      id: name,
      label: name.replace('-service', '').replace('-', ' '),
      status: services[name] || 'healthy',
      x: width / 2 + Math.cos(i * Math.PI * 2 / 6) * 140,
      y: height / 2 + Math.sin(i * Math.PI * 2 / 6) * 140,
    }));

    const links = SERVICE_DEPS.map(([source, target]) => ({ source, target }));

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // Glow filter
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'blur');
    filter.append('feMerge')
      .selectAll('feMergeNode')
      .data(['blur', 'SourceGraphic'])
      .join('feMergeNode')
      .attr('in', d => d);

    // Links
    svg.selectAll('.link')
      .data(links)
      .join('line')
      .attr('class', 'link')
      .attr('x1', d => nodes.find(n => n.id === (typeof d.source === 'string' ? d.source : d.source.id))?.x || 0)
      .attr('y1', d => nodes.find(n => n.id === (typeof d.source === 'string' ? d.source : d.source.id))?.y || 0)
      .attr('x2', d => nodes.find(n => n.id === (typeof d.target === 'string' ? d.target : d.target.id))?.x || 0)
      .attr('y2', d => nodes.find(n => n.id === (typeof d.target === 'string' ? d.target : d.target.id))?.y || 0)
      .attr('stroke', 'rgba(255,255,255,0.15)')
      .attr('stroke-width', 1.5);

    // Nodes
    const nodeGroups = svg.selectAll('.node')
      .data(nodes)
      .join('g')
      .attr('class', 'node')
      .attr('transform', d => `translate(${d.x}, ${d.y})`);

    // Outer glow
    nodeGroups.append('circle')
      .attr('r', 28)
      .attr('fill', d => NODE_COLORS[d.status] || NODE_COLORS.healthy)
      .attr('opacity', 0.2)
      .attr('filter', 'url(#glow)');

    // Inner circle
    nodeGroups.append('circle')
      .attr('r', 18)
      .attr('fill', d => NODE_COLORS[d.status] || NODE_COLORS.healthy)
      .attr('stroke', 'rgba(255,255,255,0.3)')
      .attr('stroke-width', 2);

    // Labels
    nodeGroups.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 35)
      .attr('fill', 'rgba(255,255,255,0.8)')
      .attr('font-size', '10px')
      .attr('font-weight', '600')
      .text(d => d.label.toUpperCase());

    // Add pulsing animation for healing nodes
    nodeGroups.filter(d => d.status === 'healing')
      .selectAll('circle')
      .attr('opacity', null);

  }, [services]);

  return (
    <svg
      ref={svgRef}
      className="w-full h-full"
      style={{ minHeight: '350px' }}
    />
  );
}

/* ═══════════════════════════════════════════════════════════════
   BATTLE FEED COMPONENT (Panel 2) §12
   ═══════════════════════════════════════════════════════════════ */

function BattleFeed({ events, virusGen, antibodyGen }: {
  events: BattleEvent[];
  virusGen: number;
  antibodyGen: number;
}) {
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-sm font-bold text-white/60 tracking-widest uppercase">Live Battle Feed</h3>
        <div className="flex gap-2">
          <span className="px-2 py-0.5 bg-red-500/20 text-red-400 text-xs font-bold rounded">
            Virus: G{virusGen}
          </span>
          <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 text-xs font-bold rounded">
            Antibody: G{antibodyGen}
          </span>
        </div>
      </div>
      <div ref={feedRef} className="flex-1 overflow-y-auto space-y-1 scrollbar-thin">
        <AnimatePresence>
          {events.map((evt, i) => (
            <motion.div
              key={`${evt.timestamp}-${i}`}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-white/5 text-sm"
            >
              <span className="text-lg flex-shrink-0">{evt.icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-white/80 text-xs leading-tight truncate">
                  {evt.message}
                </p>
                <p className="text-white/30 text-[10px]">{evt.timestamp}</p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   EVOLUTIONARY TIMELINE (Panel 3 — Recharts) §12
   ═══════════════════════════════════════════════════════════════ */

function EvolutionaryTimeline({ data }: { data: GenerationData[] }) {
  return (
    <div>
      <h3 className="text-sm font-bold text-white/60 tracking-widest uppercase mb-3">
        Evolutionary Timeline
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
          <XAxis
            dataKey="gen"
            stroke="rgba(255,255,255,0.3)"
            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
            label={{ value: 'Generation', position: 'bottom', fill: 'rgba(255,255,255,0.4)', fontSize: 10 }}
          />
          <YAxis
            yAxisId="left"
            stroke="rgba(255,255,255,0.3)"
            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke="rgba(255,255,255,0.3)"
            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'rgba(15,23,42,0.95)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
              color: '#fff',
            }}
          />
          <Legend wrapperStyle={{ color: 'rgba(255,255,255,0.6)', fontSize: 11 }} />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="recovery_ms"
            name="Recovery Time (ms)"
            stroke="#ef4444"
            strokeWidth={2}
            dot={{ fill: '#ef4444', r: 4 }}
            activeDot={{ r: 6 }}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="unknown_rate"
            name="Unknown Rate"
            stroke="#a855f7"
            strokeWidth={2}
            dot={{ fill: '#a855f7', r: 4 }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   DNA REPLAY (Panel 4) §12
   ═══════════════════════════════════════════════════════════════ */

function DnaReplay({ dnaLog }: { dnaLog: DnaEntry[] }) {
  const [selectedGen, setSelectedGen] = useState(1);
  const gens = [...new Set(dnaLog.map(d => d.gen))].sort();

  const genEvents = dnaLog.filter(d => d.gen === selectedGen);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white/60 tracking-widest uppercase">DNA Replay</h3>
        <select
          value={selectedGen}
          onChange={e => setSelectedGen(Number(e.target.value))}
          className="bg-white/10 text-white text-xs px-2 py-1 rounded border border-white/20"
        >
          {(gens.length > 0 ? gens : [1, 2, 3]).map(g => (
            <option key={g} value={g} className="bg-slate-900">Gen {g}</option>
          ))}
        </select>
      </div>
      <div className="space-y-1 max-h-[150px] overflow-y-auto">
        {genEvents.length === 0 ? (
          <p className="text-white/30 text-xs italic">No events for Gen {selectedGen}</p>
        ) : (
          genEvents.map((entry, i) => (
            <div key={i} className="flex items-center gap-2 py-1 px-2 rounded bg-white/5 text-xs">
              <span className={`w-2 h-2 rounded-full ${entry.success ? 'bg-emerald-500' : 'bg-red-500'}`} />
              <span className="text-white/70 font-mono">{entry.strand}</span>
              <span className="text-white/40">→</span>
              <span className="text-white/60">{entry.service?.replace('-service', '')}</span>
              <span className="ml-auto text-white/40 font-mono">{entry.recovery_ms?.toFixed(0)}ms</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   RESILIENCE SCORE (Panel 5) §12
   ═══════════════════════════════════════════════════════════════ */

function ResilienceScore({ score, totalHealed, humanInterventions }: {
  score: number;
  totalHealed: number;
  humanInterventions: number;
}) {
  const [displayScore, setDisplayScore] = useState(0);

  useEffect(() => {
    const diff = score - displayScore;
    if (Math.abs(diff) < 1) {
      setDisplayScore(score);
      return;
    }
    const timer = setTimeout(() => {
      setDisplayScore(prev => prev + Math.sign(diff) * Math.max(1, Math.abs(diff) * 0.1));
    }, 30);
    return () => clearTimeout(timer);
  }, [score, displayScore]);

  const scoreColor = score > 700 ? '#22c55e' : score > 400 ? '#f59e0b' : '#ef4444';

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs text-white/40 uppercase tracking-widest mb-1">Resilience Score</p>
          <motion.p
            className="text-5xl font-black tabular-nums"
            style={{ color: scoreColor }}
            key={Math.floor(displayScore)}
            initial={{ scale: 1.1 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.15 }}
          >
            {Math.floor(displayScore)}
          </motion.p>
        </div>
        <div className="w-px h-12 bg-white/10" />
        <div>
          <p className="text-xs text-white/40 uppercase tracking-widest">Healed</p>
          <p className="text-2xl font-bold text-emerald-400">{totalHealed}</p>
        </div>
      </div>
      <motion.div
        className="px-4 py-2 rounded-xl border-2 border-emerald-500/30 bg-emerald-500/10"
        animate={{ borderColor: ['rgba(34,197,94,0.3)', 'rgba(34,197,94,0.6)', 'rgba(34,197,94,0.3)'] }}
        transition={{ duration: 2, repeat: Infinity }}
      >
        <p className="text-emerald-400 font-black text-sm tracking-wider">
          {humanInterventions} HUMAN INTERVENTIONS
        </p>
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MAIN DASHBOARD APP
   ═══════════════════════════════════════════════════════════════ */

export default function DarwinDashboard() {
  const [services, setServices] = useState<Record<string, string>>(
    Object.fromEntries(SERVICE_NAMES.map(s => [s, 'healthy']))
  );
  const [battleFeed, setBattleFeed] = useState<BattleEvent[]>([]);
  const [genData, setGenData] = useState<GenerationData[]>([
    { gen: 1, recovery_ms: 18000, unknown_rate: 0.0, resilience_score: 340 },
    { gen: 2, recovery_ms: 8200, unknown_rate: 0.15, resilience_score: 580 },
    { gen: 3, recovery_ms: 1800, unknown_rate: 0.0, resilience_score: 847 },
  ]);
  const [dnaLog, setDnaLog] = useState<DnaEntry[]>([]);
  const [resilienceScore, setResilienceScore] = useState(0);
  const [virusGen, setVirusGen] = useState(1);
  const [antibodyGen, setAntibodyGen] = useState(1);
  const [totalHealed, setTotalHealed] = useState(0);
  const [humanInterventions] = useState(0);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  const connectWebSocket = useCallback(() => {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setConnected(true);
      console.log('[WS] Connected');
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);

        if (data.event === 'initial_state') {
          setServices(data.services || {});
          setBattleFeed(data.battle_feed || []);
          setResilienceScore(data.resilience_score || 0);
          setVirusGen(data.virus_gen || 1);
          setAntibodyGen(data.antibody_gen || 1);
          setTotalHealed(data.total_healed || 0);
          if (data.generation_data?.length > 0) {
            setGenData(data.generation_data);
          } else if (data.generation_data && data.generation_data.length === 0) {
            // Keep default if empty to avoid breaking chart line
          }
          return;
        }

        if (data.event === 'health_update') {
          setServices(data.services);
          return;
        }

        // Update service states based on events
        if (data.service) {
          if (data.virus_gen) {
            setVirusGen(data.virus_gen);
          }

          setServices(prev => {
            const next = { ...prev };
            if (data.event === 'attack_detected') next[data.service] = 'attacked';
            else if (data.event === 'recovery_started') next[data.service] = 'healing';
            else if (data.event === 'recovery_complete') {
              next[data.service] = 'healthy';
              setTotalHealed(p => p + 1);
            }
            else if (data.event === 'preemptive_action') next[data.service] = 'preemptive';
            else if (data.event === 'new_strand_discovered') next[data.service] = 'discovered';
            else if (data.event === 'honeypot_deployed') next[data.service] = 'healing';
            return next;
          });
        }

        // Fix Evolutionary Timeline updates!
        if (data.event === 'recovery_complete') {
          const recTime = data.data?.recovery_time_ms ?? data.recovery_time_ms;
          if (recTime !== undefined) {
            setGenData(prev => {
              const currGen = data.virus_gen || virusGen;
              const newGen = [...prev];
              const idx = newGen.findIndex(d => d.gen === currGen);
              if (idx >= 0) {
                newGen[idx] = { ...newGen[idx], recovery_ms: recTime };
              } else {
                newGen.push({ gen: currGen, recovery_ms: recTime, unknown_rate: 0, resilience_score: resilienceScore });
              }
              return newGen;
            });
          }
        }

        // Update resilience score
        if (data.data?.resilience_score) {
          setResilienceScore(data.data.resilience_score);
        }

        // Add to battle feed
        if (data.icon && data.message) {
          setBattleFeed(prev => [...prev.slice(-49), data]);
        }

        // Add DNA entry
        if (data.event === 'recovery_complete' && data.data) {
          setDnaLog(prev => [...prev.slice(-99), {
            id: prev.length + 1,
            strand: data.data?.strand_id || '?',
            family: data.data?.attack_family || '?',
            service: data.service || '?',
            recovery_ms: data.data?.recovery_time_ms || 0,
            success: data.data?.success ?? true,
            gen: virusGen,
            timestamp: data.timestamp || '',
          }]);
        }
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      console.log('[WS] Disconnected — reconnecting in 3s');
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, [virusGen]);

  useEffect(() => {
    connectWebSocket();
    return () => wsRef.current?.close();
  }, [connectWebSocket]);

  // Periodic state fetch as backup
  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch(`${API_URL}/api/state`);
        const data = await res.json();
        setResilienceScore(data.resilience_score || resilienceScore);
        setTotalHealed(data.total_healed || totalHealed);
        setVirusGen(data.virus_gen || virusGen);
      } catch { /* ignore */ }
    };
    const interval = setInterval(fetchState, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 text-white font-sans">
      {/* Header */}
      <header className="border-b border-white/10 px-6 py-4">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
            <h1 className="text-xl font-black tracking-tight">
              DARWIN <span className="text-indigo-400">AUTONOMOUS</span> DEFENSE
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <span className={`px-3 py-1 rounded-full text-xs font-bold ${connected ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
              }`}>
              {connected ? '● LIVE' : '○ CONNECTING'}
            </span>
            <span className="text-white/30 text-xs font-mono">v4.0.0</span>
          </div>
        </div>
      </header>

      {/* Main Grid — 5 Panels matching §12 layout */}
      <main className="max-w-[1600px] mx-auto p-6 grid grid-cols-3 grid-rows-[1fr_auto_auto] gap-4"
        style={{ minHeight: 'calc(100vh - 73px)' }}>

        {/* Panel 1: Brain Map (large, left) */}
        <div className="col-span-2 row-span-1 bg-white/5 rounded-2xl border border-white/10 p-4 backdrop-blur">
          <h3 className="text-sm font-bold text-white/60 tracking-widest uppercase mb-2">
            🧠 Neural Brain Map
          </h3>
          <BrainMap services={services} />
        </div>

        {/* Panel 2: Live Battle Feed (right) */}
        <div className="row-span-1 bg-white/5 rounded-2xl border border-white/10 p-4 backdrop-blur overflow-hidden"
          style={{ maxHeight: '420px' }}>
          <BattleFeed
            events={battleFeed}
            virusGen={virusGen}
            antibodyGen={antibodyGen}
          />
        </div>

        {/* Panel 3: Evolutionary Timeline (bottom-left) */}
        <div className="col-span-2 bg-white/5 rounded-2xl border border-white/10 p-4 backdrop-blur">
          <EvolutionaryTimeline data={genData} />
        </div>

        {/* Panel 4: DNA Replay (bottom-right) */}
        <div className="bg-white/5 rounded-2xl border border-white/10 p-4 backdrop-blur">
          <DnaReplay dnaLog={dnaLog} />
        </div>

        {/* Panel 5: Resilience Score (full width bottom) */}
        <div className="col-span-3 bg-white/5 rounded-2xl border border-white/10 px-6 py-4 backdrop-blur">
          <ResilienceScore
            score={resilienceScore}
            totalHealed={totalHealed}
            humanInterventions={humanInterventions}
          />
        </div>
      </main>
    </div>
  );
}
