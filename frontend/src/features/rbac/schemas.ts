import { z } from 'zod'

// ─── Request schemas ──────────────────────────────────────────────────────────

export const createRoleSchema = z.object({
  name: z.string().min(2, 'Name must be at least 2 characters').max(100),
  displayName: z.string().max(150).optional().or(z.literal('')),
  description: z.string().max(500).optional().or(z.literal('')),
  priority: z.number().int().min(0).max(100).default(0),
})

export const updateRoleSchema = z.object({
  name: z.string().min(2).max(100).optional(),
  displayName: z.string().max(150).optional().or(z.literal('')),
  description: z.string().max(500).optional().or(z.literal('')),
  priority: z.number().int().min(0).max(100).optional(),
})

// ─── Response interfaces ──────────────────────────────────────────────────────

export interface RoleResponse {
  id: string
  name: string
  displayName: string | null
  description: string | null
  organizationId: string | null
  isSystemRole: boolean
  isDefault: boolean
  priority: number
  createdAt: string
  updatedAt: string
}

export interface RoleListResponse {
  roles: RoleResponse[]
  total: number
}

export interface PermissionResponse {
  id: string
  name: string
  displayName: string | null
  description: string | null
  module: string
  resource: string
  action: string
  createdAt: string
  updatedAt: string
}

export interface PermissionGroup {
  module: string
  permissions: PermissionResponse[]
}

export interface PermissionGroupedResponse {
  groups: PermissionGroup[]
  total: number
}

export interface RolePermissionsResponse {
  roleId: string
  permissions: PermissionResponse[]
}

export interface MemberRoleResponse {
  organizationUserId: string
  role: RoleResponse
  assignedAt: string
  assignedBy: string | null
}

export interface MemberRolesResponse {
  organizationUserId: string
  roles: MemberRoleResponse[]
}

// ─── Inferred types ───────────────────────────────────────────────────────────
export type CreateRoleInput = z.infer<typeof createRoleSchema>
export type UpdateRoleInput = z.infer<typeof updateRoleSchema>
