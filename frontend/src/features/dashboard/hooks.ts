import { useMemo } from 'react'
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

// ─── useLiveCallsSnapshot ─────────────────────────────────────────────────────
/** REST snapshot — used as initial data before SSE kicks in */
export function useLiveCallsSnapshot() {
  return useQuery({
    queryKey: queryKeys.calls.live(),
    queryFn: dashboardApi.getLiveCalls,
    refetchInterval: 10_000,
    staleTime: 5_000,
  })
}

// ─── useLiveCallTable ─────────────────────────────────────────────────────────
/**
 * Merges SSE live frames into the REST snapshot, deduplicated by call ID.
 * Returns a stable sorted array (newest first) suitable for a table.
 */
import { useSSE } from '@/features/realtime/useSSE'
import type { LiveCall, LiveCallsSnapshot } from './schemas'

export function useLiveCallTable() {
  const snapshot = useLiveCallsSnapshot()
  const { data: sseFrame, status: sseStatus } = useSSE<LiveCallsSnapshot>(
    '/dashboard/live-calls/stream',
  )

  const calls = useMemo<LiveCall[]>(() => {
    const base = snapshot.data?.calls ?? []
    const live = sseFrame?.calls ?? []
    // Merge: SSE frame is authoritative for its IDs
    const map = new Map<string, LiveCall>(base.map((c) => [c.id, c]))
    for (const c of live) map.set(c.id, c)
    return [...map.values()].sort(
      (a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime(),
    )
  }, [snapshot.data, sseFrame])

  return {
    calls,
    isLoading: snapshot.isLoading,
    sseStatus,
  }
}
