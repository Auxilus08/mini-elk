import { LineChart, Line, ResponsiveContainer } from 'recharts'

import { useRelativeTime } from '../hooks/useRelativeTime'
import { anomalyTypeLabel, formatAnomalyValues } from '../lib/formatters'
import type { AnomalyEvent } from '../types'

import './AnomalyCard.css'

interface AnomalyCardProps {
  anomaly: AnomalyEvent
  onSelect: (anomaly: AnomalyEvent) => void
  isSelected?: boolean
  index?: number  // stagger reveal
}

// We don't have a real per-bucket history from the API in Phase 1, so
// synthesise: 9 baseline points + 1 current. This makes the spike legible
// against the baseline at-a-glance. Phase 2 can swap to real data.
function sparklineData(anomaly: AnomalyEvent): Array<{ i: number; v: number }> {
  const baseline = anomaly.baseline_mean
  const current = anomaly.current_value
  // Slight per-point jitter against the baseline so it doesn't look like a
  // perfectly flat line — keeps the eye on the final spike.
  const jitter = (Math.max(baseline, 0.001)) * 0.08
  const points: Array<{ i: number; v: number }> = []
  for (let i = 0; i < 9; i++) {
    // Deterministic pseudo-jitter from the anomaly id so the line is stable
    // across renders (and across users looking at the same anomaly).
    const seed = (anomaly.id.charCodeAt(i % anomaly.id.length) % 7) - 3
    points.push({ i, v: Math.max(0, baseline + seed * jitter * 0.4) })
  }
  points.push({ i: 9, v: current })
  return points
}

export function AnomalyCard({ anomaly, onSelect, isSelected = false, index = 0 }: AnomalyCardProps) {
  const relative = useRelativeTime(anomaly.timestamp)
  const { current, baseline } = formatAnomalyValues(anomaly)
  const data = sparklineData(anomaly)
  const sparkColor = anomaly.severity === 'critical' ? 'var(--critical)' : 'var(--warning)'
  const baselineY = anomaly.baseline_mean

  return (
    <button
      type="button"
      className={`anomaly-card severity-${anomaly.severity}${isSelected ? ' is-selected' : ''}`}
      onClick={() => onSelect(anomaly)}
      aria-pressed={isSelected}
      style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
    >
      <span className="severity-rule" aria-hidden="true" />

      <div className="ac-row top">
        <span className={`severity-pip severity-${anomaly.severity}`}>
          {anomaly.severity}
        </span>
        <span className="ac-type">{anomalyTypeLabel(anomaly.anomaly_type)}</span>
        <span className="ac-time mono" title={anomaly.timestamp}>{relative}</span>
      </div>

      <div className="ac-row mid">
        <span className="service-pill mono">{anomaly.service}</span>
        <span className="ac-zscore mono" title={`threshold: ${anomaly.threshold_used}σ`}>
          <span className="ac-zlabel">σ</span>
          <span className="ac-zvalue">{anomaly.z_score.toFixed(2)}</span>
        </span>
      </div>

      <div className="ac-row values">
        <div className="value-block">
          <div className="value-current mono">{current}</div>
          <div className="value-baseline mono">{baseline}</div>
        </div>
        <div className="sparkline" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
              {/* Faint baseline reference line as a horizontal dashed segment */}
              <Line
                type="linear"
                dataKey={() => baselineY}
                stroke="var(--fg-dim)"
                strokeWidth={1}
                strokeDasharray="2 2"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="v"
                stroke={sparkColor}
                strokeWidth={1.5}
                dot={(props) =>
                  props.index === data.length - 1 ? (
                    <circle
                      cx={props.cx}
                      cy={props.cy}
                      r={2.5}
                      fill={sparkColor}
                      stroke="var(--bg-elev-1)"
                      strokeWidth={1}
                    />
                  ) : (
                    <g />
                  )
                }
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </button>
  )
}
