import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { type UserResponse } from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// State shape
// ─────────────────────────────────────────────────────────────────────────────
interface AuthState {
  token:        string | null
  refreshToken: string | null
  orgId:        string | null
  user:         UserResponse | null

  // Actions
  setAuth:      (token: string, refreshToken: string, user: UserResponse) => void
  setTokens:    (token: string, refreshToken: string) => void
  setOrgId:     (orgId: string) => void
  setUser:      (user: UserResponse) => void
  logout:       () => void
}

// ─────────────────────────────────────────────────────────────────────────────
// Zustand store  (persisted to localStorage)
// ─────────────────────────────────────────────────────────────────────────────
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token:        null,
      refreshToken: null,
      orgId:        null,
      user:         null,

      setAuth: (token, refreshToken, user) =>
        set({ token, refreshToken, user }),

      setTokens: (token, refreshToken) =>
        set({ token, refreshToken }),

      setOrgId: (orgId) => set({ orgId }),

      setUser: (user) => set({ user }),

      logout: () =>
        set({ token: null, refreshToken: null, orgId: null, user: null }),
    }),
    {
      name:    'auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        token:        s.token,
        refreshToken: s.refreshToken,
        orgId:        s.orgId,
        user:         s.user,
      }),
    },
  ),
)

// ── Convenience selectors ─────────────────────────────────────────────────────
export const selectIsAuthenticated = (s: AuthState) => Boolean(s.token)
export const selectUser            = (s: AuthState) => s.user
export const selectIsSuperuser     = (s: AuthState) => s.user?.isSuperuser ?? false
