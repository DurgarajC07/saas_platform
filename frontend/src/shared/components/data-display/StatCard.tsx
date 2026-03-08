import { type LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/shared/components/ui/card'
import { Badge }             from '@/shared/components/ui/badge'
import { cn }                from '@/shared/lib/utils'

interface StatCardProps {
  title: string
  value: string | number
  description?: string
  icon?: LucideIcon
  trend?: { value: number; label?: string }
  className?: string
}

export function StatCard({ title, value, description, icon: Icon, trend, className }: StatCardProps) {
  const up = (trend?.value ?? 0) >= 0

  return (
    <Card className={cn(className)}>
      <CardContent className="pt-6">
        <div className="flex items-start justify-between">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          {Icon && (
            <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon className="size-4" />
            </div>
          )}
        </div>
        <p className="mt-2 text-3xl font-bold tracking-tight">{value}</p>
        <div className="mt-2 flex items-center gap-2">
          {trend !== undefined && (
            <Badge variant={up ? 'success' : 'destructive'} className="text-xs">
              {up ? '▲' : '▼'} {Math.abs(trend.value)}%
            </Badge>
          )}
          {description && (
            <span className="text-xs text-muted-foreground">{description}</span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
