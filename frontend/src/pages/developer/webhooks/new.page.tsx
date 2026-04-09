import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader }    from '@/shared/components/layout/PageHeader'

export function WebhookNewPage() {
  return (
    <PageContainer>
      <PageHeader title="New Webhook" description="Register a new webhook endpoint." />
    </PageContainer>
  )
}
