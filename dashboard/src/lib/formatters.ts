import type { AnomalyEvent, AnomalyType } from '../types'

const ANOMALY_TYPE_LABELS: Record<AnomalyType, string> = {
  error_rate_spike: 'Error Rate Spike',
  log_volume_spike: 'Log Volume Spike',
  service_silence: 'Service Silence',
  latency_spike: 'Latency Spike',
}

export function anomalyTypeLabel(t: string): string {
  if (t in ANOMALY_TYPE_LABELS) return ANOMALY_TYPE_LABELS[t as AnomalyType]
  // Fallback for unknown types: turn snake_case into Title Case so we never
  // leak raw machine names into the UI.
  return t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Returns a (currentLabel, baselineLabel) pair for an anomaly. */
export function formatAnomalyValues(
  anomaly: AnomalyEvent,
): { current: string; baseline: string } {
  switch (anomaly.anomaly_type) {
    case 'error_rate_spike':
      return {
        current: `${(anomaly.current_value * 100).toFixed(1)}% errors`,
        baseline: `baseline: ${(anomaly.baseline_mean * 100).toFixed(1)}%`,
      }
    case 'log_volume_spike':
      return {
        current: `${Math.round(anomaly.current_value)} req/min`,
        baseline: `baseline: ${anomaly.baseline_mean.toFixed(1)} req/min`,
      }
    case 'service_silence':
      return {
        current: '0 events',
        baseline: `baseline: ${anomaly.baseline_mean.toFixed(1)} req/min`,
      }
    case 'latency_spike':
      return {
        current: `${Math.round(anomaly.current_value)}ms`,
        baseline: `baseline: ${Math.round(anomaly.baseline_mean)}ms`,
      }
    default:
      return {
        current: anomaly.current_value.toFixed(2),
        baseline: `baseline: ${anomaly.baseline_mean.toFixed(2)}`,
      }
  }
}

export function formatAbsoluteTime(ts: string | Date): string {
  const d = ts instanceof Date ? ts : new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null || isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}
