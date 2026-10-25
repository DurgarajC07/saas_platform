import { apiClient } from '@/shared/api/client'
import type {
  CallLogResponse,
  CallLogListResponse,
  RecordingUrlResponse,
  AgentAnalyticsResponse,
} from './schemas'

interface AgentCallListParams {
  page?: number
  pageSize?: number
  status?: string
}

interface CallListParams extends AgentCallListParams {
  agentId?: string
}

// ─────────────────────────────────────────────────────────────────────────────
// Calls API  —  org-wide list at GET /calls, agent-scoped list under
// /agents/:id/calls, detail/recording under /calls/:id
// ─────────────────────────────────────────────────────────────────────────────

export const callsApi = {
  /** GET /calls — org-wide, optionally filtered by agent_id */
  listCalls: async (params?: CallListParams): Promise<CallLogListResponse> => {
    const { data } = await apiClient.get<CallLogListResponse>('/calls', {
      params: {
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 20,
        ...(params?.status && { status: params.status }),
        ...(params?.agentId && { agent_id: params.agentId }),
      },
    })
    return data
  },

  /** GET /agents/:id/calls */
  listAgentCalls: async (
    agentId: string,
    params?: AgentCallListParams,
  ): Promise<CallLogListResponse> => {
    const { data } = await apiClient.get<CallLogListResponse>(`/agents/${agentId}/calls`, {
      params: {
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 20,
        ...(params?.status && { status: params.status }),
      },
    })
    return data
  },

  /** GET /calls/:id */
  getCall: async (callId: string): Promise<CallLogResponse> => {
    const { data } = await apiClient.get<CallLogResponse>(`/calls/${callId}`)
    return data
  },

  /** GET /calls/:id/recording */
  getRecordingUrl: async (callId: string): Promise<RecordingUrlResponse> => {
    const { data } = await apiClient.get<RecordingUrlResponse>(`/calls/${callId}/recording`)
    return data
  },

  /** GET /agents/:id/analytics */
  getAgentAnalytics: async (agentId: string, days = 30): Promise<AgentAnalyticsResponse> => {
    const { data } = await apiClient.get<AgentAnalyticsResponse>(`/agents/${agentId}/analytics`, {
      params: { days },
    })
    return data
  },
}
