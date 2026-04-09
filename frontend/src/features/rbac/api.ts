import { apiClient } from '@/shared/api/client'
import type {
  CreateRoleInput,
  UpdateRoleInput,
  RoleResponse,
  RoleListResponse,
  PermissionGroupedResponse,
  RolePermissionsResponse,
  MemberRolesResponse,
} from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// RBAC API calls — all under /api/v1/rbac (prefix set in backend router)
// ─────────────────────────────────────────────────────────────────────────────

export const rbacApi = {
  // ── Roles ──────────────────────────────────────────────────────────────────

  /** GET /rbac/roles */
  listRoles: async (): Promise<RoleListResponse> => {
    const { data } = await apiClient.get<RoleListResponse>('/rbac/roles')
    return data
  },

  /** POST /rbac/roles */
  createRole: async (body: CreateRoleInput): Promise<RoleResponse> => {
    const { data } = await apiClient.post<RoleResponse>('/rbac/roles', body)
    return data
  },

  /** PATCH /rbac/roles/:roleId */
  updateRole: async (roleId: string, body: UpdateRoleInput): Promise<RoleResponse> => {
    const { data } = await apiClient.patch<RoleResponse>(`/rbac/roles/${roleId}`, body)
    return data
  },

  /** DELETE /rbac/roles/:roleId */
  deleteRole: async (roleId: string): Promise<void> => {
    await apiClient.delete(`/rbac/roles/${roleId}`)
  },

  // ── Role Permissions ───────────────────────────────────────────────────────

  /** GET /rbac/roles/:roleId/permissions */
  getRolePermissions: async (roleId: string): Promise<RolePermissionsResponse> => {
    const { data } = await apiClient.get<RolePermissionsResponse>(
      `/rbac/roles/${roleId}/permissions`,
    )
    return data
  },

  /** PUT /rbac/roles/:roleId/permissions — bulk replace */
  setRolePermissions: async (
    roleId: string,
    permissionIds: string[],
  ): Promise<RolePermissionsResponse> => {
    const { data } = await apiClient.put<RolePermissionsResponse>(
      `/rbac/roles/${roleId}/permissions`,
      { permissionIds },
    )
    return data
  },

  // ── Permissions catalogue ──────────────────────────────────────────────────

  /** GET /rbac/permissions */
  listPermissions: async (): Promise<PermissionGroupedResponse> => {
    const { data } = await apiClient.get<PermissionGroupedResponse>('/rbac/permissions')
    return data
  },

  // ── Member role assignments ────────────────────────────────────────────────

  /** GET /rbac/members/:memberId/roles */
  getMemberRoles: async (memberId: string): Promise<MemberRolesResponse> => {
    const { data } = await apiClient.get<MemberRolesResponse>(`/rbac/members/${memberId}/roles`)
    return data
  },

  /** PUT /rbac/members/:memberId/roles/:roleId */
  assignMemberRole: async (memberId: string, roleId: string): Promise<MemberRolesResponse> => {
    const { data } = await apiClient.put<MemberRolesResponse>(
      `/rbac/members/${memberId}/roles/${roleId}`,
    )
    return data
  },

  /** DELETE /rbac/members/:memberId/roles/:roleId */
  revokeMemberRole: async (memberId: string, roleId: string): Promise<void> => {
    await apiClient.delete(`/rbac/members/${memberId}/roles/${roleId}`)
  },
}
