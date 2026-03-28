import { Server, CheckCircle, AlertTriangle, RotateCcw } from 'lucide-react'

export default function ServiceGrid({ pods, metrics }) {
  const SERVICES = ['auth-service','api-gateway','order-service','payment-service','inventory-service','notification-service']

  return (
    <div className="sg-grid">
      {SERVICES.map(svc => {
        const pod  = pods?.find(p => p.labels?.app === svc)
        const m    = metrics?.[svc] ?? {}
        const healthy = pod?.ready ?? false
        const restarts = pod?.restarts ?? 0
        return (
          <div key={svc} className={`sg-card ${healthy ? 'healthy' : 'unhealthy'}`}>
            <div className="sg-header">
              <div className="sg-icon">
                <Server size={12} />
              </div>
              <div className="sg-name">{svc.replace('-service', '')}</div>
              <div className={`sg-dot ${healthy ? 'green' : 'red'}`} />
            </div>
            <div className="sg-metrics">
              <div className="sg-metric">
                <span className="sg-key">CPU</span>
                <div className="sg-bar-bg">
                  <div className="sg-bar-fill"
                       style={{ width: `${Math.min(100, m.cpu_usage_pct ?? 0)}%`,
                                background: (m.cpu_usage_pct ?? 0) > 70 ? 'var(--red)' : 'var(--cyan)' }} />
                </div>
                <span className="sg-val">{(m.cpu_usage_pct ?? 0).toFixed(0)}%</span>
              </div>
              <div className="sg-metric">
                <span className="sg-key">Err</span>
                <span className={`sg-val-big ${(m.http_error_rate_5xx ?? 0) > 0.05 ? 'red' : 'green'}`}>
                  {((m.http_error_rate_5xx ?? 0) * 100).toFixed(1)}%
                </span>
              </div>
            </div>
            {restarts > 0 && (
              <div className="sg-restarts">
                <RotateCcw size={10} className="icon-amber" />
                <span>{restarts} restarts</span>
              </div>
            )}
          </div>
        )
      })}
      <style>{`
        .sg-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
        .sg-card { background: var(--bg-card2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px; transition: all .2s; }
        .sg-card.healthy   { border-left: 3px solid var(--green); }
        .sg-card.unhealthy { border-left: 3px solid var(--red);   background: rgba(239,68,68,.03); }
        .sg-header { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
        .sg-icon   { width: 20px; height: 20px; background: var(--bg-hover); border-radius: 4px; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }
        .sg-name   { font-size: 11px; font-weight: 600; flex: 1; }
        .sg-dot    { width: 7px; height: 7px; border-radius: 50%; }
        .sg-dot.green { background: var(--green); box-shadow: 0 0 5px var(--green); animation: pulse-glow 2s infinite; }
        .sg-dot.red   { background: var(--red);   }
        .sg-metrics { display: flex; flex-direction: column; gap: 6px; }
        .sg-metric  { display: flex; align-items: center; gap: 5px; }
        .sg-key     { font-size: 9px; color: var(--text-muted); width: 22px; }
        .sg-bar-bg  { flex: 1; height: 3px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
        .sg-bar-fill{ height: 100%; transition: width .5s; }
        .sg-val     { font-size: 10px; font-family: var(--font-mono); color: var(--text-secondary); width: 28px; text-align: right; }
        .sg-val-big { font-size: 12px; font-weight: 700; font-family: var(--font-mono); }
        .sg-val-big.red   { color: var(--red); }
        .sg-val-big.green { color: var(--green); }
        .sg-restarts { display: flex; align-items: center; gap: 4px; margin-top: 6px; font-size: 10px; color: var(--amber); }
        @media (max-width: 1200px) { .sg-grid { grid-template-columns: repeat(3, 1fr); } }
        @media (max-width: 800px)  { .sg-grid { grid-template-columns: repeat(2, 1fr); } }
      `}</style>
    </div>
  )
}
