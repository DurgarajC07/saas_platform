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

interface MessageResponse {
  message: string
}
interface Setup2FAResponse {
  secret: string
  qrCodeUri: string
  backupCodes: string[]
}

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
  register: async (body: RegisterInput): Promise<MessageResponse> => {
    const { data } = await apiClient.post<MessageResponse>('/auth/register', body)
    return data
  },

  /** POST /auth/refresh */
  refresh: async (refreshToken: string): Promise<AuthResponse> => {
    const { data } = await apiClient.post<AuthResponse>('/auth/refresh', { refreshToken })
    return data
  },

  /** POST /auth/logout */
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout')
  },

  /** GET /auth/me */
  me: async (): Promise<UserResponse> => {
    const { data } = await apiClient.get<UserResponse>('/auth/me')
    return data
  },

  /** POST /auth/forgot-password */
  forgotPassword: async (body: ForgotPasswordInput): Promise<MessageResponse> => {
    const { data } = await apiClient.post<MessageResponse>('/auth/forgot-password', body)
    return data
  },

  /** POST /auth/reset-password */
  resetPassword: async (body: ResetPasswordInput): Promise<MessageResponse> => {
    const { data } = await apiClient.post<MessageResponse>('/auth/reset-password', body)
    return data
  },

  /** POST /auth/password/change */
  changePassword: async (body: ChangePasswordInput): Promise<MessageResponse> => {
    const { data } = await apiClient.post<MessageResponse>('/auth/password/change', body)
    return data
  },

  // ── 2FA ──────────────────────────────────────────────────────────────────
  setup2FA: async (): Promise<Setup2FAResponse> => {
    const { data } = await apiClient.post<Setup2FAResponse>('/auth/2fa/setup')
    return data
  },

  confirm2FA: async (code: string): Promise<MessageResponse> => {
    const { data } = await apiClient.post<MessageResponse>('/auth/2fa/confirm', { code })
    return data
  },

  verify2FA: async (mfaToken: string, code: string): Promise<AuthResponse> => {
    const { data } = await apiClient.post<AuthResponse>('/auth/2fa/verify', { mfaToken, code })
    return data
  },

  disable2FA: async (): Promise<MessageResponse> => {
    const { data } = await apiClient.delete<MessageResponse>('/auth/2fa/disable')
    return data
  },

  // ── Sessions ─────────────────────────────────────────────────────────────
  getSessions: async (): Promise<{ sessions: SessionResponse[] }> => {
    const { data } = await apiClient.get<{ sessions: SessionResponse[] }>('/auth/sessions')
    return data
  },

  revokeSession: async (sessionId: string): Promise<void> => {
    await apiClient.delete(`/auth/sessions/${sessionId}`)
  },

  revokeAllSessions: async (): Promise<void> => {
    await apiClient.delete('/auth/sessions')
  },
}
