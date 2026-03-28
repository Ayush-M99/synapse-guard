import { useState, useEffect, useRef } from 'react'
import { Shield, Play, Square, Sliders, Users } from 'lucide-react'

const PROFILES = [
  { id: 'normal',     label: 'Normal',      users: 20,  rate: 2,  color: 'green',  desc: 'Baseline e-commerce traffic' },
  { id: 'stress',     label: 'Stress',      users: 100, rate: 10, color: 'amber',  desc: 'High load — IF anomaly trigger' },
  { id: 'spike',      label: 'Spike',       users: 200, rate: 50, color: 'red',    desc: 'Sudden burst — timing attack sim' },
  { id: 'camouflage', label: 'Camouflage',  users: 80,  rate: 1,  color: 'purple', desc: 'Slow ramp — CUSUM drift target' },
]

export default function LocustControl() {
  const [profile,  setProfile]  = useState('normal')
  const [users,    setUsers]    = useState(20)
  const [rate,     setRate]     = useState(2)
  const [running,  setRunning]  = useState(false)
  const [stats,    setStats]    = useState(null)
  const pollRef = useRef(null)

  const selectedProfile = PROFILES.find(p => p.id === profile)

  const applyProfile = (p) => {
    setProfile(p.id)
    setUsers(p.users)
    setRate(p.rate)
  }

  const startLocust = async () => {
    try {
      await fetch('/api/locust/swarm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `user_count=${users}&spawn_rate=${rate}`,
      })
      setRunning(true)
      pollRef.current = setInterval(fetchStats, 2000)
    } catch (e) {
      // Locust web UI not running — show manual command
      setStats({ manual: true, cmd: `locust -f locust/locustfile.py --host http://localhost:30080 --users ${users} --spawn-rate ${rate} --headless --run-time 60s` })
    }
  }

  const stopLocust = async () => {
    try {
      await fetch('/api/locust/stop', { method: 'GET' })
    } catch {}
    setRunning(false)
    clearInterval(pollRef.current)
  }

  const fetchStats = async () => {
    try {
      const r = await fetch('/api/locust/stats/requests')
      if (r.ok) setStats(await r.json())
    } catch {}
  }

  useEffect(() => () => clearInterval(pollRef.current), [])

  return (
    <div className="locust-panel">
      {/* Profile selector */}
      <div className="locust-profiles">
        {PROFILES.map(p => (
          <button
            key={p.id}
            className={`profile-chip ${p.color} ${profile === p.id ? 'selected' : ''}`}
            onClick={() => applyProfile(p)}
          >
            <Users size={11} />
            <span>{p.label}</span>
            <span className="profile-users">{p.users}u</span>
          </button>
        ))}
      </div>

      {selectedProfile && (
        <div className="profile-desc">{selectedProfile.desc}</div>
      )}

      {/* Controls */}
      <div className="locust-controls">
        <div className="locust-slider">
          <label>Users: <strong>{users}</strong></label>
          <input type="range" min={1} max={500} value={users}
                 onChange={e => setUsers(+e.target.value)} className="fi-slider" />
        </div>
        <div className="locust-slider">
          <label>Spawn rate: <strong>{rate}/s</strong></label>
          <input type="range" min={1} max={100} value={rate}
                 onChange={e => setRate(+e.target.value)} className="fi-slider" />
        </div>
        <div className="locust-actions">
          {!running ? (
            <button className="btn-big btn-big-green" onClick={startLocust}>
              <Play size={14} /> Start Load
            </button>
          ) : (
            <button className="btn-big btn-big-red" onClick={stopLocust}>
              <Square size={14} /> Stop
            </button>
          )}
        </div>
      </div>

      {/* Live stats or manual command */}
      {stats?.manual ? (
        <div className="locust-cmd">
          <div className="locust-cmd-label">Run manually in WSL:</div>
          <code className="locust-cmd-code">{stats.cmd}</code>
          <div style={{marginTop: 8, fontSize: 11, color: 'var(--text-muted)'}}>
            Then open <a href="http://localhost:8089" target="_blank" rel="noreferrer"
              style={{color: 'var(--cyan)'}}>http://localhost:8089</a> for the Locust UI
          </div>
        </div>
      ) : stats ? (
        <LocustStats stats={stats} />
      ) : null}

      <style>{`
        .locust-panel { display: flex; flex-direction: column; gap: 14px; }
        .locust-profiles { display: flex; gap: 8px; flex-wrap: wrap; }
        .profile-chip { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; border: 1px solid transparent; cursor: pointer; transition: all .15s; }
        .profile-chip.green  { background: var(--green-dim);  color: var(--green);  border-color: rgba(34,197,94,.2); }
        .profile-chip.amber  { background: var(--amber-dim);  color: var(--amber);  border-color: rgba(245,158,11,.2);}
        .profile-chip.red    { background: var(--red-dim);    color: var(--red);    border-color: rgba(239,68,68,.2); }
        .profile-chip.purple { background: var(--purple-dim); color: var(--purple); border-color: rgba(168,85,247,.2);}
        .profile-chip.selected { box-shadow: 0 0 0 2px currentColor; }
        .profile-users { font-family: var(--font-mono); font-size: 10px; }
        .profile-desc { font-size: 11px; color: var(--text-muted); padding: 6px 10px; background: var(--bg-card2); border-radius: 6px; }
        .locust-controls { display: grid; grid-template-columns: 1fr 1fr auto; align-items: end; gap: 14px; }
        .locust-slider { display: flex; flex-direction: column; gap: 6px; }
        .locust-slider label { font-size: 11px; color: var(--text-muted); }
        .locust-slider strong { color: var(--cyan); }
        .locust-actions { }
        .locust-cmd { background: var(--bg-card2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
        .locust-cmd-label { font-size: 11px; color: var(--text-muted); margin-bottom: 6px; }
        .locust-cmd-code { display: block; font-family: var(--font-mono); font-size: 11px; color: var(--cyan); overflow-x: auto; white-space: nowrap; }
      `}</style>
    </div>
  )
}

function LocustStats({ stats }) {
  const total   = stats?.stats?.find(s => s.name === 'Aggregated') ?? {}
  const rps     = total.current_rps ?? 0
  const failPct = total.num_requests > 0 ? ((total.num_failures / total.num_requests) * 100).toFixed(1) : 0
  const p99     = total.response_time_percentile_99 ?? 0

  return (
    <div className="locust-stats-row">
      {[
        { label: 'Req/s',      value: rps.toFixed(1),   color: 'cyan' },
        { label: 'Failures',   value: `${failPct}%`,    color: failPct > 5 ? 'red' : 'green' },
        { label: 'P99 latency',value: `${p99}ms`,       color: p99 > 1000 ? 'amber' : 'green' },
        { label: 'Users',      value: stats?.user_count ?? 0, color: 'purple' },
      ].map(s => (
        <div key={s.label} className="lstat">
          <div className={`lstat-val text-${s.color}`}>{s.value}</div>
          <div className="lstat-label">{s.label}</div>
        </div>
      ))}
      <style>{`
        .locust-stats-row { display: flex; gap: 8px; }
        .lstat { flex: 1; background: var(--bg-card2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; text-align: center; }
        .lstat-val { font-size: 18px; font-weight: 700; font-family: var(--font-mono); }
        .lstat-label { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
        .text-cyan { color: var(--cyan); }
        .text-green { color: var(--green); }
        .text-red { color: var(--red); }
        .text-amber { color: var(--amber); }
        .text-purple { color: var(--purple); }
      `}</style>
    </div>
  )
}
