import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import { agentsApi } from './api'
import type { CreateAgentInput } from './schemas'

interface AgentListFilters {
  page?: number
  pageSize?: number
  status?: string
  type?: string
  search?: string
}

// ─── useAgents ────────────────────────────────────────────────────────────────
export function useAgents(filters: AgentListFilters = {}) {
  return useQuery({
    queryKey: queryKeys.agents.list({
      page: filters.page,
      pageSize: filters.pageSize,
      search: filters.search,
    }),
    queryFn: () => agentsApi.listAgents(filters),
    staleTime: 30_000,
    placeholderData: (prev) => prev, // keep last page while loading next
  })
}

// ─── useAgent ─────────────────────────────────────────────────────────────────
export function useAgent(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.agents.detail(id ?? ''),
    queryFn: () => agentsApi.getAgent(id ?? ''),
    enabled: Boolean(id),
    staleTime: 60_000,
  })
}

// ─── useCreateAgent ───────────────────────────────────────────────────────────
export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateAgentInput) => agentsApi.createAgent(body),
    onSuccess: (agent) => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success(`Agent "${agent.name}" created!`)
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useUpdateAgent ───────────────────────────────────────────────────────────
export function useUpdateAgent(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<CreateAgentInput>) => agentsApi.updateAgent(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.detail(id) })
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success('Agent updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useDeleteAgent ───────────────────────────────────────────────────────────
export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => agentsApi.deleteAgent(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success('Agent deleted.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useSetAgentStatus ────────────────────────────────────────────────────────
export function useSetAgentStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => agentsApi.setStatus(id, status),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success('Agent status updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useBulkUpdateAgents ─────────────────────────────────────────────────────
export function useBulkUpdateAgents() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ids, status }: { ids: string[]; status: string }) =>
      agentsApi.bulkUpdate(ids, { status }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success(`${res.updated} agents updated.`)
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useBulkDeleteAgents ─────────────────────────────────────────────────────
export function useBulkDeleteAgents() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ids: string[]) => agentsApi.bulkDelete(ids),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: queryKeys.agents.all() })
      toast.success(`${res.deleted} agents deleted.`)
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}
