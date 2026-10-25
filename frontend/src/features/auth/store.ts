import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { UserResponse, TokenResponse } from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// State shape
//
// The refresh token is deliberately NOT part of this store (and therefore
// never persisted to localStorage): the backend now also sets it as an
// httpOnly cookie on /login, /refresh, /2fa/verify, /2fa/backup, and the
// OAuth callback (see app/modules/auth/router.py::_set_refresh_cookie). A
// long-lived credential sitting in JS-readable storage is a real landmine
// the day any HTML/markdown renderer is added (transcripts, KB content) —
// the httpOnly cookie is immune to that class of theft by construction.
// The short-lived (15 min) access token is still kept here; its much
// smaller exposure window is an accepted, much lower risk by comparison.
// Non-browser API clients that call /login directly still receive
// refreshToken in the JSON body (backend contract unchanged) — this store
// just doesn't hold onto it.
// ─────────────────────────────────────────────────────────────────────────────
interface AuthState {
  token: string | null
  orgId: string | null
  user: UserResponse | null
  isAuthenticated: boolean

  // Actions
  setAuth: (data: Pick<TokenResponse, 'accessToken' | 'orgId'>) => void
  setToken: (token: string) => void
  setOrg: (orgId: string) => void
  setUser: (user: UserResponse) => void
  logout: () => void
}

// ─────────────────────────────────────────────────────────────────────────────
// Zustand store  (persisted to localStorage — access token + profile only)
// ─────────────────────────────────────────────────────────────────────────────
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      orgId: null,
      user: null,
      isAuthenticated: false,

      setAuth: (data) =>
        set({
          token: data.accessToken,
          // Persist org_id from login response so subsequent requests include it
          ...(data.orgId != null ? { orgId: data.orgId } : {}),
          isAuthenticated: true,
        }),

      setToken: (token) => set({ token }),

      setOrg: (orgId) => set({ orgId }),

      setUser: (user) => set({ user }),

      logout: () => set({ token: null, orgId: null, user: null, isAuthenticated: false }),
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        token: s.token,
        orgId: s.orgId,
        user: s.user,
        isAuthenticated: s.isAuthenticated,
      }),
    },
  ),
)

// ── Convenience selectors ─────────────────────────────────────────────────────
export const selectIsAuthenticated = (s: AuthState) => s.isAuthenticated
export const selectUser = (s: AuthState) => s.user
export const selectOrgId = (s: AuthState) => s.orgId
export const selectIsPlatformAdmin = (s: AuthState) => s.user?.isPlatformAdmin ?? false
