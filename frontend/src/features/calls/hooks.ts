import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '@/shared/api/query-keys'
import { callsApi } from './api'

interface AgentCallsParams {
  page?: number
  pageSize?: number
  status?: string
}

// ─── useCalls ──────────────────────────────────────────────────────────────────
interface CallsParams {
  page?: number
  pageSize?: number
  status?: string
  agentId?: string
}

export function useCalls(params: CallsParams = {}) {
  return useQuery({
    queryKey: queryKeys.calls.list({
      page: params.page,
      pageSize: params.pageSize,
      status: params.status,
      agentId: params.agentId,
    }),
    queryFn: () => callsApi.listCalls(params),
    placeholderData: (prev) => prev,
  })
}

// ─── useAgentCalls ─────────────────────────────────────────────────────────────
export function useAgentCalls(agentId: string | null | undefined, params: AgentCallsParams = {}) {
  return useQuery({
    queryKey: queryKeys.agents.calls(agentId ?? '', {
      page: params.page,
      pageSize: params.pageSize,
      status: params.status,
      agentId: agentId ?? '',
    }),
    queryFn: () => callsApi.listAgentCalls(agentId ?? '', params),
    enabled: Boolean(agentId),
    placeholderData: (prev) => prev,
  })
}

// ─── useCall ───────────────────────────────────────────────────────────────────
export function useCall(callId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.calls.detail(callId ?? ''),
    queryFn: () => callsApi.getCall(callId ?? ''),
    enabled: Boolean(callId),
  })
}

// ─── useRecordingUrl ───────────────────────────────────────────────────────────
export function useRecordingUrl(callId: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.calls.detail(callId ?? ''), 'recording'],
    queryFn: () => callsApi.getRecordingUrl(callId ?? ''),
    enabled: Boolean(callId) && enabled,
  })
}

// ─── useAgentAnalytics ─────────────────────────────────────────────────────────
export function useAgentAnalytics(agentId: string | null | undefined, days = 30) {
  return useQuery({
    queryKey: queryKeys.agents.analytics(agentId ?? '', days),
    queryFn: () => callsApi.getAgentAnalytics(agentId ?? '', days),
    enabled: Boolean(agentId),
  })
}
