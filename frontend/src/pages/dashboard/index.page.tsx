import { useMemo } from 'react'
import { PhoneCall, Phone, Bot, Gauge, Clock, ArrowRight } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { formatDistanceToNow } from 'date-fns'
import { useOverview, useLiveCallsSnapshot } from '@/features/dashboard/hooks'
import { CallVolumeChart } from '@/features/dashboard/components/CallVolumeChart'
import { AgentPerfTable } from '@/features/dashboard/components/AgentPerfTable'
import { StatCard } from '@/shared/components/data-display/StatCard'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import type { DashboardOverview } from '@/features/dashboard/schemas'

// ── Helper: derive delta shape from nullable number ───────────────────────────
function toDelta(
  v: number | null,
  positiveIsUp = true,
): { value: number; direction: 'up' | 'down'; label: string } | undefined {
  if (v === null) return undefined
  const abs = Math.abs(v)
  const direction = v >= 0 === positiveIsUp ? 'up' : 'down'
  return { value: abs, direction, label: 'vs yesterday' }
}

// ── Stat card data derived from overview ──────────────────────────────────────
function useStatCards(data: DashboardOverview | undefined, isLoading: boolean) {
  return useMemo(
    () => [
      {
        title: 'Active Calls',
        value: data?.activeCalls ?? '—',
        icon: PhoneCall,
        loading: isLoading,
        delta: toDelta(data?.deltaActiveCalls ?? null),
      },
      {
        title: 'Calls Today',
        value: data?.callsToday ?? '—',
        icon: Phone,
        loading: isLoading,
        delta: toDelta(data?.deltaCallsToday ?? null),
      },
      {
        title: 'Agents Live',
        value: data?.agentsLive ?? '—',
        icon: Bot,
        loading: isLoading,
        delta: toDelta(data?.deltaAgentsLive ?? null),
      },
      {
        title: 'Avg Latency',
        value: data ? `${data.avgLatencyMs}ms` : '—',
        icon: Gauge,
        loading: isLoading,
        // latency going up is bad → positiveIsUp = false
        delta: toDelta(data?.deltaAvgLatency ?? null, false),
      },
    ],
    [data, isLoading],
  )
}

// ── Live call mini-list ───────────────────────────────────────────────────────
function LiveCallList() {
  const { data, isLoading } = useLiveCallsSnapshot()
  const calls = data?.calls ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-base">Live Calls</CardTitle>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/dashboard/calls">
            View all <ArrowRight className="ml-1 h-4 w-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))
        ) : calls.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No active calls right now.
          </p>
        ) : (
          calls.slice(0, 6).map((call) => (
            <div
              key={call.id}
              className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-3">
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
                <div>
                  <p className="font-medium">{call.callerNumber}</p>
                  <p className="text-xs text-muted-foreground">{call.agentName}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span className="text-xs">
                  {formatDistanceToNow(new Date(call.startedAt), { addSuffix: false })}
                </span>
                <Badge variant="secondary" className="text-xs capitalize">
                  {call.status.replace('_', ' ')}
                </Badge>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function DashboardPage() {
  const { data, isLoading } = useOverview()
  const statCards = useStatCards(data, isLoading)

  return (
    <PageContainer>
      <PageHeader
        title="Dashboard"
        description="Overview of your AI voice platform."
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link to="/dashboard/analytics">Analytics</Link>
          </Button>
        }
      />

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <StatCard key={card.title} {...card} />
        ))}
      </div>

      {/* Call volume chart + live call list */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <CallVolumeChart period="7d" />
        </div>
        <LiveCallList />
      </div>

      {/* Agent performance table */}
      <AgentPerfTable />
    </PageContainer>
  )
}
