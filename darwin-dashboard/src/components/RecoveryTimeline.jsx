import { CheckCircle, XCircle, Clock } from 'lucide-react'

export default function RecoveryTimeline({ recoveries, anomalies }) {
  // Merge recoveries + anomalies into one timeline
  const events = [
    ...(anomalies || []).map(a => ({
      type: 'anomaly', time: a.timestamp, service: a.service,
      label: `Anomaly: ${a.rf_label}`, color: 'amber', state: a.attack_state,
    })),
    ...(recoveries || []).map(r => ({
      type: 'recovery', time: r.timestamp, service: r.service,
      label: `Recovery: ${r.playbook_id}`, color: r.success ? 'green' : 'red',
      tier: r.tier_label, ms: r.recovery_time_ms,
    })),
  ].sort((a, b) => (b.time ?? 0) - (a.time ?? 0)).slice(0, 20)

  if (!events.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 120, color: 'var(--text-muted)', fontSize: 13 }}>
        No events yet — inject a fault to start the loop!
      </div>
    )
  }

  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div key={i} className="tl-item animate-fade-in">
          {/* Dot + connector */}
          <div className="tl-left">
            <div className={`tl-dot tl-dot-${e.color}`}>
              {e.type === 'recovery'
                ? (e.color === 'green' ? <CheckCircle size={10} /> : <XCircle size={10} />)
                : <Clock size={10} />
              }
            </div>
            {i < events.length - 1 && <div className="tl-line" />}
          </div>
          {/* Content */}
          <div className="tl-content">
            <div className="tl-top">
              <span className={`tl-label text-${e.color}`}>{e.label}</span>
              <span className="tl-svc">{e.service}</span>
              {e.state && <span className={`tl-state state-${e.state?.toLowerCase()}`}>{e.state}</span>}
              {e.tier && <span className="tl-tier">{e.tier}</span>}
              {e.ms && <span className="tl-ms">{(e.ms / 1000).toFixed(1)}s</span>}
              <span className="tl-time">{e.time ? new Date(e.time).toLocaleTimeString() : ''}</span>
            </div>
          </div>
        </div>
      ))}
      <style>{`
        .timeline { display: flex; flex-direction: column; max-height: 400px; overflow-y: auto; }
        .tl-item  { display: flex; gap: 12px; min-height: 36px; }
        .tl-left  { display: flex; flex-direction: column; align-items: center; }
        .tl-dot   { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .tl-dot-green  { background: var(--green-dim); color: var(--green); border: 1px solid rgba(34,197,94,.4); }
        .tl-dot-red    { background: var(--red-dim);   color: var(--red);   border: 1px solid rgba(239,68,68,.4); }
        .tl-dot-amber  { background: var(--amber-dim); color: var(--amber); border: 1px solid rgba(245,158,11,.4); }
        .tl-line { flex: 1; width: 1px; background: var(--border); margin: 3px 0; }
        .tl-content { flex: 1; padding-bottom: 10px; }
        .tl-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .tl-label { font-size: 12px; font-weight: 600; }
        .tl-svc   { font-size: 10px; color: var(--text-muted); }
        .tl-state { font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 99px; }
        .state-known    { background: rgba(34,197,94,.15); color: var(--green); }
        .state-probable { background: rgba(245,158,11,.15); color: var(--amber); }
        .state-unknown  { background: rgba(168,85,247,.15); color: var(--purple); }
        .tl-tier  { font-size: 9px; color: var(--cyan); padding: 1px 5px; border-radius: 99px; background: var(--cyan-dim); }
        .tl-ms    { font-size: 10px; font-family: var(--font-mono); color: var(--text-secondary); }
        .tl-time  { font-size: 10px; color: var(--text-muted); margin-left: auto; }
        .text-green { color: var(--green); }
        .text-red   { color: var(--red); }
        .text-amber { color: var(--amber); }
      `}</style>
    </div>
  )
}
