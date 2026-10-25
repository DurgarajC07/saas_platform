import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import { knowledgeBaseApi } from './api'

// ─── useKnowledgeBase ─────────────────────────────────────────────────────────
export function useKnowledgeBase(agentId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.agents.kb(agentId ?? ''),
    queryFn: () => knowledgeBaseApi.listDocuments(agentId ?? ''),
    enabled: Boolean(agentId),
    refetchInterval: (query) => {
      const docs = query.state.data?.documents ?? []
      return docs.some((d) => d.status === 'pending' || d.status === 'processing') ? 4000 : false
    },
  })
}

// ─── useUploadKbDocument ──────────────────────────────────────────────────────
export function useUploadKbDocument(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, sourceUrl }: { file: File; sourceUrl?: string }) =>
      knowledgeBaseApi.uploadDocument(agentId, file, sourceUrl),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.kb(agentId) })
      toast.success('Document queued for ingestion.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useIngestUrl ─────────────────────────────────────────────────────────────
export function useIngestUrl(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => knowledgeBaseApi.ingestUrl(agentId, url),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.kb(agentId) })
      toast.success('Document queued for ingestion.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useDeleteKbDocument ──────────────────────────────────────────────────────
export function useDeleteKbDocument(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (docId: string) => knowledgeBaseApi.deleteDocument(agentId, docId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.kb(agentId) })
      toast.success('Document removed.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useClearKnowledgeBase ────────────────────────────────────────────────────
export function useClearKnowledgeBase(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => knowledgeBaseApi.clearAll(agentId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.kb(agentId) })
      toast.success('Knowledge base cleared.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}
