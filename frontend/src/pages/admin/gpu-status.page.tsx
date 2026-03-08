import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader }    from '@/shared/components/layout/PageHeader'

export function GpuStatusPage() {
  return (
    <PageContainer>
      <PageHeader title="GPU Status" description="Monitor GPU worker health and usage." />
    </PageContainer>
  )
}
