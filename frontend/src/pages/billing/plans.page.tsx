import { useNavigate } from '@tanstack/react-router'
import { CheckIcon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/shared/components/ui/card'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { usePlans, useSubscription, useSubscribe } from '@/features/billing/hooks'
import type { PlanResponse } from '@/features/billing/schemas'

function formatPrice(priceMonthly: string | null): string {
  if (priceMonthly === null) return 'Contact us'
  return `$${Number(priceMonthly).toFixed(2)}/mo`
}

export function PlansPage() {
  const navigate = useNavigate()
  const { data, isLoading } = usePlans()
  const { data: subscription } = useSubscription()
  const subscribe = useSubscribe()

  const plans = data?.plans ?? []
  const currentPlanId = subscription?.plan?.id

  function handleSelect(plan: PlanResponse) {
    subscribe.mutate(
      { planId: plan.id, billingCycle: 'monthly' },
      {
        onSuccess: () => {
          void navigate({ to: '/billing' })
        },
      },
    )
  }

  return (
    <PageContainer>
      <PageHeader title="Plans" description="Compare and upgrade subscription plans." />

      {isLoading ? (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((plan) => {
            const isCurrent = plan.id === currentPlanId
            const features = Object.entries(plan.features)
            let buttonLabel = 'Upgrade'
            if (isCurrent) {
              buttonLabel = 'Current plan'
            } else if (currentPlanId) {
              buttonLabel = 'Switch'
            }
            return (
              <Card key={plan.id} className={isCurrent ? 'border-primary' : undefined}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    {plan.name}
                    {isCurrent && <Badge>Current plan</Badge>}
                  </CardTitle>
                  {plan.description && <CardDescription>{plan.description}</CardDescription>}
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-2xl font-bold">{formatPrice(plan.priceMonthly)}</p>
                  {plan.trialDays > 0 && (
                    <p className="text-muted-foreground text-sm">
                      {plan.trialDays}-day free trial
                    </p>
                  )}
                  {features.length > 0 && (
                    <ul className="space-y-1.5">
                      {features.map(([key, value]) => (
                        <li key={key} className="flex items-start gap-2 text-sm">
                          <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                          <span>
                            {key}: {String(value)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <Button
                    className="w-full"
                    disabled={isCurrent || subscribe.isPending}
                    onClick={() => {
                      handleSelect(plan)
                    }}
                  >
                    {buttonLabel}
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </PageContainer>
  )
}
