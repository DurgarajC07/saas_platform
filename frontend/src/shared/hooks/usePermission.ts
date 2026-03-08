import { useAuthStore } from '@/features/auth/store'

interface UserWithPermissions {
  is_superuser?: boolean
  permissions?: string[]
}

/**
 * Returns true when the current user has ALL of the given permissions
 * within their active organization membership.
 */
export function usePermission(...permissions: string[]): boolean {
  const user = useAuthStore((s) => s.user) as UserWithPermissions | null

  if (!user) return false

  // Superusers bypass all permission checks
  if (user.is_superuser) return true

  // Permissions come from the user object once org-member route returns them.
  // Fall back to false when not yet loaded.
  const granted: string[] = user.permissions ?? []
  return permissions.every((p) => granted.includes(p))
}
