import { formatDistanceToNow } from 'date-fns'
import { Monitor, Smartphone, Globe, Loader2, LogOut } from 'lucide-react'
import { useSessions, useRevokeSession } from '@/features/auth/hooks'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'

function deviceIcon(deviceType: string | null) {
  if (deviceType === 'mobile') return <Smartphone className="size-4 shrink-0" />
  if (deviceType === 'desktop') return <Monitor className="size-4 shrink-0" />
  return <Globe className="size-4 shrink-0" />
}

export function SessionsPage() {
  const { data, isLoading } = useSessions()
  const revokeSession = useRevokeSession()

  const sessions = data?.sessions ?? []

  return (
    <PageContainer>
      <PageHeader
        title="Active Sessions"
        description="Manage your active login sessions across devices."
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="size-4 animate-spin" /> Loading sessions…
        </div>
      ) : (
        <div className="space-y-3 max-w-2xl">
          {sessions.map((session) => (
            <Card key={session.id}>
              <CardHeader className="flex-row items-start gap-3 pb-2">
                <div className="pt-0.5 text-muted-foreground">{deviceIcon(session.deviceType)}</div>
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-sm">
                      {session.deviceType
                        ? `${session.deviceType.charAt(0).toUpperCase()}${session.deviceType.slice(1)}`
                        : 'Unknown device'}
                    </CardTitle>
                    {session.isCurrent && (
                      <Badge variant="default" className="text-xs">
                        Current
                      </Badge>
                    )}
                  </div>
                  <CardDescription className="text-xs">
                    {session.ipAddress ?? 'Unknown IP'} · Last active{' '}
                    {formatDistanceToNow(new Date(session.lastActiveAt), { addSuffix: true })}
                  </CardDescription>
                  {session.userAgent && (
                    <p className="text-xs text-muted-foreground truncate max-w-sm">
                      {session.userAgent}
                    </p>
                  )}
                </div>
                {!session.isCurrent && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive shrink-0"
                    disabled={revokeSession.isPending}
                    onClick={() => {
                      revokeSession.mutate(session.id)
                    }}
                  >
                    <LogOut className="mr-1 size-4" />
                    Revoke
                  </Button>
                )}
              </CardHeader>
            </Card>
          ))}

          {sessions.length === 0 && (
            <p className="text-sm text-muted-foreground py-8">No active sessions found.</p>
          )}
        </div>
      )}
    </PageContainer>
  )
}
