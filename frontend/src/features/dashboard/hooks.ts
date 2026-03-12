import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '@/shared/api/query-keys'
import { dashboardApi } from './api'
import type { DateRange } from './schemas'

// ─── useOverview ──────────────────────────────────────────────────────────────
export function useOverview() {
  return useQuery({
    queryKey: queryKeys.dashboard.overview(),
    queryFn: dashboardApi.getOverview,
    refetchInterval: 30_000, // auto-refresh every 30 s
    staleTime: 10_000,
  })
}

// ─── useCallVolume ────────────────────────────────────────────────────────────
export function useCallVolume(period = '7d') {
  return useQuery({
    queryKey: queryKeys.dashboard.callVolume(period),
    queryFn: () => dashboardApi.getCallVolume(period),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useAgentPerformance ──────────────────────────────────────────────────────
export function useAgentPerformance(days = 7) {
  return useQuery({
    queryKey: queryKeys.dashboard.agentPerf(days),
    queryFn: () => dashboardApi.getAgentPerformance(days),
    staleTime: 60_000,
    refetchInterval: 60_000,
  })
}

// ─── useAnalytics ─────────────────────────────────────────────────────────────
export function useAnalytics(range: DateRange) {
  return useQuery({
    queryKey: queryKeys.dashboard.analytics(range.from, range.to),
    queryFn: () => dashboardApi.getAnalytics(range),
    staleTime: 2 * 60 * 1000,
    enabled: Boolean(range.from && range.to),
  })
}
