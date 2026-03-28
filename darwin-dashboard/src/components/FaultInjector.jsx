import { useState } from 'react'
import { AlertTriangle, Zap, RefreshCw, ChevronDown } from 'lucide-react'

const SERVICES = ['auth-service','api-gateway','order-service','payment-service','inventory-service','notification-service']
const FAULT_TYPES = [
  { id: 'pod_crash',       label: 'Pod Crash',       color: 'red',    desc: 'Force-delete pod — K8s restarts via Deployment controller' },
  { id: 'scale_down',      label: 'Scale to Zero',   color: 'red',    desc: 'Scale deployment to 0 replicas — total service outage' },
  { id: 'cpu_stress',      label: 'CPU Stress',      color: 'amber',  desc: 'Deploy busybox CPU hog pod — resource pressure' },
  { id: 'memory_hog',      label: 'Memory Hog',      color: 'amber',  desc: 'Deploy memory-consuming pod — OOM pressure' },
  { id: 'network_latency', label: 'Network Latency', color: 'purple', desc: 'Inject 2s latency via Istio VirtualService' },
]

export default function FaultInjector({ onInject, onRecover }) {
  const [service,   setService]   = useState('payment-service')
  const [faultType, setFaultType] = useState('pod_crash')
  const [duration,  setDuration]  = useState(0)
  const [loading,   setLoading]   = useState(false)
  const [result,    setResult]    = useState(null)

  const selectedFault = FAULT_TYPES.find(f => f.id === faultType)

  const handleInject = async () => {
    setLoading(true)
    setResult(null)
    try {
      const r = await onInject({ service, fault_type: faultType, duration_seconds: duration })
      setResult({ ok: true,  msg: `Fault injected: ${r?.result?.fault_id ?? 'OK'}` })
    } catch {
      setResult({ ok: false, msg: 'Injection failed' })
    } finally {
      setLoading(false)
    }
  }

  const handleRecover = async () => {
    setLoading(true)
    try {
      await onRecover({ service, strand_id: faultType, attack_family: faultType.replace(/_\w+/, ''), rf_confidence: 0.9, anomaly_score: 0.85 })
      setResult({ ok: true, msg: 'Recovery triggered!' })
    } catch {
      setResult({ ok: false, msg: 'Recovery failed' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fault-injector">
      {/* Service selector */}
      <div className="fi-field">
        <label className="fi-label">Target Service</label>
        <div className="fi-select-wrap">
          <select className="fi-select" value={service} onChange={e => setService(e.target.value)}>
            {SERVICES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <ChevronDown size={12} className="fi-chevron" />
        </div>
      </div>

      {/* Fault type grid */}
      <div className="fi-field">
        <label className="fi-label">Fault Type</label>
        <div className="fault-grid">
          {FAULT_TYPES.map(f => (
            <button
              key={f.id}
              className={`fault-chip ${f.color} ${faultType === f.id ? 'selected' : ''}`}
              onClick={() => setFaultType(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        {selectedFault && (
          <div className="fault-desc">{selectedFault.desc}</div>
        )}
      </div>

      {/* Duration */}
      <div className="fi-field">
        <label className="fi-label">Auto-recover after (0 = manual)</label>
        <div className="fi-slider-row">
          <input type="range" min={0} max={120} step={10} value={duration}
                 onChange={e => setDuration(+e.target.value)} className="fi-slider" />
          <span className="fi-slider-val">{duration === 0 ? 'manual' : `${duration}s`}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="fi-actions">
        <button
          className={`btn-big btn-big-red ${loading ? 'loading' : ''}`}
          onClick={handleInject}
          disabled={loading}
        >
          <AlertTriangle size={16} />
          {loading ? 'Injecting...' : 'Inject Fault'}
        </button>
        <button
          className={`btn-big btn-big-green ${loading ? 'loading' : ''}`}
          onClick={handleRecover}
          disabled={loading}
        >
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          Recover Now
        </button>
      </div>

      {/* Result */}
      {result && (
        <div className={`fi-result ${result.ok ? 'ok' : 'err'}`}>
          {result.msg}
        </div>
      )}

      <style>{`
        .fault-injector { display: flex; flex-direction: column; gap: 16px; }
        .fi-field { display: flex; flex-direction: column; gap: 6px; }
        .fi-label { font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
        .fi-select-wrap { position: relative; }
        .fi-select { width: 100%; background: var(--bg-card2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; color: var(--text-primary); font-size: 13px; appearance: none; cursor: pointer; outline: none; }
        .fi-select:focus { border-color: var(--cyan); }
        .fi-chevron { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); color: var(--text-muted); pointer-events: none; }
        .fault-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
        .fault-chip { padding: 7px 10px; border-radius: 8px; font-size: 11px; font-weight: 600; border: 1px solid transparent; cursor: pointer; transition: all .15s; text-align: center; }
        .fault-chip.red    { background: var(--red-dim);    color: var(--red);    border-color: rgba(239,68,68,.2);   }
        .fault-chip.amber  { background: var(--amber-dim);  color: var(--amber);  border-color: rgba(245,158,11,.2);  }
        .fault-chip.purple { background: var(--purple-dim); color: var(--purple); border-color: rgba(168,85,247,.2);  }
        .fault-chip.selected { box-shadow: 0 0 0 2px currentColor; transform: scale(1.03); }
        .fault-desc { font-size: 11px; color: var(--text-muted); padding: 6px 10px; background: var(--bg-card2); border-radius: 6px; border-left: 2px solid var(--cyan-dim); }
        .fi-slider-row { display: flex; align-items: center; gap: 10px; }
        .fi-slider { flex: 1; -webkit-appearance: none; height: 4px; border-radius: 2px; background: var(--bg-hover); outline: none; }
        .fi-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: var(--cyan); cursor: pointer; }
        .fi-slider-val { font-family: var(--font-mono); font-size: 12px; color: var(--cyan); min-width: 50px; text-align: right; }
        .fi-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .btn-big { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 11px 16px; border: none; border-radius: 10px; font-size: 13px; font-weight: 700; cursor: pointer; transition: all .15s; }
        .btn-big-red   { background: var(--red-dim);   color: var(--red);   border: 1px solid rgba(239,68,68,.3); }
        .btn-big-red:hover:not(:disabled) { background: var(--red); color: #fff; box-shadow: 0 0 20px rgba(239,68,68,.4); }
        .btn-big-green { background: var(--green-dim); color: var(--green); border: 1px solid rgba(34,197,94,.3); }
        .btn-big-green:hover:not(:disabled) { background: var(--green); color: #fff; box-shadow: 0 0 20px rgba(34,197,94,.4); }
        .btn-big:disabled { opacity: .5; cursor: not-allowed; }
        .fi-result { padding: 8px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; }
        .fi-result.ok  { background: var(--green-dim); color: var(--green); border: 1px solid rgba(34,197,94,.3); }
        .fi-result.err { background: var(--red-dim);   color: var(--red);   border: 1px solid rgba(239,68,68,.3); }
        .spin { animation: rotate-slow 1s linear infinite; }
      `}</style>
    </div>
  )
}
