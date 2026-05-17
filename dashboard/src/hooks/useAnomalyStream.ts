import { useEffect, useRef, useState } from 'react'

import { fetchRecentAnomalies, ApiError } from '../api/client'
import { config } from '../config'
import type {
  AnomalyEvent,
  UseAnomalyStreamOptions,
  UseAnomalyStreamResult,
} from '../types'

/**
 * Transport-abstracted anomaly stream.
 *
 * Phase 1 implements the `poll` transport only. The `ws` slot is reserved so
 * components don't need to change when Phase 2 ships — they keep calling
 * `useAnomalyStream()` and the wire choice flips below the hook surface.
 *
 * On API error we keep the previous `anomalies` array intact so a brief outage
 * doesn't blank the feed.
 */
export function useAnomalyStream(
  opts: UseAnomalyStreamOptions = {},
): UseAnomalyStreamResult {
  const {
    transport = config.transport,
    pollIntervalMs = config.pollIntervalMs,
    service,
    limit = config.maxAnomaliesInFeed,
  } = opts

  // Hard fail in dev for unimplemented transport — production silently degrades.
  if (transport === 'ws' && import.meta.env.DEV) {
    throw new Error(
      'WebSocket transport not implemented in Phase 1. Set VITE_TRANSPORT=poll.',
    )
  }

  const [anomalies, setAnomalies] = useState<AnomalyEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Mutable ref so the polling loop sees the latest filter values without
  // having to restart on every parent re-render that doesn't actually change
  // the parameters semantically.
  const paramsRef = useRef({ service, limit })
  paramsRef.current = { service, limit }

  useEffect(() => {
    if (transport !== 'poll') {
      setError('WebSocket transport not yet available')
      setIsConnected(false)
      return
    }

    let cancelled = false
    const controller = new AbortController()

    const tick = async () => {
      try {
        const res = await fetchRecentAnomalies(
          { service: paramsRef.current.service, limit: paramsRef.current.limit },
          controller.signal,
        )
        if (cancelled) return
        setAnomalies(res.anomalies)
        setIsConnected(true)
        setLastUpdated(new Date())
        setError(null)
      } catch (err) {
        if (cancelled) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        const msg = err instanceof ApiError ? err.message : (err as Error).message
        setError(msg)
        setIsConnected(false)
        // Note: we intentionally do NOT clear `anomalies` — stale data is
        // better than a blank panel during a transient outage.
      }
    }

    void tick()
    const handle = window.setInterval(tick, pollIntervalMs)

    return () => {
      cancelled = true
      controller.abort()
      window.clearInterval(handle)
    }
  }, [transport, pollIntervalMs, service, limit])

  return { anomalies, isConnected, lastUpdated, error }
}
