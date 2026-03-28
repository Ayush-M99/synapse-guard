import { useState, useEffect } from 'react'
import { Activity, Cpu, Shield, Wifi } from 'lucide-react'

export default function Header({ health }) {
  const status = health?.status ?? 'connecting...'
  const isHealthy = status === 'healthy'

  return (
    <header className="header">
      {/* Logo */}
      <div className="logo">
        <div className="logo-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <div>
          <div className="logo-name">DARWIN</div>
          <div className="logo-sub">Autonomous Chaos Platform</div>
        </div>
      </div>

      {/* Center status */}
      <div className="header-center">
        <div className={`status-pill ${isHealthy ? 'healthy' : 'degraded'}`}>
          <span className={`status-dot ${isHealthy ? 'green' : 'red'}`} />
          <span>{status}</span>
        </div>
        <div className="header-stats">
          <div className="hstat">
            <Cpu size={11} />
            <span>ML Pipeline</span>
            <span className="hstat-val">Active</span>
          </div>
          <div className="hstat-sep" />
          <div className="hstat">
            <Wifi size={11} />
            <span>DARWIN API</span>
            <span className="hstat-val">:9000</span>
          </div>
          <div className="hstat-sep" />
          <div className="hstat">
            <Shield size={11} />
            <span>Active Faults</span>
            <span className="hstat-val">{health?.active_faults ?? 0}</span>
          </div>
        </div>
      </div>

      {/* Right — live clock */}
      <div className="header-right">
        <LiveClock />
        <div className="version-badge">v1.0</div>
      </div>

      <style>{`
        .header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 20px; height: 52px; flex-shrink: 0;
          background: var(--bg-base);
          border-bottom: 1px solid var(--border);
        }
        .logo {
          display: flex; align-items: center; gap: 10px;
        }
        .logo-icon {
          width: 34px; height: 34px; border-radius: 8px;
          background: linear-gradient(135deg, var(--cyan-dim), var(--purple-dim));
          border: 1px solid var(--border-bright);
          display: flex; align-items: center; justify-content: center;
          color: var(--cyan);
        }
        .logo-name { font-size: 15px; font-weight: 800; letter-spacing: 0.12em; color: var(--text-primary); }
        .logo-sub  { font-size: 9px;  font-weight: 400; color: var(--text-muted);  letter-spacing: 0.08em; }
        .header-center { display: flex; align-items: center; gap: 16px; }
        .status-pill    { display: flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 99px; font-size: 11px; font-weight: 600; }
        .status-pill.healthy  { background: var(--green-dim); border: 1px solid rgba(34,197,94,.3); color: var(--green); }
        .status-pill.degraded { background: var(--red-dim);   border: 1px solid rgba(239,68,68,.3);  color: var(--red); }
        .status-dot { width: 6px; height: 6px; border-radius: 50%; }
        .status-dot.green { background: var(--green); animation: pulse-glow 1.5s ease-in-out infinite; box-shadow: 0 0 6px var(--green); }
        .status-dot.red   { background: var(--red); }
        .header-stats { display: flex; align-items: center; gap: 0; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
        .hstat { display: flex; align-items: center; gap: 5px; padding: 5px 10px; font-size: 10px; color: var(--text-muted); }
        .hstat-val { color: var(--cyan); font-weight: 600; font-family: var(--font-mono); }
        .hstat-sep { width: 1px; height: 16px; background: var(--border); }
        .header-right { display: flex; align-items: center; gap: 10px; }
        .version-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 99px; background: var(--purple-dim); color: var(--purple); border: 1px solid rgba(168,85,247,.3); }
      `}</style>
    </header>
  )
}

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
      {time.toLocaleTimeString()}
    </div>
  )
}

