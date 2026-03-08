import { apiClient } from '@/shared/api/client'
import {
  type LoginInput,
  type RegisterInput,
  type ForgotPasswordInput,
  type ResetPasswordInput,
  type ChangePasswordInput,
  type AuthResponse,
  type UserResponse,
  type SessionResponse,
} from './schemas'

// ─────────────────────────────────────────────────────────────────────────────
// Auth API calls
// ─────────────────────────────────────────────────────────────────────────────

export const authApi = {
  /** POST /auth/login */
  login: async (body: LoginInput): Promise<AuthResponse> => {
    const { data } = await apiClient.post<AuthResponse>('/auth/login', body)
    return data
  },

  /** POST /auth/register */
  register: async (body: RegisterInput) => {
    const { data } = await apiClient.post('/auth/register', body)
    return data
  },

  /** POST /auth/refresh */
  refresh: async (refreshToken: string): Promise<AuthResponse> => {
    const { data } = await apiClient.post<AuthResponse>('/auth/refresh', { refreshToken })
    return data
  },

  /** POST /auth/logout */
  logout: async () => {
    await apiClient.post('/auth/logout')
  },

  /** GET /auth/me */
  me: async (): Promise<UserResponse> => {
    const { data } = await apiClient.get<UserResponse>('/auth/me')
    return data
  },

  /** POST /auth/forgot-password */
  forgotPassword: async (body: ForgotPasswordInput) => {
    const { data } = await apiClient.post('/auth/forgot-password', body)
    return data
  },

  /** POST /auth/reset-password */
  resetPassword: async (body: ResetPasswordInput) => {
    const { data } = await apiClient.post('/auth/reset-password', body)
    return data
  },

  /** POST /auth/password/change */
  changePassword: async (body: ChangePasswordInput) => {
    const { data } = await apiClient.post('/auth/password/change', body)
    return data
  },

  // ── 2FA ──────────────────────────────────────────────────────────────────
  setup2FA: async () => {
    const { data } = await apiClient.post('/auth/2fa/setup')
    return data as { secret: string; qrCodeUri: string; backupCodes: string[] }
  },

  confirm2FA: async (code: string) => {
    const { data } = await apiClient.post('/auth/2fa/confirm', { code })
    return data
  },

  verify2FA: async (mfaToken: string, code: string): Promise<AuthResponse> => {
    const { data } = await apiClient.post<AuthResponse>('/auth/2fa/verify', { mfaToken, code })
    return data
  },

  disable2FA: async () => {
    const { data } = await apiClient.delete('/auth/2fa/disable')
    return data
  },

  // ── Sessions ─────────────────────────────────────────────────────────────
  getSessions: async (): Promise<{ sessions: SessionResponse[] }> => {
    const { data } = await apiClient.get('/auth/sessions')
    return data
  },

  revokeSession: async (sessionId: string) => {
    await apiClient.delete(`/auth/sessions/${sessionId}`)
  },

  revokeAllSessions: async () => {
    await apiClient.delete('/auth/sessions')
  },
}
