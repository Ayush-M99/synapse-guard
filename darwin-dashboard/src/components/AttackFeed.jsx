import { AlertTriangle, Shield, Zap } from 'lucide-react'
import { useRef, useEffect } from 'react'

const FAMILY_COLOR = {
  pod_crash: 'red', network: 'amber', resource: 'purple',
  timing: 'cyan', camouflage: 'purple', unknown: 'text-muted'
}

export default function AttackFeed({ anomalies }) {
  const listRef = useRef(null)

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = 0
    }
  }, [anomalies.length])

  if (!anomalies.length) {
    return (
      <div className="feed-empty">
        <Shield size={28} className="icon-green" />
        <span>No anomalies detected</span>
        <span className="feed-sub">ML pipeline monitoring all services</span>
      </div>
    )
  }

  return (
    <div className="feed-list" ref={listRef}>
      {anomalies.slice(0, 12).map((a, i) => {
        const color = FAMILY_COLOR[a.rf_label] ?? 'text-muted'
        const ts = a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ''
        return (
          <div key={i} className="feed-item animate-fade-in">
            <div className="feed-icon-wrap">
              {a.attack_state === 'KNOWN' ? (
                <Shield size={12} className={`icon-${color}`} />
              ) : (
                <AlertTriangle size={12} className="icon-amber animate-pulse-glow" />
              )}
            </div>
            <div className="feed-body">
              <div className="feed-top">
                <span className={`feed-label text-${color}`}>{a.rf_label}</span>
                <span className={`feed-state state-${a.attack_state?.toLowerCase()}`}>
                  {a.attack_state}
                </span>
              </div>
              <div className="feed-bottom">
                <span className="feed-svc">{a.service}</span>
                <span className="feed-score">score: {(a.anomaly_score ?? 0).toFixed(2)}</span>
                <span className="feed-ts">{ts}</span>
              </div>
            </div>
            <div className="feed-conf">
              <div className="conf-bar-bg">
                <div className="conf-bar-fill" style={{ width: `${(a.rf_confidence ?? 0) * 100}%` }} />
              </div>
              <span className="conf-val">{((a.rf_confidence ?? 0) * 100).toFixed(0)}%</span>
            </div>
          </div>
        )
      })}
      <style>{`
        .feed-list  { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; }
        .feed-item  { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; background: var(--bg-card2); border: 1px solid var(--border); transition: border-color .2s; }
        .feed-item:hover { border-color: var(--border-bright); }
        .feed-icon-wrap { width: 24px; height: 24px; border-radius: 6px; background: var(--bg-hover); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .feed-body  { flex: 1; min-width: 0; }
        .feed-top   { display: flex; align-items: center; gap: 6px; }
        .feed-label { font-size: 12px; font-weight: 600; }
        .feed-state { font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 99px; text-transform: uppercase; }
        .state-known    { background: rgba(34,197,94,.15);  color: var(--green); }
        .state-probable { background: rgba(245,158,11,.15); color: var(--amber); }
        .state-unknown  { background: rgba(168,85,247,.15); color: var(--purple); }
        .feed-bottom { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
        .feed-svc   { font-size: 10px; color: var(--text-muted); }
        .feed-score { font-size: 10px; color: var(--text-secondary); font-family: var(--font-mono); }
        .feed-ts    { font-size: 10px; color: var(--text-muted); margin-left: auto; }
        .feed-conf  { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
        .conf-bar-bg   { width: 40px; height: 3px; background: var(--bg-hover); border-radius: 2px; }
        .conf-bar-fill { height: 100%; background: linear-gradient(90deg, var(--cyan), var(--purple)); border-radius: 2px; }
        .conf-val { font-size: 9px; font-family: var(--font-mono); color: var(--text-muted); width: 26px; }
        .feed-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 24px 0; color: var(--text-muted); }
        .feed-sub { font-size: 11px; }
        .text-red    { color: var(--red); }
        .text-amber  { color: var(--amber); }
        .text-cyan   { color: var(--cyan); }
        .text-purple { color: var(--purple); }
        .text-muted  { color: var(--text-muted); }
      `}</style>
    </div>
  )
}
