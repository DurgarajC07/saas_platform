import { apiClient } from '@/shared/api/client'
import type { KbUploadResponse, KbDocumentListResponse, KbDeleteDocResponse } from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// Knowledge Base API  —  all endpoints under /agents/:agentId/knowledge-base
// ─────────────────────────────────────────────────────────────────────────────

export const knowledgeBaseApi = {
  /** POST /agents/:agentId/knowledge-base — multipart upload */
  uploadDocument: async (
    agentId: string,
    file: File,
    sourceUrl?: string,
  ): Promise<KbUploadResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await apiClient.post<KbUploadResponse>(
      `/agents/${agentId}/knowledge-base`,
      formData,
      {
        params: sourceUrl ? { source_url: sourceUrl } : undefined,
        headers: { 'Content-Type': 'multipart/form-data' },
      },
    )
    return data
  },

  /**
   * POST /agents/:agentId/knowledge-base — URL/YouTube ingestion.
   * Workaround: the backend's multipart endpoint always requires a `file`
   * field even for URL-type ingestion, so we send a tiny placeholder text
   * file alongside the real `source_url` query param.
   */
  ingestUrl: async (agentId: string, url: string): Promise<KbUploadResponse> => {
    const blob = new Blob([url], { type: 'text/plain' })
    const file = new File([blob], 'source.txt', { type: 'text/plain' })
    return knowledgeBaseApi.uploadDocument(agentId, file, url)
  },

  /** GET /agents/:agentId/knowledge-base */
  listDocuments: async (agentId: string, status?: string): Promise<KbDocumentListResponse> => {
    const { data } = await apiClient.get<KbDocumentListResponse>(
      `/agents/${agentId}/knowledge-base`,
      {
        params: status ? { status } : undefined,
      },
    )
    return data
  },

  /** DELETE /agents/:agentId/knowledge-base/:docId */
  deleteDocument: async (agentId: string, docId: string): Promise<KbDeleteDocResponse> => {
    const { data } = await apiClient.delete<KbDeleteDocResponse>(
      `/agents/${agentId}/knowledge-base/${docId}`,
    )
    return data
  },

  /** DELETE /agents/:agentId/knowledge-base — clears the whole knowledge base */
  clearAll: async (agentId: string): Promise<void> => {
    await apiClient.delete(`/agents/${agentId}/knowledge-base`)
  },
}
