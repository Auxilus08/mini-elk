import { useEffect, useState } from 'react'

import { AnomalyFeed } from './components/AnomalyFeed'
import { LogDrillDown } from './components/LogDrillDown'
import { ServiceHealthGrid } from './components/ServiceHealthGrid'
import { useServiceHealth } from './hooks/useServiceHealth'
import { formatDuration } from './lib/formatters'
import type { AnomalyEvent } from './types'

import './App.css'

export default function App() {
  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyEvent | null>(null)
  const { esStatus, status, uptimeSeconds, isConnected } = useServiceHealth()
  const clock = useWallClock()

  const clusterClass = `cluster-${esStatus}`

  return (
    <div className="app">
      <header className="topbar mono">
        <div className="topbar-left">
          <span className="brand">
            <span className="brand-mark">▰</span>
            <span className="brand-name">MINI-ELK</span>
          </span>
          <span className="topbar-sep">·</span>
          <span className={`topbar-item ${clusterClass}`}>
            <span className="uplabel">ES</span>
            <span className="topbar-value">{esStatus.toUpperCase()}</span>
          </span>
          <span className="topbar-sep">·</span>
          <span className={`topbar-item system-${status ?? 'unknown'}`}>
            <span className="uplabel">SYS</span>
            <span className="topbar-value">{(status ?? 'init').toUpperCase()}</span>
          </span>
          <span className="topbar-sep">·</span>
          <span className="topbar-item">
            <span className="uplabel">UP</span>
            <span className="topbar-value">{formatDuration(uptimeSeconds)}</span>
          </span>
        </div>
        <div className="topbar-right">
          <span className={`topbar-connection ${isConnected ? 'is-live' : 'is-stale'}`}>
            <span className="topbar-connection-dot" aria-hidden="true" />
            <span className="uplabel">{isConnected ? 'live' : 'stale'}</span>
          </span>
          <span className="topbar-sep">·</span>
          <span className="topbar-clock">{clock}</span>
        </div>
      </header>

      <main className="main-grid">
        <section className="col-left">
          <ServiceHealthGrid />
        </section>
        <section className="col-right">
          <AnomalyFeed
            onAnomalySelect={setSelectedAnomaly}
            selectedAnomalyId={selectedAnomaly?.id}
          />
        </section>
      </main>

      <LogDrillDown
        anomaly={selectedAnomaly}
        onClose={() => setSelectedAnomaly(null)}
      />
    </div>
  )
}

function useWallClock(): string {
  const [now, setNow] = useState(() => formatClock(new Date()))
  useEffect(() => {
    const id = window.setInterval(() => setNow(formatClock(new Date())), 1000)
    return () => window.clearInterval(id)
  }, [])
  return now
}

function formatClock(d: Date): string {
  return d.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
