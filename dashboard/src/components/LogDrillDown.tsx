import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, fetchAnomalyWindowLogs } from '../api/client'
import { useRelativeTime } from '../hooks/useRelativeTime'
import {
  anomalyTypeLabel,
  formatAbsoluteTime,
  formatAnomalyValues,
} from '../lib/formatters'
import type { AnomalyEvent, LogEvent } from '../types'

import './LogDrillDown.css'

interface LogDrillDownProps {
  anomaly: AnomalyEvent | null
  onClose: () => void
}

type LevelTab = 'all' | 'error' | 'warn' | 'info'
const LEVEL_TABS: ReadonlyArray<{ key: LevelTab; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'error', label: 'Error' },
  { key: 'warn', label: 'Warn' },
  { key: 'info', label: 'Info' },
]

const INITIAL_PAGE_SIZE = 200
const PAGE_INCREMENT = 200

export function LogDrillDown({ anomaly, onClose }: LogDrillDownProps) {
  const [logs, setLogs] = useState<LogEvent[]>([])
  const [level, setLevel] = useState<LevelTab>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [traceFilter, setTraceFilter] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(INITIAL_PAGE_SIZE)

  // Escape closes the panel.
  useEffect(() => {
    if (!anomaly) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [anomaly, onClose])

  // Reset transient state when the anomaly changes.
  useEffect(() => {
    setTraceFilter(null)
    setVisibleCount(INITIAL_PAGE_SIZE)
    setLevel('all')
  }, [anomaly?.id])

  // Fetch on anomaly + level change.
  useEffect(() => {
    if (!anomaly) return
    let cancelled = false
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    const lvl = level === 'all' ? undefined : level
    fetchAnomalyWindowLogs(anomaly.id, { level: lvl, size: 500 }, controller.signal)
      .then((r) => {
        if (cancelled) return
        setLogs(r.hits)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        const msg = err instanceof ApiError ? err.message : (err as Error).message
        setError(msg)
        setLogs([])
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [anomaly?.id, level])

  const filtered = useMemo(() => {
    if (!traceFilter) return logs
    return logs.filter((l) => l.trace_id === traceFilter)
  }, [logs, traceFilter])

  const visible = filtered.slice(0, visibleCount)
  const hasMore = filtered.length > visible.length

  const isOpen = anomaly !== null

  return (
    <>
      <div
        className={`ldd-backdrop${isOpen ? ' is-open' : ''}`}
        onClick={onClose}
        aria-hidden={!isOpen}
      />
      <aside
        className={`ldd-panel${isOpen ? ' is-open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={anomaly ? `Logs for ${anomaly.anomaly_type} on ${anomaly.service}` : undefined}
      >
        {anomaly && (
          <PanelBody
            anomaly={anomaly}
            logs={visible}
            totalFiltered={filtered.length}
            level={level}
            onLevelChange={setLevel}
            loading={loading}
            error={error}
            traceFilter={traceFilter}
            onTraceFilter={setTraceFilter}
            hasMore={hasMore}
            onLoadMore={useCallback(
              () => setVisibleCount((c) => c + PAGE_INCREMENT),
              [],
            )}
            onClose={onClose}
          />
        )}
      </aside>
    </>
  )
}

interface PanelBodyProps {
  anomaly: AnomalyEvent
  logs: LogEvent[]
  totalFiltered: number
  level: LevelTab
  onLevelChange: (l: LevelTab) => void
  loading: boolean
  error: string | null
  traceFilter: string | null
  onTraceFilter: (t: string | null) => void
  hasMore: boolean
  onLoadMore: () => void
  onClose: () => void
}

function PanelBody({
  anomaly,
  logs,
  totalFiltered,
  level,
  onLevelChange,
  loading,
  error,
  traceFilter,
  onTraceFilter,
  hasMore,
  onLoadMore,
  onClose,
}: PanelBodyProps) {
  const relative = useRelativeTime(anomaly.timestamp)
  const { current, baseline } = formatAnomalyValues(anomaly)
  const window = (anomaly.window_seconds / 60).toFixed(0)

  return (
    <>
      <header className="ldd-header">
        <div className="ldd-header-top">
          <span className={`severity-pip severity-${anomaly.severity}`}>
            {anomaly.severity}
          </span>
          <h2 className="ldd-title">{anomalyTypeLabel(anomaly.anomaly_type)}</h2>
          <button type="button" className="ldd-close" onClick={onClose} aria-label="Close panel">
            ×
          </button>
        </div>
        <div className="ldd-header-sub">
          <span className="service-pill mono">{anomaly.service}</span>
          <span className="ldd-meta mono" title={anomaly.timestamp}>{relative}</span>
        </div>

        <dl className="ldd-summary mono">
          <SummaryItem label="z-score" value={`σ ${anomaly.z_score.toFixed(2)}`} />
          <SummaryItem label="current" value={current} accent={anomaly.severity} />
          <SummaryItem label={baseline.replace(/^baseline:\s*/, 'baseline')} value="" hideValue />
          <SummaryItem label="window" value={`${window} min`} />
          <SummaryItem label="samples" value={anomaly.sample_count.toLocaleString()} />
          <SummaryItem label="threshold" value={`${anomaly.threshold_used}σ`} />
        </dl>

        {anomaly.sampled_trace_ids.length > 0 && (
          <div className="ldd-traces">
            <span className="uplabel ldd-traces-label">sampled traces</span>
            <div className="ldd-trace-tags">
              {anomaly.sampled_trace_ids.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`ldd-trace-tag mono${traceFilter === t ? ' is-active' : ''}`}
                  onClick={() => onTraceFilter(traceFilter === t ? null : t)}
                  title={`Filter logs to trace ${t}`}
                >
                  {t.length > 12 ? `${t.slice(0, 12)}…` : t}
                </button>
              ))}
              {traceFilter && (
                <button
                  type="button"
                  className="ldd-trace-clear"
                  onClick={() => onTraceFilter(null)}
                >
                  clear filter
                </button>
              )}
            </div>
          </div>
        )}

        <nav className="ldd-tabs" role="tablist">
          {LEVEL_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={level === tab.key}
              className={`ldd-tab${level === tab.key ? ' is-active' : ''}`}
              onClick={() => onLevelChange(tab.key)}
            >
              {tab.label}
            </button>
          ))}
          <span className="ldd-tab-count mono">
            {loading ? 'loading…' : `${totalFiltered} events`}
          </span>
        </nav>
      </header>

      <div className="ldd-table-wrap">
        {error ? (
          <div className="ldd-error mono">
            <span className="uplabel">fetch failed</span>
            <span>{error}</span>
          </div>
        ) : loading && logs.length === 0 ? (
          <SkeletonRows count={8} />
        ) : logs.length === 0 ? (
          <div className="ldd-empty">
            <span className="uplabel">empty window</span>
            <p>No logs in the ±{window} min window match the current filters.</p>
          </div>
        ) : (
          <>
            <table className="ldd-table">
              <thead>
                <tr>
                  <th className="col-time uplabel">time</th>
                  <th className="col-level uplabel">level</th>
                  <th className="col-message uplabel">message</th>
                  <th className="col-trace uplabel">trace</th>
                  <th className="col-duration uplabel">dur</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log, i) => (
                  <LogRow key={`${log.timestamp}-${i}`} log={log} />
                ))}
              </tbody>
            </table>
            {hasMore && (
              <div className="ldd-load-more">
                <button type="button" className="ldd-load-more-btn mono" onClick={onLoadMore}>
                  load {Math.min(PAGE_INCREMENT, totalFiltered - logs.length).toLocaleString()} more
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

function LogRow({ log }: { log: LogEvent }) {
  return (
    <tr className={`ldd-row level-${log.level}`}>
      <td className="col-time mono">{formatAbsoluteTime(log.timestamp)}</td>
      <td className="col-level">
        <span className={`level-badge level-${log.level} mono`}>{log.level}</span>
      </td>
      <td className="col-message">
        <span className="ldd-msg">{log.message}</span>
        {log.http_path && (
          <span className="ldd-http mono">
            {log.http_method} {log.http_path}
            {log.http_status != null && <> · {log.http_status}</>}
          </span>
        )}
      </td>
      <td className="col-trace mono" title={log.trace_id}>
        {log.trace_id.slice(0, 8)}
      </td>
      <td className="col-duration mono">
        {log.duration_ms != null ? `${log.duration_ms.toFixed(0)}ms` : '—'}
      </td>
    </tr>
  )
}

function SummaryItem({
  label,
  value,
  accent,
  hideValue,
}: { label: string; value: string; accent?: 'warning' | 'critical'; hideValue?: boolean }) {
  return (
    <div className="ldd-summary-item">
      <dt className="uplabel">{label}</dt>
      {!hideValue && (
        <dd className={`ldd-summary-value${accent ? ` accent-${accent}` : ''}`}>{value}</dd>
      )}
    </div>
  )
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="ldd-skeleton">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="ldd-skeleton-row" style={{ animationDelay: `${i * 40}ms` }} />
      ))}
    </div>
  )
}
