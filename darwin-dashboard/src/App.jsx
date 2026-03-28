import { useState, useEffect, useRef, useCallback } from 'react'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell
} from 'recharts'
import {
  Activity, AlertTriangle, CheckCircle, Shield, Zap,
  Server, Database, Cpu, HardDrive, Network, Play,
  Square, RefreshCw, Terminal, Brain, Dna, Eye
} from 'lucide-react'
import Header from './components/Header.jsx'
import ServiceGrid from './components/ServiceGrid.jsx'
import AttackFeed from './components/AttackFeed.jsx'
import MetricsChart from './components/MetricsChart.jsx'
import AnomalyRadar from './components/AnomalyRadar.jsx'
import LocustControl from './components/LocustControl.jsx'
import ImmunityPanel from './components/ImmunityPanel.jsx'
import RecoveryTimeline from './components/RecoveryTimeline.jsx'
import FaultInjector from './components/FaultInjector.jsx'
import { useDarwinAPI } from './hooks/useDarwinAPI.js'
import { useMetricsPoller } from './hooks/useMetricsPoller.js'

export default function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const { health, pods, anomalies, recoveries, immunity, faults, injectFault, triggerRecover } = useDarwinAPI()
  const { metrics, history } = useMetricsPoller()

  const tabs = [
    { id: 'overview',   label: 'Overview',       icon: Activity },
    { id: 'chaos',      label: 'Chaos Control',  icon: Zap },
    { id: 'metrics',    label: 'Patient Metrics', icon: Cpu },
    { id: 'immunity',   label: 'Immunity',        icon: Shield },
    { id: 'timeline',   label: 'Timeline',        icon: Brain },
  ]

  return (
    <div className="app-shell">
      <Header health={health} />

      {/* Tab Nav */}
      <nav className="tab-nav">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`tab-btn ${activeTab === id ? 'active' : ''}`}
            onClick={() => setActiveTab(id)}
          >
            <Icon size={14} />
            <span>{label}</span>
            {id === 'chaos' && faults?.length > 0 && (
              <span className="badge badge-red">{faults.length}</span>
            )}
            {id === 'immunity' && immunity?.t_cell_count > 0 && (
              <span className="badge badge-green">{immunity.t_cell_count}</span>
            )}
          </button>
        ))}
      </nav>

      {/* Main Content */}
      <main className="main-content">
        {activeTab === 'overview' && (
          <OverviewTab
            health={health} pods={pods} anomalies={anomalies}
            metrics={metrics} history={history} recoveries={recoveries}
          />
        )}
        {activeTab === 'chaos' && (
          <ChaosTab
            faults={faults} anomalies={anomalies}
            injectFault={injectFault} triggerRecover={triggerRecover}
          />
        )}
        {activeTab === 'metrics' && (
          <MetricsTab metrics={metrics} history={history} pods={pods} />
        )}
        {activeTab === 'immunity' && (
          <ImmunityTab immunity={immunity} recoveries={recoveries} />
        )}
        {activeTab === 'timeline' && (
          <TimelineTab recoveries={recoveries} anomalies={anomalies} />
        )}
      </main>

      <style>{appStyles}</style>
    </div>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
