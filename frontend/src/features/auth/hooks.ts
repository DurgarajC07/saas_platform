import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'
import { authApi } from './api'
import { useAuthStore } from './store'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import type {
  LoginInput,
  RegisterInput,
  ForgotPasswordInput,
  ResetPasswordInput,
  ChangePasswordInput,
  OAuthProvider,
} from './schemas'

// ─── useCurrentUser ───────────────────────────────────────────────────────────
export function useCurrentUser() {
  const token = useAuthStore((s) => s.token)
  return useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: authApi.me,
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
  })
}

// ─── useLogin ────────────────────────────────────────────────────────────────
export function useLogin() {
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (body: LoginInput) => authApi.login(body),
    onSuccess: (data) => {
      if ('userId' in data) {
        // 2FA required — stash the userId and send to 2FA verify page
        sessionStorage.setItem('2fa_user_id', data.userId)
        void navigate({ to: '/auth/2fa-verify' })
        return
      }
      setAuth(data)
      void qc.invalidateQueries({ queryKey: queryKeys.auth.me() })
      void navigate({ to: '/dashboard' })
    },
    // errors shown inline on form via form.setError('root', …)
  })
}

// ─── useRegister ─────────────────────────────────────────────────────────────
export function useRegister() {
  const navigate = useNavigate()

  return useMutation({
    mutationFn: (body: RegisterInput) => authApi.register(body),
    onSuccess: () => {
      toast.success('Account created! Check your email to verify.')
      void navigate({ to: '/auth/login' })
    },
    // errors shown inline on form
  })
}

// ─── useLogout ───────────────────────────────────────────────────────────────
export function useLogout() {
  const { logout, refreshToken } = useAuthStore()
  const navigate = useNavigate()
  const qc = useQueryClient()

  return useMutation({
    mutationFn: () => authApi.logout(refreshToken),
    onSettled: () => {
      logout()
      qc.clear()
      void navigate({ to: '/auth/login' })
    },
  })
}

// ─── useForgotPassword ───────────────────────────────────────────────────────
export function useForgotPassword() {
  return useMutation({
    mutationFn: (body: ForgotPasswordInput) => authApi.forgotPassword(body),
    onSuccess: () => toast.success('Reset link sent! Check your inbox.'),
    // errors shown inline on form
  })
}

// ─── useVerifyEmail ───────────────────────────────────────────────────────────
export function useVerifyEmail(token: string) {
  return useQuery({
    queryKey: ['auth', 'verify-email', token],
    queryFn: () => authApi.verifyEmail(token),
    enabled: Boolean(token),
    retry: false,
  })
}

// ─── useResetPassword ────────────────────────────────────────────────────────
export function useResetPassword() {
  const navigate = useNavigate()

  return useMutation({
    mutationFn: (body: ResetPasswordInput) => authApi.resetPassword(body),
    onSuccess: () => {
      toast.success('Password reset! You can log in now.')
      void navigate({ to: '/auth/login' })
    },
    // errors shown inline on form
  })
}

// ─── useChangePassword ───────────────────────────────────────────────────────
export function useChangePassword() {
  return useMutation({
    mutationFn: (body: ChangePasswordInput) => authApi.changePassword(body),
    onSuccess: () => toast.success('Password changed successfully.'),
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}

// ─── use2FASetup ─────────────────────────────────────────────────────────────
export function use2FASetup() {
  return useMutation({
    mutationFn: authApi.setup2FA,
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}

// ─── use2FAConfirm ───────────────────────────────────────────────────────────
export function use2FAConfirm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => authApi.confirm2FA(code),
    onSuccess: () => {
      toast.success('Two-factor authentication enabled.')
      void qc.invalidateQueries({ queryKey: queryKeys.auth.me() })
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}

// ─── use2FAVerify (login-time 2FA step) ─────────────────────────────────────
export function use2FAVerify() {
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ userId, code }: { userId: string; code: string }) =>
      authApi.verify2FA(userId, code),
    onSuccess: (data) => {
      setAuth(data)
      void qc.invalidateQueries({ queryKey: queryKeys.auth.me() })
      sessionStorage.removeItem('2fa_user_id')
      void navigate({ to: '/dashboard' })
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}

// ─── useOAuthLogin ───────────────────────────────────────────────────────────
/**
 * Returns `startOAuth(provider)` which fetches the authorization URL from the
 * backend and redirects the browser to the provider consent screen.
 * After consent the backend redirects to /oauth/callback with the tokens.
 */
export function useOAuthLogin() {
  const [loading, setLoading] = useState<OAuthProvider | null>(null)

  const startOAuth = async (provider: OAuthProvider) => {
    setLoading(provider)
    try {
      const data = await authApi.getOAuthUrl(provider)
      window.location.href = data.authorizationUrl
    } catch (err) {
      setLoading(null)
      toast.error(getErrorMessage(err))
    }
  }

  return { startOAuth, loading }
}

// ─── useSessions ─────────────────────────────────────────────────────────────
export function useSessions() {
  return useQuery({
    queryKey: ['auth', 'sessions'],
    queryFn: authApi.getSessions,
  })
}

// ─── useRevokeSession ────────────────────────────────────────────────────────
export function useRevokeSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['auth', 'sessions'] })
      toast.success('Session revoked.')
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}
