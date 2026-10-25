import { useParams } from '@tanstack/react-router'
import { PhoneIcon, CheckCircle2Icon, ClockIcon, ArrowLeftRightIcon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { StatCard } from '@/shared/components/data-display/StatCard'
import { BreakdownChart } from '@/features/dashboard/components/BreakdownChart'
import { CallSuccessDonut } from '@/features/dashboard/components/CallSuccessDonut'
import { useAgentAnalytics } from '@/features/calls/hooks'
import { type BreakdownPoint } from '@/features/dashboard/schemas'

function formatDuration(sec: number | null): string {
  if (sec === null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function AgentAnalyticsPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/analytics' })
  const { data, isLoading } = useAgentAnalytics(agentId, 30)

  const breakdownData: BreakdownPoint[] = data
    ? [
        { component: 'STT', avgMs: data.sttLatency.avgMs ?? 0, p95Ms: data.sttLatency.p95Ms ?? 0 },
        { component: 'LLM', avgMs: data.llmLatency.avgMs ?? 0, p95Ms: data.llmLatency.p95Ms ?? 0 },
        { component: 'TTS', avgMs: data.ttsLatency.avgMs ?? 0, p95Ms: data.ttsLatency.p95Ms ?? 0 },
      ]
    : []

  return (
    <PageContainer>
      <PageHeader title="Agent Analytics" description="Performance metrics for this agent (last 30 days)." />

      <div className="mt-6 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Total Calls"
            value={data?.totalCalls ?? 0}
            icon={PhoneIcon}
            loading={isLoading}
          />
          <StatCard
            title="Success Rate"
            value={data?.successRatePct !== null && data?.successRatePct !== undefined ? `${data.successRatePct.toFixed(1)}%` : '—'}
            icon={CheckCircle2Icon}
            loading={isLoading}
          />
          <StatCard
            title="Avg Duration"
            value={formatDuration(data?.avgDurationSec ?? null)}
            icon={ClockIcon}
            loading={isLoading}
          />
          <StatCard
            title="Inbound / Outbound"
            value={`${data?.inboundCalls ?? 0} / ${data?.outboundCalls ?? 0}`}
            icon={ArrowLeftRightIcon}
            loading={isLoading}
          />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <BreakdownChart data={breakdownData} isLoading={isLoading} />
          <CallSuccessDonut successRate={data?.successRatePct ?? 0} isLoading={isLoading} />
        </div>
      </div>
    </PageContainer>
  )
}
