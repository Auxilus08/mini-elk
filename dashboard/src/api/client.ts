import { config } from '../config'
import type {
  AnomalyListResponse,
  HealthResponse,
  LogSearchResponse,
} from '../types'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type QueryValue = string | number | boolean | null | undefined

function buildQueryString(params: Record<string, QueryValue>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  )
  if (entries.length === 0) return ''
  const search = new URLSearchParams()
  for (const [k, v] of entries) search.append(k, String(v))
  return `?${search.toString()}`
}

async function get<T>(path: string, params: Record<string, QueryValue> = {}, signal?: AbortSignal): Promise<T> {
  const url = `${config.apiBaseUrl}${path}${buildQueryString(params)}`
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, url, `network error: ${(err as Error).message}`)
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body.detail ?? ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new ApiError(
      response.status,
      url,
      detail || `HTTP ${response.status}`,
    )
  }
  return (await response.json()) as T
}

export function fetchRecentAnomalies(
  params: { service?: string; severity?: string; anomaly_type?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AnomalyListResponse> {
  return get<AnomalyListResponse>('/anomalies/recent', params, signal)
}

export function fetchAnomalyWindowLogs(
  anomalyId: string,
  params: { level?: string; size?: number } = {},
  signal?: AbortSignal,
): Promise<LogSearchResponse> {
  return get<LogSearchResponse>(`/logs/anomaly-window/${encodeURIComponent(anomalyId)}`, params, signal)
}

export function fetchLogs(
  params: {
    service?: string
    level?: string
    from_ts?: string
    to_ts?: string
    q?: string
    size?: number
    offset?: number
  },
  signal?: AbortSignal,
): Promise<LogSearchResponse> {
  // Translate from_ts/to_ts → from/to per Phase 1D's query param aliases.
  const { from_ts, to_ts, ...rest } = params
  return get<LogSearchResponse>('/logs/search', { ...rest, from: from_ts, to: to_ts }, signal)
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return get<HealthResponse>('/health', {}, signal)
}
