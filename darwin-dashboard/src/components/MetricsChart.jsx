import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

export default function MetricsChart({ history }) {
  const data = (history || []).map((h, i) => ({
    t:    i,
    score: parseFloat((h.anomaly_score ?? 0).toFixed(3)),
    threshold: 0.65,
  })).slice(-60)

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null
    return (
      <div style={{ background: 'var(--bg-card2)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 10px', fontSize: 11 }}>
        <div style={{ color: 'var(--cyan)' }}>Score: {payload[0]?.value}</div>
      </div>
    )
  }

  return (
    <div style={{ height: 160 }}>
      {data.length === 0 ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: 12 }}>
          Waiting for ML pipeline data...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="anomalyGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#00e5ff" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#00e5ff" stopOpacity={0}   />
              </linearGradient>
              <linearGradient id="dangerGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0}   />
              </linearGradient>
            </defs>
            <XAxis dataKey="t" hide />
            <YAxis domain={[0, 1]} hide />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0.65} stroke="#f59e0b" strokeDasharray="4 4"
              label={{ value: 'Threshold', position: 'right', fontSize: 9, fill: '#f59e0b' }} />
            <Area type="monotone" dataKey="score" stroke="#00e5ff" strokeWidth={2}
                  fill="url(#anomalyGrad)" dot={false} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
