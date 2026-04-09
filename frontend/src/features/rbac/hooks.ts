import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { rbacApi } from './api'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import type { CreateRoleInput, UpdateRoleInput } from './schemas'

// ─── useRoles ─────────────────────────────────────────────────────────────────
export function useRoles() {
  return useQuery({
    queryKey: queryKeys.rbac.roles(),
    queryFn: rbacApi.listRoles,
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useRole ──────────────────────────────────────────────────────────────────
export function useRole(roleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.rbac.role(roleId ?? ''),
    queryFn: () =>
      rbacApi.listRoles().then((r) => r.roles.find((role) => role.id === roleId) ?? null),
    enabled: Boolean(roleId),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useCreateRole ────────────────────────────────────────────────────────────
export function useCreateRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateRoleInput) => rbacApi.createRole(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.roles() })
      toast.success('Role created.')
    },
  })
}

// ─── useUpdateRole ────────────────────────────────────────────────────────────
export function useUpdateRole(roleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateRoleInput) => rbacApi.updateRole(roleId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.roles() })
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.role(roleId) })
      toast.success('Role updated.')
    },
  })
}

// ─── useDeleteRole ────────────────────────────────────────────────────────────
export function useDeleteRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => rbacApi.deleteRole(roleId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.roles() })
      toast.success('Role deleted.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── usePermissions ───────────────────────────────────────────────────────────
export function usePermissions() {
  return useQuery({
    queryKey: queryKeys.rbac.permissions(),
    queryFn: rbacApi.listPermissions,
    staleTime: 10 * 60 * 1000, // permissions rarely change
  })
}

// ─── useRolePermissions ───────────────────────────────────────────────────────
export function useRolePermissions(roleId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.rbac.rolePerms(roleId ?? ''),
    queryFn: () => rbacApi.getRolePermissions(roleId ?? ''),
    enabled: Boolean(roleId),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useSetRolePermissions ────────────────────────────────────────────────────
export function useSetRolePermissions(roleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (permissionIds: string[]) => rbacApi.setRolePermissions(roleId, permissionIds),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.rolePerms(roleId) })
      toast.success('Permissions updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useMemberRoles ───────────────────────────────────────────────────────────
export function useMemberRoles(memberId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.rbac.memberRoles(memberId ?? ''),
    queryFn: () => rbacApi.getMemberRoles(memberId ?? ''),
    enabled: Boolean(memberId),
    staleTime: 2 * 60 * 1000,
  })
}

// ─── useAssignMemberRole ─────────────────────────────────────────────────────
export function useAssignMemberRole(memberId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => rbacApi.assignMemberRole(memberId, roleId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.memberRoles(memberId) })
      toast.success('Role assigned.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useRevokeMemberRole ──────────────────────────────────────────────────────
export function useRevokeMemberRole(memberId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => rbacApi.revokeMemberRole(memberId, roleId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.rbac.memberRoles(memberId) })
      toast.success('Role revoked.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}
