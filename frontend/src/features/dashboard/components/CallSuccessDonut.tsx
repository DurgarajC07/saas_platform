import { useMemo } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, type TooltipProps } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'

interface DonutProps {
  successRate?: number // 0-100
  isLoading?: boolean
}

function CustomTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null
  const entry = payload[0]
  const color =
    (entry.name as string) === 'Success' ? 'hsl(var(--primary))' : 'hsl(var(--destructive) / 0.6)'
  return (
    <div className="rounded-lg border bg-background px-3 py-2 text-sm shadow-md">
      <p style={{ color }}>
        {entry.name as string}: <span className="font-semibold">{entry.value as number}%</span>
      </p>
    </div>
  )
}

export function CallSuccessDonut({ successRate, isLoading }: DonutProps) {
  const rate = successRate ?? 0
  const failure = Math.max(0, 100 - rate)

  const chartData = useMemo(
    () => [
      { name: 'Success', value: rate },
      { name: 'Failed', value: failure },
    ],
    [rate, failure],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Success Rate</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-2">
        {isLoading ? (
          <Skeleton className="h-48 w-48 rounded-full" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={192}>
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={88}
                  paddingAngle={3}
                  dataKey="value"
                >
                  <Cell fill="hsl(var(--primary))" />
                  <Cell fill="hsl(var(--destructive) / 0.6)" />
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <p className="text-3xl font-bold -mt-4">{rate.toFixed(1)}%</p>
            <p className="text-xs text-muted-foreground">calls completed successfully</p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
