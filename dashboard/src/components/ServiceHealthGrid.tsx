import { useServiceHealth } from '../hooks/useServiceHealth'
import { useRelativeTime } from '../hooks/useRelativeTime'
import { anomalyTypeLabel } from '../lib/formatters'
import type { ServiceHealth } from '../types'

import './ServiceHealthGrid.css'

const STATUS_LABEL: Record<ServiceHealth['status'], string> = {
  healthy: 'operational',
  degraded: 'degraded',
  anomalous: 'anomalous',
}

export function ServiceHealthGrid() {
  const { services, esStatus, error } = useServiceHealth()

  return (
    <section className="health-grid">
      <header className="hg-header">
        <h2 className="hg-title">Services</h2>
        <span className="uplabel hg-count">{services.length} tracked</span>
      </header>

      <div className="hg-cluster mono">
        <span className="uplabel hg-cluster-label">elasticsearch</span>
        <span className={`hg-cluster-status status-${esStatus}`}>{esStatus}</span>
      </div>

      {error && (
        <div className="hg-error mono">
          <span className="uplabel">offline</span>
          <span>{error}</span>
        </div>
      )}

      <div className="hg-list">
        {services.length === 0 && !error && (
          <div className="hg-empty">
            <span className="uplabel">awaiting telemetry</span>
            <p>No services have emitted in the last 60 seconds.</p>
          </div>
        )}
        {services.map((s) => (
          <ServiceStrip key={s.service} svc={s} />
        ))}
      </div>
    </section>
  )
}

function ServiceStrip({ svc }: { svc: ServiceHealth }) {
  const lastAnomalyRel = useRelativeTime(svc.last_anomaly_at)
  const errorRatePct = Math.min(100, svc.error_rate_1m * 100)

  return (
    <article className={`hg-strip status-${svc.status}`}>
      <div className="hg-strip-top">
        <span className={`hg-dot status-${svc.status}`} aria-hidden="true" />
        <span className="hg-service-name mono">{svc.service}</span>
        <span className={`hg-status-tag status-${svc.status}`}>
          {STATUS_LABEL[svc.status]}
        </span>
      </div>

      <div className="hg-strip-metrics">
        <Metric label="err rate" value={`${(svc.error_rate_1m * 100).toFixed(2)}%`} />
        <Metric label="vol /min" value={svc.log_volume_1m.toLocaleString()} />
      </div>

      <div className="hg-bar" aria-hidden="true">
        <div
          className={`hg-bar-fill status-${svc.status}`}
          style={{ width: `${errorRatePct}%` }}
        />
      </div>

      <div className="hg-anomaly">
        {svc.last_anomaly_at && svc.last_anomaly_type ? (
          <>
            <span className="uplabel">last anomaly</span>
            <span className="hg-anomaly-text">
              <span className="hg-anomaly-type">{anomalyTypeLabel(svc.last_anomaly_type)}</span>
              <span className="hg-anomaly-time mono">· {lastAnomalyRel}</span>
            </span>
          </>
        ) : (
          <span className="hg-anomaly-clear uplabel">no recent anomalies</span>
        )}
      </div>
    </article>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="hg-metric">
      <div className="hg-metric-value mono">{value}</div>
      <div className="uplabel hg-metric-label">{label}</div>
    </div>
  )
}
