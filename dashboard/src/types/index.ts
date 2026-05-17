export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'critical'

export type AnomalyType =
  | 'error_rate_spike'
  | 'log_volume_spike'
  | 'service_silence'
  | 'latency_spike'

export type Severity = 'warning' | 'critical'

export interface LogEvent {
  timestamp: string
  service: string
  level: LogLevel
  message: string
  trace_id: string
  duration_ms?: number
  http_method?: string
  http_status?: number
  http_path?: string
  host?: string
}

export interface AnomalyEvent {
  id: string
  timestamp: string
  anomaly_type: AnomalyType
  service: string
  severity: Severity
  z_score: number
  current_value: number
  baseline_mean: number
  baseline_stddev: number
  window_seconds: number
  sample_count: number
  threshold_used: number
  sampled_trace_ids: string[]
  resolved: boolean
}

export type ServiceStatus = 'healthy' | 'degraded' | 'anomalous'

export interface ServiceHealth {
  service: string
  status: ServiceStatus
  error_rate_1m: number
  log_volume_1m: number
  last_anomaly_at: string | null
  last_anomaly_type: string | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  es_cluster_status: string
  services: ServiceHealth[]
  uptime_seconds: number
}

export interface LogSearchResponse {
  total: number
  hits: LogEvent[]
  anomaly_id: string | null
}

export interface AnomalyListResponse {
  total: number
  anomalies: AnomalyEvent[]
}

// Transport abstraction
export type Transport = 'poll' | 'ws'

export interface UseAnomalyStreamOptions {
  transport?: Transport
  pollIntervalMs?: number
  service?: string
  limit?: number
}

export interface UseAnomalyStreamResult {
  anomalies: AnomalyEvent[]
  isConnected: boolean
  lastUpdated: Date | null
  error: string | null
}
