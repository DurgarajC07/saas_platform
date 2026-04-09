import { apiClient } from '@/shared/api/client'
import type {
  DashboardOverview,
  CallVolumeResponse,
  AgentPerfRow,
  AnalyticsResponse,
  DateRange,
} from './schemas'

/** Parse a period string like '7d' | '30d' into `days` + `granularity` for the backend. */
function parsePeriod(period: string): { days: number; granularity: string } {
  const m = /^(\d+)([dhm])$/.exec(period)
  if (!m) return { days: 7, granularity: 'day' }
  const n = parseInt(m[1], 10)
  const unit = m[2]
  if (unit === 'h') return { days: 1, granularity: 'hour' }
  if (unit === 'm') return { days: n * 30, granularity: 'month' }
  return { days: n, granularity: 'day' }
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard API calls  —  all endpoints under /dashboard
// ─────────────────────────────────────────────────────────────────────────────

export const dashboardApi = {
  /** GET /dashboard/overview — 4 stat cards + deltas */
  getOverview: async (): Promise<DashboardOverview> => {
    const { data } = await apiClient.get<DashboardOverview>('/dashboard/overview')
    return data
  },

  /** GET /dashboard/call-volume?days=N&granularity=day|hour|month */
  getCallVolume: async (period = '7d'): Promise<CallVolumeResponse> => {
    const { data } = await apiClient.get<CallVolumeResponse>('/dashboard/call-volume', {
      params: parsePeriod(period),
    })
    return data
  },

  /** GET /dashboard/agent-performance?days=7 */
  getAgentPerformance: async (days = 7): Promise<AgentPerfRow[]> => {
    const { data } = await apiClient.get<AgentPerfRow[]>('/dashboard/agent-performance', {
      params: { days },
    })
    return data
  },

  /** GET /dashboard/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD */
  getAnalytics: async (range: DateRange): Promise<AnalyticsResponse> => {
    const { data } = await apiClient.get<AnalyticsResponse>('/dashboard/analytics', {
      params: { from: range.from, to: range.to },
    })
    return data
  },
}
