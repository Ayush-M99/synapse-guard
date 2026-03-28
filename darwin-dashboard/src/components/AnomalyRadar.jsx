import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, Tooltip } from 'recharts'

const SERVICES = ['auth','gateway','order','payment','inventory','notify']
const SVC_MAP = {
  'auth-service': 'auth', 'api-gateway': 'gateway', 'order-service': 'order',
  'payment-service': 'payment', 'inventory-service': 'inventory', 'notification-service': 'notify'
}

export default function AnomalyRadar({ metrics }) {
  const data = SERVICES.map(svc => {
    const fullName = Object.keys(SVC_MAP).find(k => SVC_MAP[k] === svc) ?? svc
    const m = metrics?.[fullName] ?? {}
    const health = Math.max(0, 100 - (
      (m.cpu_usage_pct ?? 0) * 0.3 +
      (m.http_error_rate_5xx ?? 0) * 200 +
      (m.request_latency_p99 ?? 0) * 20 +
      (m.pod_restart_count_delta ?? 0) * 30
    ))
    return { service: svc, health: Math.round(Math.min(100, health)) }
  })

  return (
    <div style={{ height: 160 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 24 }}>
          <PolarGrid stroke="rgba(99,130,255,0.15)" />
          <PolarAngleAxis dataKey="service" tick={{ fontSize: 10, fill: '#8899cc' }} />
          <Radar name="Health" dataKey="health" stroke="#00e5ff" fill="#00e5ff"
                 fillOpacity={0.12} strokeWidth={1.5} />
          <Tooltip
            contentStyle={{ background: 'var(--bg-card2)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 11 }}
            formatter={(v) => [`${v}%`, 'Health']}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
