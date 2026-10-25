/**
 * OAuthCallbackPage — landing page for /oauth/callback
 *
 * The backend redirects here after a successful OAuth2 login:
 *   FRONTEND_URL/oauth/callback?accessToken=…&tokenType=…&expiresIn=…
 *
 * The refresh token is NOT in this URL — a query string ends up in browser
 * history and server/proxy access logs, which is worse than localStorage
 * ever was. It arrives as the same httpOnly refresh_token cookie /login
 * uses instead (set directly on this redirect response by the backend).
 *
 * This page parses the access-token query params, stores it in Zustand,
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

    if (!accessToken) {
      toast.error('OAuth sign-in failed. Please try again.')
      void navigate({ to: '/auth/login' })
      return
    }

    setAuth({ accessToken })
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
