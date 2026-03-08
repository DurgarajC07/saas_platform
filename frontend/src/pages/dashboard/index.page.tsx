import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader }    from '@/shared/components/layout/PageHeader'
import { Card, CardContent } from '@/shared/components/ui/card'
import { Badge }         from '@/shared/components/ui/badge'

export function DashboardPage() {
  return (
    <PageContainer>
      <PageHeader title="Dashboard" description="Overview of your AI voice platform." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {['Total Calls', 'Active Agents', 'Minutes Used', 'Success Rate'].map((label) => (
          <Card key={label}>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">{label}</p>
              <p className="mt-1 text-3xl font-bold">—</p>
              <Badge variant="secondary" className="mt-2">Loading…</Badge>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageContainer>
  )
}
