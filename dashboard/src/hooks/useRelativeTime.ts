import { useEffect, useState } from 'react'

const REFRESH_MS = 30_000

function formatRelative(target: Date, now: Date): string {
  const diffMs = now.getTime() - target.getTime()
  const sec = Math.round(diffMs / 1000)
  if (sec < 5) return 'just now'
  if (sec < 60) return `${sec}s ago`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const days = Math.round(hr / 24)
  return `${days}d ago`
}

/**
 * Returns a "X min ago"-style string that auto-refreshes every 30s. Does NOT
 * trigger any data refetches — purely a render-loop timer.
 */
export function useRelativeTime(input: Date | string | null | undefined): string {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), REFRESH_MS)
    return () => window.clearInterval(id)
  }, [])

  if (input == null) return ''
  const target = input instanceof Date ? input : new Date(input)
  if (isNaN(target.getTime())) return ''
  return formatRelative(target, now)
}