function OverviewTab({ health, pods, anomalies, metrics, history, recoveries }) {
  const components = health?.components || {}
  const healthyPods = pods?.pods?.filter(p => p.ready)?.length ?? 0
  const totalPods   = pods?.count ?? 0
  const avgRecovery = recoveries?.recoveries?.length
    ? Math.round(recoveries.recoveries.reduce((a, r) => a + (r.recovery_time_ms || 0), 0) / recoveries.recoveries.length)
    : 0

  const statCards = [
    {
      label: 'System Status',
      value: health?.status ?? 'loading...',
      icon: Activity,
      color: health?.status === 'healthy' ? 'green' : 'red',
      subtitle: `${Object.values(components).filter(c => c.ok).length}/${Object.keys(components).length} components up`,
    },
    {
      label: 'Pods Ready',
      value: `${healthyPods}/${totalPods}`,
      icon: Server,
      color: healthyPods === totalPods && totalPods > 0 ? 'green' : 'amber',
      subtitle: 'patient namespace',
    },
    {
      label: 'Anomalies Detected',
      value: anomalies?.count ?? 0,
      icon: AlertTriangle,
      color: (anomalies?.count ?? 0) > 0 ? 'amber' : 'green',
      subtitle: 'last 1 hour',
    },
    {
      label: 'Avg Recovery',
      value: avgRecovery > 0 ? `${(avgRecovery / 1000).toFixed(1)}s` : '—',
      icon: Zap,
      color: 'cyan',
      subtitle: `${recoveries?.count ?? 0} recoveries total`,
    },
  ]

  return (
    <div className="grid-layout">
      {/* Stat Cards */}
      <div className="stats-row">
        {statCards.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      {/* Middle row */}
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Activity size={14}/> Live Anomaly Score</span>
            <span className="pill cyan">ML Pipeline</span>
          </div>
          <MetricsChart history={history} />
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Eye size={14}/> Service Health Radar</span>
            <span className="pill purple">All Services</span>
          </div>
          <AnomalyRadar metrics={metrics} />
        </div>
      </div>

      {/* Bottom row */}
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Zap size={14}/> Infrastructure</span>
          </div>
          <InfraStatus components={components} />
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Shield size={14}/> Battle Feed</span>
            <span className="pill red animate-pulse-glow">LIVE</span>
          </div>
          <AttackFeed anomalies={anomalies?.anomalies ?? []} />
        </div>
      </div>
    </div>
  )
}

// ── Chaos Tab ─────────────────────────────────────────────────────────────────
function ChaosTab({ faults, anomalies, injectFault, triggerRecover }) {
  return (
    <div className="grid-layout">
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Zap size={14}/> Inject Fault</span>
            <span className="pill red">DARWIN Virus Agent</span>
          </div>
          <FaultInjector onInject={injectFault} onRecover={triggerRecover} />
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Terminal size={14}/> Active Faults</span>
            {faults?.length > 0 && <span className="badge badge-red">{faults.length}</span>}
          </div>
          <ActiveFaultsList faults={faults ?? []} onRecover={triggerRecover} />
        </div>
      </div>
      <div className="card full-width">
        <div className="card-header">
          <span className="card-title"><Activity size={14}/> Locust Load Generator</span>
          <span className="pill cyan">Patient Traffic</span>
        </div>
        <LocustControl />
      </div>
    </div>
  )
}

// ── Metrics Tab ───────────────────────────────────────────────────────────────
function MetricsTab({ metrics, history, pods }) {
  const services = Object.keys(metrics || {})

  return (
    <div className="grid-layout">
      <ServiceGrid pods={pods?.pods ?? []} metrics={metrics} />
      <div className="metrics-grid">
        {services.map(svc => (
          <ServiceMetricCard key={svc} service={svc} data={metrics[svc]} history={history} />
        ))}
      </div>
    </div>
  )
}

// ── Immunity Tab ──────────────────────────────────────────────────────────────
function ImmunityTab({ immunity, recoveries }) {
  return (
    <div className="grid-layout">
      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Dna size={14}/> T-Cell Memory Cache</span>
            <span className="pill green">{immunity?.t_cell_count ?? 0} entries</span>
          </div>
          <ImmunityPanel immunity={immunity} />
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title"><Shield size={14}/> Recovery Outcomes</span>
          </div>
          <RecoveryStats recoveries={recoveries?.recoveries ?? []} />
        </div>
      </div>
    </div>
  )
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────
function TimelineTab({ recoveries, anomalies }) {
  return (
    <div className="grid-layout">
      <div className="card full-width">
        <div className="card-header">
          <span className="card-title"><Brain size={14}/> Evolutionary Timeline</span>
          <span className="pill purple">inject → detect → recover → learn</span>
        </div>
        <RecoveryTimeline recoveries={recoveries?.recoveries ?? []} anomalies={anomalies?.anomalies ?? []} />
      </div>
    </div>
  )
}

// ── Shared UI Components ──────────────────────────────────────────────────────

function StatCard({ label, value, icon: Icon, color, subtitle }) {
  return (
    <div className={`stat-card stat-card--${color}`}>
      <div className="stat-icon-wrap">
        <Icon size={18} className={`icon-${color}`} />
      </div>
      <div className="stat-body">
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
        {subtitle && <div className="stat-sub">{subtitle}</div>}
      </div>
      <div className={`stat-glow stat-glow--${color}`} />
    </div>
  )
}

function InfraStatus({ components }) {
  const icons = { kubernetes: Server, redis: Database, prometheus: Activity, neo4j: Brain }
  return (
    <div className="infra-list">
      {Object.entries(components).map(([name, info]) => {
        const Icon = icons[name] || Server
        return (
          <div key={name} className="infra-row">
            <div className="infra-left">
              <Icon size={14} className={info.ok ? 'icon-green' : 'icon-red'} />
              <span className="infra-name">{name}</span>
            </div>
            <div className="infra-right">
              <span className="infra-endpoint">{info.endpoint}</span>
              <span className={`pill-sm ${info.ok ? 'green' : 'red'}`}>
                {info.ok ? 'UP' : 'DOWN'}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ActiveFaultsList({ faults, onRecover }) {
  if (!faults.length) {
    return (
      <div className="empty-state">
        <CheckCircle size={32} className="icon-green" />
        <p>No active faults</p>
        <span>System is healthy</span>
      </div>
    )
  }
  return (
    <div className="fault-list">
      {faults.map((f) => (
        <div key={f.fault_id} className="fault-row animate-fade-in">
          <div className="fault-left">
            <AlertTriangle size={14} className="icon-red animate-pulse-glow" />
            <div>
              <div className="fault-name">{f.fault_type}</div>
              <div className="fault-service">{f.service}</div>
            </div>
          </div>
          <button
            className="btn btn-sm btn-green"
            onClick={() => onRecover({ service: f.service, strand_id: f.fault_id, attack_family: f.fault_type, rf_confidence: 0.9, anomaly_score: 0.9 })}
          >
            Recover
          </button>
        </div>
      ))}
    </div>
  )
}

function ServiceMetricCard({ service, data, history }) {
  if (!data) return null
  const svcHistory = (history || []).map(h => ({
    t: h.t,
    cpu: h.services?.[service]?.cpu_usage_pct ?? 0,
    err: h.services?.[service]?.http_error_rate_5xx ?? 0,
  }))

  return (
    <div className="metric-card">
      <div className="metric-header">
        <span className="metric-svc">{service}</span>
        <div className="metric-pills">
          <span className="pill-sm cyan">CPU {(data.cpu_usage_pct ?? 0).toFixed(1)}%</span>
          <span className="pill-sm purple">Mem {(data.memory_usage_pct ?? 0).toFixed(0)}MB</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <AreaChart data={svcHistory.slice(-20)}>
          <defs>
            <linearGradient id={`g-${service}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#00e5ff" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#00e5ff" stopOpacity={0}   />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="cpu" stroke="#00e5ff" strokeWidth={1.5}
                fill={`url(#g-${service})`} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
      <div className="metric-row">
        <span className="metric-key">Error rate</span>
        <span className={`metric-val ${data.http_error_rate_5xx > 0.1 ? 'text-red' : 'text-green'}`}>
          {((data.http_error_rate_5xx ?? 0) * 100).toFixed(2)}%
        </span>
      </div>
      <div className="metric-row">
        <span className="metric-key">Latency P99</span>
        <span className="metric-val">{((data.request_latency_p99 ?? 0) * 1000).toFixed(0)}ms</span>
      </div>
    </div>
  )
}

function RecoveryStats({ recoveries }) {
  const byTier = { 1: 0, 2: 0, 3: 0 }
  recoveries.forEach(r => { byTier[r.tier ?? 3]++ })
  const success = recoveries.filter(r => r.success).length
  const total   = recoveries.length

  const tierData = [
    { name: 'T-Cell (Tier 1)', value: byTier[1], color: '#22c55e' },
    { name: 'Neo4j  (Tier 2)', value: byTier[2], color: '#3b82f6' },
    { name: 'LLM    (Tier 3)', value: byTier[3], color: '#a855f7' },
  ]

  return (
    <div className="recovery-stats">
      <div className="recovery-summary">
        <div className="rs-big">{total > 0 ? Math.round((success / total) * 100) : 0}%</div>
        <div className="rs-label">Success Rate</div>
        <div className="rs-sub">{success}/{total} recoveries</div>
      </div>
      <div className="tier-bars">
        {tierData.map(t => (
          <div key={t.name} className="tier-bar-row">
            <span className="tier-name">{t.name}</span>
            <div className="tier-bar-bg">
              <div className="tier-bar-fill"
                style={{ width: `${total ? (t.value / total) * 100 : 0}%`, background: t.color }} />
            </div>
            <span className="tier-count">{t.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const appStyles = `
/* Shell */
.app-shell { display: flex; flex-direction: column; height: 100vh; background: var(--bg-deep); overflow: hidden; }

/* Tab nav */
.tab-nav { display: flex; align-items: center; gap: 4px; padding: 0 20px; background: var(--bg-base); border-bottom: 1px solid var(--border); flex-shrink: 0; }
.tab-btn  { display: flex; align-items: center; gap: 6px; padding: 10px 14px; font-size: 12px; font-weight: 500; color: var(--text-secondary); background: none; border: none; border-bottom: 2px solid transparent; cursor: pointer; transition: all .2s; white-space: nowrap; }
.tab-btn:hover  { color: var(--text-primary); background: var(--bg-hover); border-radius: 6px 6px 0 0; }
.tab-btn.active { color: var(--cyan); border-bottom-color: var(--cyan); }

/* Main content */
.main-content { flex: 1; overflow-y: auto; padding: 16px 20px; }

/* Grid layouts */
.grid-layout  { display: flex; flex-direction: column; gap: 14px; }
.two-col      { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.stats-row    { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.full-width   { width: 100%; }

/* Card */
.card        { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; position: relative; overflow: hidden; }
.card::before { content: ''; position: absolute; top:0; left:0; right:0; height:1px; background: linear-gradient(90deg, transparent, var(--cyan-dim), transparent); }
.card-header  { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.card-title   { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }

/* Pills */
.pill      { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 99px; }
.pill.cyan   { background: var(--cyan-dim);   color: var(--cyan);   border: 1px solid rgba(0,229,255,.3); }
.pill.purple { background: var(--purple-dim); color: var(--purple); border: 1px solid rgba(168,85,247,.3); }
.pill.green  { background: var(--green-dim);  color: var(--green);  border: 1px solid rgba(34,197,94,.3); }
.pill.red    { background: var(--red-dim);    color: var(--red);    border: 1px solid rgba(239,68,68,.3); }
.pill-sm     { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 99px; }
.pill-sm.cyan   { background: var(--cyan-dim);   color: var(--cyan); }
.pill-sm.purple { background: var(--purple-dim); color: var(--purple); }
.pill-sm.green  { background: var(--green-dim);  color: var(--green); }
.pill-sm.red    { background: var(--red-dim);    color: var(--red); }

/* Badges */
.badge       { font-size: 10px; font-weight: 700; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 99px; display: inline-flex; align-items: center; justify-content: center; }
.badge-red   { background: var(--red);   color: #fff; }
.badge-green { background: var(--green); color: #fff; }

/* Stat cards */
.stat-card         { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; display: flex; align-items: center; gap: 12px; position: relative; overflow: hidden; transition: transform .2s, border-color .2s; }
.stat-card:hover   { transform: translateY(-2px); border-color: var(--border-bright); }
.stat-card--green  { border-left: 3px solid var(--green); }
.stat-card--amber  { border-left: 3px solid var(--amber); }
.stat-card--cyan   { border-left: 3px solid var(--cyan);  }
.stat-card--red    { border-left: 3px solid var(--red);   }
.stat-icon-wrap    { width: 36px; height: 36px; border-radius: 8px; background: var(--bg-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-value        { font-size: 22px; font-weight: 800; line-height: 1; }
.stat-label        { font-size: 11px; color: var(--text-secondary); font-weight: 500; margin-top: 3px; }
.stat-sub          { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
.stat-glow         { position: absolute; top: -20px; right: -20px; width: 80px; height: 80px; border-radius: 50%; opacity: 0.06; }
.stat-glow--green  { background: var(--green); }
.stat-glow--cyan   { background: var(--cyan);  }
.stat-glow--amber  { background: var(--amber); }
.stat-glow--red    { background: var(--red);   }

/* Icon colors */
.icon-green { color: var(--green); }
.icon-cyan  { color: var(--cyan);  }
.icon-red   { color: var(--red);   }
.icon-amber { color: var(--amber); }
.icon-purple{ color: var(--purple);}
.text-green { color: var(--green); }
.text-red   { color: var(--red);   }

/* Infra list */
.infra-list { display: flex; flex-direction: column; gap: 10px; }
.infra-row  { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 8px; background: var(--bg-card2); border: 1px solid var(--border); }
.infra-left { display: flex; align-items: center; gap: 8px; }
.infra-name { font-size: 13px; font-weight: 500; text-transform: capitalize; }
.infra-right { display: flex; align-items: center; gap: 8px; }
.infra-endpoint { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }

/* Fault list */
.fault-list { display: flex; flex-direction: column; gap: 8px; }
.fault-row  { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 8px; background: rgba(239,68,68,.05); border: 1px solid rgba(239,68,68,.2); }
.fault-left { display: flex; align-items: center; gap: 10px; }
.fault-name { font-size: 12px; font-weight: 600; color: var(--red); }
.fault-service { font-size: 11px; color: var(--text-muted); }

/* Buttons */
.btn     { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; border: none; border-radius: 6px; cursor: pointer; transition: all .15s; }
.btn-sm  { padding: 5px 10px; font-size: 11px; }
.btn-green { background: var(--green-dim); color: var(--green); border: 1px solid rgba(34,197,94,.3); }
.btn-green:hover { background: var(--green); color: #fff; }
.btn-red   { background: var(--red-dim); color: var(--red); border: 1px solid rgba(239,68,68,.3); }
.btn-red:hover { background: var(--red); color: #fff; }
.btn-cyan  { background: var(--cyan-dim); color: var(--cyan); border: 1px solid rgba(0,229,255,.3); }
.btn-cyan:hover { background: var(--cyan); color: var(--bg-deep); }

/* Empty state */
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px 0; color: var(--text-muted); }
.empty-state p { font-size: 14px; font-weight: 500; color: var(--text-secondary); }
.empty-state span { font-size: 12px; }

/* Metric cards */
.metric-card   { background: var(--bg-card2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; }
.metric-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.metric-svc    { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.metric-pills  { display: flex; gap: 4px; }
.metric-row    { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 11px; }
.metric-key    { color: var(--text-muted); }
.metric-val    { font-family: var(--font-mono); font-size: 11px; font-weight: 500; }

/* Recovery stats */
.recovery-stats   { display: flex; gap: 20px; }
.recovery-summary { display: flex; flex-direction: column; align-items: center; padding: 16px; background: var(--bg-card2); border-radius: var(--radius-sm); min-width: 100px; }
.rs-big    { font-size: 36px; font-weight: 900; background: linear-gradient(135deg, var(--cyan), var(--purple)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.rs-label  { font-size: 11px; color: var(--text-secondary); font-weight: 600; margin-top: 4px; }
.rs-sub    { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
.tier-bars { flex: 1; display: flex; flex-direction: column; gap: 12px; justify-content: center; }
.tier-bar-row  { display: flex; align-items: center; gap: 10px; }
.tier-name     { font-size: 11px; color: var(--text-muted); width: 100px; font-family: var(--font-mono); }
.tier-bar-bg   { flex: 1; height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.tier-bar-fill { height: 100%; border-radius: 3px; transition: width .5s ease; }
.tier-count    { font-size: 11px; font-weight: 600; width: 24px; text-align: right; color: var(--text-secondary); }

@media (max-width: 1200px) {
  .stats-row    { grid-template-columns: repeat(2, 1fr); }
  .metrics-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 900px) {
  .two-col { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: 1fr 1fr; }
}
`
