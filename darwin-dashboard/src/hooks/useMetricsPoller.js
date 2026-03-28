import { useState, useEffect, useRef } from 'react'

const SERVICES = ['auth-service','api-gateway','order-service','payment-service','inventory-service','notification-service']
const DARWIN_BASE = '/api/darwin'

function computeAnomalyScore(metricsMap) {
  let totalScore = 0
  let count      = 0
  for (const svc of Object.keys(metricsMap)) {
    const m = metricsMap[svc]
    const score = (
      (m.cpu_usage_pct        ?? 0) * 0.25 +
      (m.http_error_rate_5xx  ?? 0) * 3.0  +
      (m.request_latency_p99  ?? 0) * 0.15 +
      (m.pod_restart_count_delta ?? 0) * 0.3
    )
    totalScore += Math.min(1, score)
    count++
  }
  return count > 0 ? totalScore / count : 0
}

export function useMetricsPoller() {
  const [metrics, setMetrics]     = useState({})
  const [history, setHistory]     = useState([])
  const pollRef   = useRef(null)

  useEffect(() => {
    const poll = async () => {
      try {
        // Poll all services in parallel
        const results = await Promise.allSettled(
          SERVICES.map(svc =>
            fetch(`${DARWIN_BASE}/metrics?service=${svc}`)
              .then(r => r.json())
              .then(d => [svc, d.metrics])
          )
        )

        const metricsMap = {}
        results.forEach(r => {
          if (r.status === 'fulfilled' && r.value) {
            const [svc, m] = r.value
            if (m) metricsMap[svc] = m
          }
        })

        if (Object.keys(metricsMap).length > 0) {
          setMetrics(metricsMap)
          const scoreNow = computeAnomalyScore(metricsMap)
          setHistory(prev => [
            ...prev.slice(-120),  // keep last 10 min (5s interval)
            { t: Date.now(), anomaly_score: scoreNow, services: metricsMap },
          ])
        }
      } catch { /* API down */ }
    }

    poll()
    pollRef.current = setInterval(poll, 5000)
    return () => clearInterval(pollRef.current)
  }, [])

  return { metrics, history }
}
