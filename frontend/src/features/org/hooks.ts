import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { orgApi } from './api'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import { useAuthStore } from '@/features/auth/store'
import type {
  UpdateOrgInput,
  InviteMemberInput,
  UpdateMemberRoleInput,
  AddDomainInput,
} from './schemas'

// ─── useOrg ───────────────────────────────────────────────────────────────────
/**
 * Fetch the current org by slug.
 * The slug is read from the URL slug stored in the org object itself —
 * the API client auto-injects the X-Org-ID header for auth so we need
 * to know the slug to fetch.
 */
export function useOrg(slug: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.tenancy.org(slug ?? ''),
    queryFn: () => orgApi.getOrg(slug ?? ''),
    enabled: Boolean(slug),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useUpdateOrg ─────────────────────────────────────────────────────────────
export function useUpdateOrg(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateOrgInput) => orgApi.updateOrg(orgId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['orgs'] })
      toast.success('Organization settings saved.')
    },
  })
}

// ─── useDeleteOrg ─────────────────────────────────────────────────────────────
export function useDeleteOrg() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (orgId: string) => orgApi.deleteOrg(orgId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['orgs'] })
    },
  })
}

// ─── useOrgMembers ────────────────────────────────────────────────────────────
export function useOrgMembers(orgId: string | null | undefined, page = 1) {
  return useQuery({
    queryKey: queryKeys.tenancy.members(orgId ?? ''),
    queryFn: () => orgApi.listMembers(orgId ?? '', { page, pageSize: 50 }),
    enabled: Boolean(orgId),
    staleTime: 2 * 60 * 1000,
  })
}

// ─── useRemoveMember ─────────────────────────────────────────────────────────
export function useRemoveMember(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (uid: string) => orgApi.removeMember(orgId, uid),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.members(orgId) })
      toast.success('Member removed.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useUpdateMemberRole ──────────────────────────────────────────────────────
export function useUpdateMemberRole(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ uid, body }: { uid: string; body: UpdateMemberRoleInput }) =>
      orgApi.updateMemberRole(orgId, uid, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.members(orgId) })
      toast.success('Role updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useInviteMember ─────────────────────────────────────────────────────────
export function useInviteMember(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InviteMemberInput) => orgApi.inviteMember(orgId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.invitations(orgId) })
      toast.success('Invitation sent.')
    },
  })
}

// ─── useOrgInvitations ────────────────────────────────────────────────────────
export function useOrgInvitations(orgId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.tenancy.invitations(orgId ?? ''),
    queryFn: () => orgApi.listInvitations(orgId ?? ''),
    enabled: Boolean(orgId),
    staleTime: 2 * 60 * 1000,
  })
}

// ─── useRevokeInvitation ──────────────────────────────────────────────────────
export function useRevokeInvitation(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (invitationId: string) => orgApi.revokeInvitation(orgId, invitationId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.invitations(orgId) })
      toast.success('Invitation revoked.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useAcceptInvitation ──────────────────────────────────────────────────────
export function useAcceptInvitation() {
  const setOrg = useAuthStore((s) => s.setOrg)
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => orgApi.acceptInvitation(token),
    onSuccess: (org) => {
      setOrg(org.id)
      void qc.invalidateQueries({ queryKey: ['orgs'] })
      toast.success(`Joined ${org.name}!`)
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useOrgDomains ────────────────────────────────────────────────────────────
export function useOrgDomains(orgId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.tenancy.domains(orgId ?? ''),
    queryFn: () => orgApi.listDomains(orgId ?? ''),
    enabled: Boolean(orgId),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useAddDomain ─────────────────────────────────────────────────────────────
export function useAddDomain(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AddDomainInput) => orgApi.addDomain(orgId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.domains(orgId) })
      toast.success('Domain added. Add the DNS TXT record to verify.')
    },
  })
}

// ─── useDeleteDomain ──────────────────────────────────────────────────────────
export function useDeleteDomain(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (domainId: string) => orgApi.deleteDomain(orgId, domainId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.domains(orgId) })
      toast.success('Domain removed.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useVerifyDomain ──────────────────────────────────────────────────────────
export function useVerifyDomain(orgId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (domainId: string) => orgApi.verifyDomain(orgId, domainId),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: queryKeys.tenancy.domains(orgId) })
      if (d.isVerified) {
        toast.success(`${d.domain} verified!`)
      } else {
        toast.error('DNS TXT record not found yet. Try again shortly.')
      }
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}
