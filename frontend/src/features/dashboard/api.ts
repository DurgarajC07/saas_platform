import { apiClient } from '@/shared/api/client'
import type {
  DashboardOverview,
  CallVolumeResponse,
  AgentPerfRow,
  AnalyticsResponse,
  LiveCallsSnapshot,
  DateRange,
} from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard API calls  —  all endpoints under /dashboard
// ─────────────────────────────────────────────────────────────────────────────

export const dashboardApi = {
  /** GET /dashboard/overview — 4 stat cards + deltas */
  getOverview: async (): Promise<DashboardOverview> => {
    const { data } = await apiClient.get<DashboardOverview>('/dashboard/overview')
    return data
  },

  /** GET /dashboard/call-volume?period=7d|30d */
  getCallVolume: async (period = '7d'): Promise<CallVolumeResponse> => {
    const { data } = await apiClient.get<CallVolumeResponse>('/dashboard/call-volume', {
      params: { period },
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

  /** GET /dashboard/live-calls  — REST snapshot (used for initial load / polling fallback) */
  getLiveCalls: async (): Promise<LiveCallsSnapshot> => {
    const { data } = await apiClient.get<LiveCallsSnapshot>('/dashboard/live-calls')
    return data
  },
}
