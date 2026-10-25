import { apiClient } from '@/shared/api/client'
import type {
  AgentResponse,
  AgentListResponse,
  CreateAgentInput,
  AgentPromptResponse,
  AgentPhoneNumberResponse,
  AssignPhoneNumberInput,
} from './schemas'

interface AgentListParams {
  page?: number
  pageSize?: number
  status?: string
  type?: string
  search?: string
}

// ─────────────────────────────────────────────────────────────────────────────
// Agents API  —  all endpoints under /agents
// ─────────────────────────────────────────────────────────────────────────────

export const agentsApi = {
  /** GET /agents */
  listAgents: async (params?: AgentListParams): Promise<AgentListResponse> => {
    const { data } = await apiClient.get<AgentListResponse>('/agents', {
      params: {
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 20,
        ...(params?.status && { status: params.status }),
        ...(params?.type && { agent_type: params.type }),
        ...(params?.search && { search: params.search }),
      },
    })
    return data
  },

  /** GET /agents/:id */
  getAgent: async (id: string): Promise<AgentResponse> => {
    const { data } = await apiClient.get<AgentResponse>(`/agents/${id}`)
    return data
  },

  /** POST /agents */
  createAgent: async (body: CreateAgentInput): Promise<AgentResponse> => {
    const { data } = await apiClient.post<AgentResponse>('/agents', {
      name: body.name,
      agent_type: body.agentType,
      llm_model: body.llmModel,
      temperature: body.temperature,
      max_tokens: body.maxTokens,
      language: body.language || null,
      tts_voice: body.ttsVoice,
      tts_speed: body.ttsSpeed,
      vad_threshold: body.vadThreshold,
      allow_interruptions: body.allowInterruptions,
      noise_removal_level: body.noiseRemovalLevel,
      system_prompt: body.systemPrompt || null,
      welcome_message: body.welcomeMessage || null,
    })
    return data
  },

  /** PATCH /agents/:id */
  updateAgent: async (id: string, body: Partial<CreateAgentInput>): Promise<AgentResponse> => {
    const { data } = await apiClient.patch<AgentResponse>(`/agents/${id}`, body)
    return data
  },

  /** DELETE /agents/:id */
  deleteAgent: async (id: string): Promise<void> => {
    await apiClient.delete(`/agents/${id}`)
  },

  /** PATCH /agents/:id/status — convenience endpoint */
  setStatus: async (id: string, status: string): Promise<AgentResponse> => {
    const { data } = await apiClient.patch<AgentResponse>(`/agents/${id}`, { status })
    return data
  },

  /** POST /agents/bulk — bulk status change */
  bulkUpdate: async (ids: string[], payload: { status?: string }): Promise<{ updated: number }> => {
    const { data } = await apiClient.post<{ updated: number }>('/agents/bulk', {
      agent_ids: ids,
      ...payload,
    })
    return data
  },

  /** DELETE /agents/bulk */
  bulkDelete: async (ids: string[]): Promise<{ deleted: number }> => {
    const { data } = await apiClient.post<{ deleted: number }>('/agents/bulk-delete', {
      agent_ids: ids,
    })
    return data
  },

  /** GET /agents/:id/prompt */
  getPrompt: async (id: string): Promise<AgentPromptResponse> => {
    const { data } = await apiClient.get<AgentPromptResponse>(`/agents/${id}/prompt`)
    return data
  },

  /** PUT /agents/:id/prompt */
  updatePrompt: async (id: string, systemPrompt: string): Promise<AgentPromptResponse> => {
    const { data } = await apiClient.put<AgentPromptResponse>(`/agents/${id}/prompt`, {
      system_prompt: systemPrompt,
    })
    return data
  },

  /** PUT /agents/:id/tools */
  updateTools: async (
    id: string,
    toolsJson: Record<string, unknown>[],
  ): Promise<AgentResponse> => {
    const { data } = await apiClient.put<AgentResponse>(`/agents/${id}/tools`, {
      tools_json: toolsJson,
    })
    return data
  },

  /** GET /agents/:id/phone-numbers */
  listPhoneNumbers: async (id: string): Promise<AgentPhoneNumberResponse[]> => {
    const { data } = await apiClient.get<AgentPhoneNumberResponse[]>(`/agents/${id}/phone-numbers`)
    return data
  },

  /** POST /agents/:id/phone-numbers */
  assignPhoneNumber: async (
    id: string,
    body: AssignPhoneNumberInput,
  ): Promise<AgentPhoneNumberResponse> => {
    const { data } = await apiClient.post<AgentPhoneNumberResponse>(`/agents/${id}/phone-numbers`, {
      phone_number: body.phoneNumber,
      provider: body.provider,
    })
    return data
  },

  /** DELETE /agents/:id/phone-numbers/:phoneNumberId */
  unassignPhoneNumber: async (id: string, phoneNumberId: string): Promise<void> => {
    await apiClient.delete(`/agents/${id}/phone-numbers/${phoneNumberId}`)
  },
}
