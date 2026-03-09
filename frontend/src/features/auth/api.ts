import { apiClient } from '@/shared/api/client'
import {
  type LoginInput,
  type RegisterInput,
  type ForgotPasswordInput,
  type ResetPasswordInput,
  type ChangePasswordInput,
  type TokenResponse,
  type TwoFactorChallengeResponse,
  type UserResponse,
  type SessionResponse,
  type OAuthProvider,
  type OAuthRedirectResponse,
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
  /** POST /auth/login — returns tokens on success, or 2FA challenge */
  login: async (body: LoginInput): Promise<TokenResponse | TwoFactorChallengeResponse> => {
    const { data } = await apiClient.post<TokenResponse | TwoFactorChallengeResponse>(
      '/auth/login',
      body,
    )
    return data
  },

  /** POST /auth/register — returns UserResponse (201) */
  register: async (body: RegisterInput): Promise<UserResponse> => {
    const { data } = await apiClient.post<UserResponse>('/auth/register', body)
    return data
  },

  /** POST /auth/refresh */
  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/refresh', { refreshToken })
    return data
  },

  /** POST /auth/logout — optionally revoke refresh token too */
  logout: async (refreshToken?: string | null): Promise<void> => {
    await apiClient.post('/auth/logout', { refreshToken: refreshToken ?? null })
  },

  /** GET /auth/me */
  me: async (): Promise<UserResponse> => {
    const { data } = await apiClient.get<UserResponse>('/auth/me')
    return data
  },

  /** GET /auth/verify-email?token=TOKEN */
  verifyEmail: async (token: string): Promise<MessageResponse> => {
    const { data } = await apiClient.get<MessageResponse>('/auth/verify-email', {
      params: { token },
    })
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

  verify2FA: async (userId: string, code: string): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/2fa/verify', { userId, code })
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

  // ── OAuth ────────────────────────────────────────────────────────────────
  /** GET /auth/oauth/{provider} — fetch the provider authorization URL */
  getOAuthUrl: async (provider: OAuthProvider): Promise<OAuthRedirectResponse> => {
    const { data } = await apiClient.get<OAuthRedirectResponse>(`/auth/oauth/${provider}`)
    return data
  },
}
