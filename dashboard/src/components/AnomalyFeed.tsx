import { useMemo, useState } from 'react'

import { useAnomalyStream } from '../hooks/useAnomalyStream'
import { useRelativeTime } from '../hooks/useRelativeTime'
import type { AnomalyType, Severity } from '../types'

import { AnomalyCard } from './AnomalyCard'
import './AnomalyFeed.css'

interface AnomalyFeedProps {
  onAnomalySelect: (anomaly: import('../types').AnomalyEvent) => void
  selectedAnomalyId?: string
}

const SEVERITY_OPTIONS: ReadonlyArray<{ label: string; value: '' | Severity }> = [
  { label: 'all severity', value: '' },
  { label: 'critical', value: 'critical' },
  { label: 'warning', value: 'warning' },
]

const TYPE_OPTIONS: ReadonlyArray<{ label: string; value: '' | AnomalyType }> = [
  { label: 'all types', value: '' },
  { label: 'Error Rate Spike', value: 'error_rate_spike' },
  { label: 'Latency Spike', value: 'latency_spike' },
  { label: 'Log Volume Spike', value: 'log_volume_spike' },
  { label: 'Service Silence', value: 'service_silence' },
]

export function AnomalyFeed({ onAnomalySelect, selectedAnomalyId }: AnomalyFeedProps) {
  const { anomalies, isConnected, lastUpdated, error } = useAnomalyStream()
  const [severityFilter, setSeverityFilter] = useState<'' | Severity>('')
  const [typeFilter, setTypeFilter] = useState<'' | AnomalyType>('')
  const lastUpdatedRel = useRelativeTime(lastUpdated)

  const filtered = useMemo(() => {
    return anomalies.filter((a) => {
      if (severityFilter && a.severity !== severityFilter) return false
      if (typeFilter && a.anomaly_type !== typeFilter) return false
      return true
    })
  }, [anomalies, severityFilter, typeFilter])

  const statusLabel = error
    ? 'disconnected'
    : isConnected
      ? 'live'
      : 'connecting'
  const statusClass = error
    ? 'status-error'
    : isConnected
      ? 'status-live'
      : 'status-pending'

  return (
    <section className="anomaly-feed">
      <header className="af-header">
        <div className="af-title-block">
          <h2 className="af-title">Anomaly Feed</h2>
          <span className="uplabel af-count">
            {filtered.length}
            {filtered.length !== anomalies.length ? ` / ${anomalies.length}` : ''} events
          </span>
        </div>

        <div className="af-status">
          <span className={`af-status-pip ${statusClass}`} aria-hidden="true" />
          <span className="mono af-status-label">{statusLabel}</span>
          {lastUpdated && (
            <span className="mono af-last-updated" title={lastUpdated.toISOString()}>
              · updated {lastUpdatedRel}
            </span>
          )}
        </div>
      </header>

      <div className="af-filters">
        <FilterSelect
          value={severityFilter}
          onChange={(v) => setSeverityFilter(v as '' | Severity)}
          options={SEVERITY_OPTIONS}
          label="severity"
        />
        <FilterSelect
          value={typeFilter}
          onChange={(v) => setTypeFilter(v as '' | AnomalyType)}
          options={TYPE_OPTIONS}
          label="type"
        />
        {(severityFilter || typeFilter) && (
          <button
            type="button"
            className="af-clear"
            onClick={() => {
              setSeverityFilter('')
              setTypeFilter('')
            }}
          >
            clear
          </button>
        )}
      </div>

      {error && (
        <div className="af-error-bar mono" role="alert">
          <span className="uplabel af-error-tag">api error</span>
          <span className="af-error-msg">{error}</span>
        </div>
      )}

      <div className="af-list">
        {filtered.length === 0 ? (
          anomalies.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="af-empty">
              <div className="uplabel">no matches</div>
              <p>No anomalies match the current filters.</p>
            </div>
          )
        ) : (
          filtered.map((a, idx) => (
            <AnomalyCard
              key={a.id}
              anomaly={a}
              onSelect={onAnomalySelect}
              isSelected={a.id === selectedAnomalyId}
              index={idx}
            />
          ))
        )}
      </div>
    </section>
  )
}

interface FilterSelectProps<T extends string> {
  value: T
  onChange: (v: T) => void
  options: ReadonlyArray<{ label: string; value: T }>
  label: string
}

function FilterSelect<T extends string>({ value, onChange, options, label }: FilterSelectProps<T>) {
  return (
    <label className="af-filter">
      <span className="uplabel af-filter-label">{label}</span>
      <select
        className="mono af-filter-select"
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function EmptyState() {
  return (
    <div className="af-empty af-empty-healthy">
      <div className="af-empty-mark" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="11" stroke="currentColor" strokeWidth="1" opacity="0.4" />
          <circle cx="12" cy="12" r="3" fill="currentColor" />
        </svg>
      </div>
      <div className="af-empty-text">
        <div className="uplabel">all clear</div>
        <p>No anomalies detected — system healthy.</p>
      </div>
    </div>
  )
}
