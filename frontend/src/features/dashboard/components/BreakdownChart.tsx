import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  type TooltipProps,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'
import type { BreakdownPoint } from '../schemas'

function CustomTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-background px-3 py-2 text-sm shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }}>
          {entry.name}: <span className="font-semibold">{entry.value as number}ms</span>
        </p>
      ))}
    </div>
  )
}

interface BreakdownChartProps {
  data?: BreakdownPoint[]
  isLoading?: boolean
}

export function BreakdownChart({ data, isLoading }: BreakdownChartProps) {
  const chartData = useMemo(
    () => (data ?? []).map((d) => ({ component: d.component, Avg: d.avgMs, P95: d.p95Ms })),
    [data],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>STT / LLM / TTS Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-48 w-full rounded-lg" />
        ) : (
          <ResponsiveContainer width="100%" height={192}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 4, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 12 }} unit="ms" />
              <YAxis type="category" dataKey="component" tick={{ fontSize: 13 }} width={36} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Bar dataKey="Avg" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
              <Bar dataKey="P95" fill="hsl(var(--destructive) / 0.5)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
