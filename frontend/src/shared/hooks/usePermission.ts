import { useAuthStore } from '@/features/auth/store'

/**
 * Returns true when the current user has ALL of the given permissions
 * within their active organization membership.
 */
export function usePermission(...permissions: string[]): boolean {
  const user = useAuthStore((s) => s.user)

  if (!user) return false

  // Superusers bypass all permission checks
  if ((user as any).is_superuser) return true

  // Permissions come from the user object once org-member route returns them.
  // Fall back to false when not yet loaded.
  const granted: string[] = (user as any).permissions ?? []
  return permissions.every((p) => granted.includes(p))
}
