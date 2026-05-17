import { useEffect, useState } from 'react'

import { ApiError, fetchHealth } from '../api/client'
import { config } from '../config'
import type { HealthResponse, ServiceHealth } from '../types'

export interface UseServiceHealthResult {
  services: ServiceHealth[]
  esStatus: string
  status: HealthResponse['status'] | null
  uptimeSeconds: number | null
  isConnected: boolean
  lastUpdated: Date | null
  error: string | null
}

export function useServiceHealth(
  pollIntervalMs: number = config.healthPollIntervalMs,
): UseServiceHealthResult {
  const [services, setServices] = useState<ServiceHealth[]>([])
  const [esStatus, setEsStatus] = useState<string>('unknown')
  const [status, setStatus] = useState<HealthResponse['status'] | null>(null)
  const [uptimeSeconds, setUptimeSeconds] = useState<number | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    const tick = async () => {
      try {
        const res = await fetchHealth(controller.signal)
        if (cancelled) return
        setServices(res.services)
        setEsStatus(res.es_cluster_status)
        setStatus(res.status)
        setUptimeSeconds(res.uptime_seconds)
        setIsConnected(true)
        setLastUpdated(new Date())
        setError(null)
      } catch (err) {
        if (cancelled) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        const msg = err instanceof ApiError ? err.message : (err as Error).message
        setError(msg)
        setIsConnected(false)
      }
    }

    void tick()
    const handle = window.setInterval(tick, pollIntervalMs)
    return () => {
      cancelled = true
      controller.abort()
      window.clearInterval(handle)
    }
  }, [pollIntervalMs])

  return { services, esStatus, status, uptimeSeconds, isConnected, lastUpdated, error }
}
