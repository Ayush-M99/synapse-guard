import { useState, useEffect, useCallback, useRef } from 'react'

const DARWIN_BASE  = '/api/darwin'
const POLL_MS      = 3000

async function get(path)  { const r = await fetch(`${DARWIN_BASE}${path}`); return r.json() }
async function post(path, body) {
  const r = await fetch(`${DARWIN_BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

export function useDarwinAPI() {
  const [health,     setHealth]     = useState(null)
  const [pods,       setPods]       = useState(null)
  const [anomalies,  setAnomalies]  = useState(null)
  const [recoveries, setRecoveries] = useState(null)
  const [immunity,   setImmunity]   = useState(null)
  const [faults,     setFaults]     = useState([])
  const pollRef = useRef(null)

  const fetchAll = useCallback(async () => {
    try {
      const [h, p, a, r, i] = await Promise.allSettled([
        get('/health'),
        get('/pods'),
        get('/anomalies'),
        get('/recoveries'),
        get('/immunity'),
      ])
      if (h.status === 'fulfilled') setHealth(h.value)
      if (p.status === 'fulfilled') setPods(p.value)
      if (a.status === 'fulfilled') setAnomalies(a.value)
      if (r.status === 'fulfilled') setRecoveries(r.value)
      if (i.status === 'fulfilled') setImmunity(i.value)
    } catch { /* API down — keep previous state */ }
  }, [])

  useEffect(() => {
    fetchAll()
    pollRef.current = setInterval(fetchAll, POLL_MS)
    return () => clearInterval(pollRef.current)
  }, [fetchAll])

  const injectFault = useCallback(async (payload) => {
    const result = await post('/inject-fault', payload)
    // Track active faults locally
    if (result?.result?.fault_id) {
      setFaults(prev => [...prev.filter(f => f.fault_id !== result.result.fault_id), result.result])
    }
    fetchAll()
    return result
  }, [fetchAll])

  const triggerRecover = useCallback(async (payload) => {
    const result = await post('/recover', payload)
    // Remove from active faults on recovery
    if (payload.strand_id) {
      setFaults(prev => prev.filter(f => f.fault_id !== payload.strand_id))
    }
    fetchAll()
    return result
  }, [fetchAll])

  return { health, pods, anomalies, recoveries, immunity, faults, injectFault, triggerRecover }
}
