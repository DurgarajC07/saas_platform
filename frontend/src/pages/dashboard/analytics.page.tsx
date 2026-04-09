import { useState, useCallback } from 'react'
import { format, subDays } from 'date-fns'
import { CalendarRange, RefreshCw } from 'lucide-react'
import { useAnalytics } from '@/features/dashboard/hooks'
import { LatencyChart } from '@/features/dashboard/components/LatencyChart'
import { CallSuccessDonut } from '@/features/dashboard/components/CallSuccessDonut'
import { BreakdownChart } from '@/features/dashboard/components/BreakdownChart'
import { StatCard } from '@/shared/components/data-display/StatCard'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Phone, Gauge, Activity, Zap } from 'lucide-react'

// ── Date range picker ─────────────────────────────────────────────────────────
interface DateRange {
  from: string
  to: string
}

const PRESETS: { label: string; days: number }[] = [
  { label: '24h', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
]

function toISODate(d: Date) {
  return format(d, 'yyyy-MM-dd')
}

function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange
  onChange: (r: DateRange) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      {PRESETS.map((p) => (
        <Button
          key={p.label}
          variant="outline"
          size="sm"
          onClick={() => {
            onChange({
              from: toISODate(subDays(new Date(), p.days)),
              to: toISODate(new Date()),
            })
          }}
        >
          {p.label}
        </Button>
      ))}
      <div className="flex items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="from" className="text-xs">
            From
          </Label>
          <Input
            id="from"
            type="date"
            value={value.from}
            max={value.to}
            className="h-8 w-36 text-sm"
            onChange={(e) => {
              onChange({ ...value, from: e.target.value })
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="to" className="text-xs">
            To
          </Label>
          <Input
            id="to"
            type="date"
            value={value.to}
            min={value.from}
            max={toISODate(new Date())}
            className="h-8 w-36 text-sm"
            onChange={(e) => {
              onChange({ ...value, to: e.target.value })
            }}
          />
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function AnalyticsPage() {
  const [range, setRange] = useState<DateRange>({
    from: toISODate(subDays(new Date(), 7)),
    to: toISODate(new Date()),
  })

  const { data, isLoading, refetch } = useAnalytics(range)

  const handleRefresh = useCallback(() => {
    void refetch()
  }, [refetch])

  return (
    <PageContainer>
      <PageHeader
        title="Analytics"
        description="Platform-wide usage insights and latency breakdown."
        actions={
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        }
      />

      {/* Date range picker */}
      <div className="flex items-center gap-2">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <DateRangePicker value={range} onChange={setRange} />
      </div>

      {/* Top-level stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Calls"
          value={data?.totalCalls ?? '—'}
          icon={Phone}
          loading={isLoading}
        />
        <StatCard
          title="Success Rate"
          value={data ? `${data.successRate.toFixed(1)}%` : '—'}
          icon={Activity}
          loading={isLoading}
          delta={
            data
              ? {
                  value: data.successRate,
                  direction: data.successRate >= 90 ? 'up' : 'down',
                  label: 'of calls',
                }
              : undefined
          }
        />
        <StatCard
          title="P95 Latency"
          value={
            data?.latency.length
              ? `${(data.latency.reduce((s, p) => s + p.p95, 0) / data.latency.length).toFixed(0)}ms`
              : '—'
          }
          icon={Gauge}
          loading={isLoading}
        />
        <StatCard
          title="Failure Rate"
          value={data ? `${data.failureRate.toFixed(1)}%` : '—'}
          icon={Zap}
          loading={isLoading}
          delta={
            data
              ? {
                  value: data.failureRate,
                  direction: data.failureRate <= 5 ? 'up' : 'down',
                  label: 'of calls',
                }
              : undefined
          }
        />
      </div>

      {/* Latency line chart — spans full width */}
      <LatencyChart data={data?.latency} isLoading={isLoading} />

      {/* Success donut + STT/LLM/TTS breakdown */}
      <div className="grid gap-4 lg:grid-cols-2">
        <CallSuccessDonut successRate={data?.successRate} isLoading={isLoading} />
        <BreakdownChart data={data?.breakdown} isLoading={isLoading} />
      </div>
    </PageContainer>
  )
}
