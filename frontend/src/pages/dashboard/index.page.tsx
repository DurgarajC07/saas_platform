import { useMemo } from 'react'
import { PhoneCall, Phone, Bot, Gauge, ArrowRight } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { useOverview } from '@/features/dashboard/hooks'
import { CallVolumeChart } from '@/features/dashboard/components/CallVolumeChart'
import { AgentPerfTable } from '@/features/dashboard/components/AgentPerfTable'
import { StatCard } from '@/shared/components/data-display/StatCard'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
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
  const { data, isLoading } = useOverview()
  const activeCalls = data?.activeCalls ?? 0

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
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 gap-3">
            <span className="relative flex h-4 w-4">
              {activeCalls > 0 && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex h-4 w-4 rounded-full ${
                  activeCalls > 0 ? 'bg-emerald-500' : 'bg-muted-foreground/30'
                }`}
              />
            </span>
            <p className="text-3xl font-bold tabular-nums">{activeCalls}</p>
            <p className="text-sm text-muted-foreground">
              {activeCalls === 1 ? 'active call' : 'active calls'}
            </p>
          </div>
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
