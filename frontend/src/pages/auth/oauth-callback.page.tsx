/**
 * OAuthCallbackPage — landing page for /oauth/callback
 *
 * The backend redirects here after a successful OAuth2 login:
 *   FRONTEND_URL/oauth/callback?accessToken=…&refreshToken=…&tokenType=…&expiresIn=…
 *
 * This page parses those query params, stores the tokens in Zustand,
 * then immediately redirects to the dashboard.
 * If parameters are missing it redirects back to login with an error toast.
 */
import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useAuthStore } from '@/features/auth/store'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/shared/api/query-keys'

export function OAuthCallbackPage() {
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()
  const qc = useQueryClient()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('accessToken')
    const refreshToken = params.get('refreshToken')
    const tokenType = params.get('tokenType') ?? 'bearer'
    const expiresIn = parseInt(params.get('expiresIn') ?? '1800', 10)

    if (!accessToken || !refreshToken) {
      toast.error('OAuth sign-in failed. Please try again.')
      void navigate({ to: '/auth/login' })
      return
    }

    setAuth({ accessToken, refreshToken, tokenType, expiresIn })
    void qc.invalidateQueries({ queryKey: queryKeys.auth.me() })
    void navigate({ to: '/dashboard' })
    // intentionally run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col items-center gap-3">
      <Loader2 className="size-8 animate-spin text-primary" />
      <p className="text-sm text-muted-foreground">Completing sign in…</p>
    </div>
  )
}
