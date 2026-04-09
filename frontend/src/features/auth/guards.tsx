import type { ReactNode } from 'react'
import { Navigate, redirect } from '@tanstack/react-router'
import { useAuthStore } from './store'

// ─── Component guards (for JSX trees) ────────────────────────────────────────

interface GuardProps {
  children: ReactNode
}

/** Renders children only when authenticated; otherwise redirects to /auth/login */
export function AuthGuard({ children }: GuardProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) {
    return <Navigate to="/auth/login" />
  }
  return <>{children}</>
}

/** Renders children only when NOT authenticated; otherwise redirects to /dashboard */
export function GuestGuard({ children }: GuardProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (isAuthenticated) {
    return <Navigate to="/" />
  }
  return <>{children}</>
}

// ─── beforeLoad helpers (throw-based, for TanStack Router) ───────────────────

/** Use as `beforeLoad: requireAuth` on protected routes */
export function requireAuth() {
  const isAuthenticated = useAuthStore.getState().isAuthenticated
  if (!isAuthenticated) {
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw redirect({ to: '/auth/login' })
  }
}

/** Use as `beforeLoad: requireGuest` on auth routes to bounce logged-in users */
export function requireGuest() {
  const isAuthenticated = useAuthStore.getState().isAuthenticated
  if (isAuthenticated) {
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw redirect({ to: '/' })
  }
}
