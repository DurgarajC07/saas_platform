import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { UserResponse, TokenResponse } from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// State shape
// ─────────────────────────────────────────────────────────────────────────────
interface AuthState {
  token: string | null
  refreshToken: string | null
  orgId: string | null
  user: UserResponse | null
  isAuthenticated: boolean

  // Actions
  setAuth: (data: TokenResponse) => void
  setTokens: (token: string, refreshToken: string) => void
  setOrg: (orgId: string) => void
  setUser: (user: UserResponse) => void
  logout: () => void
}

// ─────────────────────────────────────────────────────────────────────────────
// Zustand store  (persisted to localStorage)
// ─────────────────────────────────────────────────────────────────────────────
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      orgId: null,
      user: null,
      isAuthenticated: false,

      setAuth: (data) =>
        set({
          token: data.accessToken,
          refreshToken: data.refreshToken,
          // Persist org_id from login response so subsequent requests include it
          ...(data.orgId != null ? { orgId: data.orgId } : {}),
          isAuthenticated: true,
        }),

      setTokens: (token, refreshToken) => set({ token, refreshToken }),

      setOrg: (orgId) => set({ orgId }),

      setUser: (user) => set({ user }),

      logout: () =>
        set({ token: null, refreshToken: null, orgId: null, user: null, isAuthenticated: false }),
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        token: s.token,
        refreshToken: s.refreshToken,
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
