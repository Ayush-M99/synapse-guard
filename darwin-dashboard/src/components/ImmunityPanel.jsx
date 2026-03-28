import { Dna, Zap } from 'lucide-react'

export default function ImmunityPanel({ immunity }) {
  const entries = immunity?.immunity ?? {}
  const keys    = Object.keys(entries)

  if (!keys.length) {
    return (
      <div className="ip-empty">
        <Dna size={32} className="icon-purple" />
        <p>No T-cell memory yet</p>
        <span>T-cells are created after each successful recovery</span>
      </div>
    )
  }

  return (
    <div className="ip-list">
      {keys.map(strandId => {
        const pb = entries[strandId] ?? {}
        return (
          <div key={strandId} className="ip-item animate-fade-in">
            <div className="ip-icon">
              <Zap size={12} className="icon-green" />
            </div>
            <div className="ip-body">
              <div className="ip-strand">{strandId}</div>
              <div className="ip-actions">{(pb.actions ?? []).join(' → ')}</div>
              <div className="ip-source">source: {pb.source ?? 'cache'}</div>
            </div>
            <div className="ip-badge">CACHED</div>
          </div>
        )
      })}
      <style>{`
        .ip-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px 0; color: var(--text-muted); }
        .ip-empty p { font-size: 14px; font-weight: 500; color: var(--text-secondary); }
        .ip-empty span { font-size: 11px; text-align: center; }
        .ip-list  { display: flex; flex-direction: column; gap: 8px; max-height: 280px; overflow-y: auto; }
        .ip-item  { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; background: var(--bg-card2); border: 1px solid var(--border); }
        .ip-icon  { width: 28px; height: 28px; background: var(--green-dim); border-radius: 6px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .ip-body  { flex: 1; min-width: 0; }
        .ip-strand { font-size: 12px; font-weight: 600; font-family: var(--font-mono); color: var(--cyan); }
        .ip-actions { font-size: 11px; color: var(--text-muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .ip-source  { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
        .ip-badge   { font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 99px; background: var(--green-dim); color: var(--green); border: 1px solid rgba(34,197,94,.3); flex-shrink: 0; }
      `}</style>
    </div>
  )
}
