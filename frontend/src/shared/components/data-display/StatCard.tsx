import { type LucideIcon } from 'lucide-react'
import { cn } from '@/shared/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'

export interface StatCardProps {
  title: string
  value: string | number
  delta?: { value: number; direction: 'up' | 'down'; label: string }
  icon: LucideIcon
  loading?: boolean
}

export function StatCard({ title, value, delta, icon: Icon, loading }: StatCardProps) {
  if (loading) return <Skeleton className="h-32 w-full rounded-xl" />

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {delta && (
          <p
            className={cn(
              'mt-1 text-xs',
              delta.direction === 'up' ? 'text-emerald-600' : 'text-rose-600',
            )}
          >
            {delta.direction === 'up' ? '↑' : '↓'} {delta.value}% {delta.label}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
