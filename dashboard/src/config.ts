import type { Transport } from './types'

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  transport: (import.meta.env.VITE_TRANSPORT ?? 'poll') as Transport,
  pollIntervalMs: Number(import.meta.env.VITE_POLL_INTERVAL_MS ?? 5000),
  healthPollIntervalMs: 10000,
  anomalyWindowMinutes: 5,
  defaultPageSize: 100,
  maxAnomaliesInFeed: 50,
} as const
