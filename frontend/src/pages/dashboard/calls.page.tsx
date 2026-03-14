import { Activity, Bot, PhoneCall, Radio } from 'lucide-react'
import { useOverview } from '@/features/dashboard/hooks'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-3 w-3">
      {active ? (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
      ) : null}
      <span
        className={`relative inline-flex h-3 w-3 rounded-full ${
          active ? 'bg-emerald-500' : 'bg-muted-foreground/30'
        }`}
      />
    </span>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function CallsDashboardPage() {
  const { data, isLoading } = useOverview()

  const activeCalls = data?.activeCalls ?? 0
  const agentsLive = data?.agentsLive ?? 0
  const callsToday = data?.callsToday ?? 0

  return (
    <PageContainer>
      <PageHeader
        title="Live Calls"
        description="Current live-call activity from the dashboard overview feed."
      />

      <div className="flex flex-wrap gap-3">
        <Badge variant="default" className="h-7 gap-1.5 px-3">
          <PhoneCall className="h-3.5 w-3.5" />
          {activeCalls} active
        </Badge>
        <Badge variant="secondary" className="h-7 gap-1.5 px-3">
          <Bot className="h-3.5 w-3.5" />
          {agentsLive} agents live
        </Badge>
        <Badge variant="outline" className="h-7 gap-1.5 px-3">
          <Activity className="h-3.5 w-3.5" />
          {callsToday} calls today
        </Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Active call load</CardTitle>
            <CardDescription>
              Live count derived from the dashboard overview endpoint.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-32" />
                <Skeleton className="h-4 w-56" />
              </div>
            ) : (
              <div className="flex min-h-48 flex-col items-center justify-center gap-4 text-center">
                <StatusDot active={activeCalls > 0} />
                <div className="text-5xl font-bold tabular-nums">{activeCalls}</div>
                <p className="text-sm text-muted-foreground">
                  {activeCalls === 1
                    ? 'There is 1 active call right now.'
                    : `There are ${activeCalls} active calls right now.`}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Radio className="h-4 w-4" />
              Stream status
            </CardTitle>
            <CardDescription>
              Detailed row-level live call data is not loaded on this page.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>The previous version depended on `useLiveCallTable`, which was removed.</p>
            <p>
              This page now uses the supported overview endpoint and loads without the
              missing-export error.
            </p>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}
