import { useNavigate } from '@tanstack/react-router'
import { format } from 'date-fns'
import { ReceiptIcon, CreditCardIcon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Badge } from '@/shared/components/ui/badge'
import { Progress } from '@/shared/components/ui/progress'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { useBillingUsage, useSubscription, useInvoicePreview } from '@/features/billing/hooks'

export function BillingPage() {
  const navigate = useNavigate()
  const { data: usage, isLoading: usageLoading } = useBillingUsage()
  const { data: subscription, isLoading: subLoading } = useSubscription()
  const { data: preview } = useInvoicePreview()

  const planName = subscription?.plan?.name ?? usage?.planName ?? 'No active plan'
  const usagePct =
    usage && usage.allowedMinutes
      ? Math.min(100, Math.round((usage.usedMinutes / usage.allowedMinutes) * 100))
      : 0

  return (
    <PageContainer>
      <PageHeader
        title="Billing"
        description="Manage your subscription and usage."
        actions={
          <Button
            onClick={() => {
              void navigate({ to: '/billing/plans' })
            }}
          >
            View plans
          </Button>
        }
      />

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Current plan */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Current plan
              {subscription && <Badge variant="secondary">{subscription.status}</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {subLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <p className="text-xl font-semibold">{planName}</p>
                {subscription && (
                  <p className="text-muted-foreground text-sm capitalize">
                    {subscription.billingCycle} billing
                  </p>
                )}
                {subscription?.currentPeriodEnd && (
                  <p className="text-muted-foreground text-sm">
                    Renews {format(new Date(subscription.currentPeriodEnd), 'MMM d, yyyy')}
                  </p>
                )}
                {preview && (
                  <p className="text-muted-foreground mt-2 text-xs">
                    Estimated this period: {preview.currency} {preview.subtotal.toFixed(2)}
                  </p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Usage meter */}
        <Card>
          <CardHeader>
            <CardTitle>Usage this month</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {usageLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : usage ? (
              <>
                {usage.allowedMinutes === null ? (
                  <p className="text-sm font-medium">Unlimited minutes</p>
                ) : (
                  <>
                    <Progress value={usagePct} />
                    <p className="text-muted-foreground text-sm">
                      {usage.usedMinutes.toFixed(0)} / {usage.allowedMinutes.toFixed(0)} minutes
                      used
                    </p>
                  </>
                )}
                <p className="text-muted-foreground text-sm">
                  Credit balance: {usage.creditBalance.toFixed(2)}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">No usage data available.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick links */}
      <div className="mt-6 flex flex-wrap gap-2">
        <Button
          variant="outline"
          onClick={() => {
            void navigate({ to: '/billing/invoices' })
          }}
        >
          <ReceiptIcon className="mr-2 h-4 w-4" />
          Invoices
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            void navigate({ to: '/billing/payment-methods' })
          }}
        >
          <CreditCardIcon className="mr-2 h-4 w-4" />
          Payment methods
        </Button>
      </div>
    </PageContainer>
  )
}
