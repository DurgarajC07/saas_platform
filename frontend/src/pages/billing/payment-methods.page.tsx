import { useEffect, useRef, useState } from 'react'
import { loadStripe } from '@stripe/stripe-js'
import type { Stripe, StripeCardElement, StripeElements } from '@stripe/stripe-js'
import { CreditCardIcon, PlusIcon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent } from '@/shared/components/ui/card'
import { Badge } from '@/shared/components/ui/badge'
import { Label } from '@/shared/components/ui/label'
import { Switch } from '@/shared/components/ui/switch'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { EmptyState } from '@/shared/components/data-display/EmptyState'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/shared/components/ui/dialog'
import { STRIPE_PUBLISHABLE_KEY } from '@/shared/lib/constants'

import { usePaymentMethods, useAddPaymentMethod, useSetDefaultPaymentMethod } from '@/features/billing/hooks'

// Loaded once per page module — loadStripe() memoizes internally, but keep a single
// promise around so remounting the dialog doesn't re-trigger script injection.
const stripePromise = STRIPE_PUBLISHABLE_KEY ? loadStripe(STRIPE_PUBLISHABLE_KEY) : null

export function PaymentMethodsPage() {
  const { data, isLoading } = usePaymentMethods()
  const addPaymentMethod = useAddPaymentMethod()
  const setDefault = useSetDefaultPaymentMethod()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [setAsDefault, setSetAsDefault] = useState(false)
  const [cardError, setCardError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [cardElementReady, setCardElementReady] = useState(false)

  const cardMountRef = useRef<HTMLDivElement>(null)
  const stripeRef = useRef<Stripe | null>(null)
  const elementsRef = useRef<StripeElements | null>(null)
  const cardElementRef = useRef<StripeCardElement | null>(null)

  const paymentMethods = data?.paymentMethods ?? []

  // Mount the Stripe Elements card input whenever the dialog opens.
  useEffect(() => {
    if (!dialogOpen || !stripePromise) {
      return
    }

    let unmounted = false

    void stripePromise.then((stripe) => {
      if (!stripe || unmounted || !cardMountRef.current) {
        return
      }
      stripeRef.current = stripe
      const elements = stripe.elements()
      elementsRef.current = elements

      const cardElement = elements.create('card', {
        style: {
          base: {
            fontSize: '14px',
            color: 'hsl(var(--foreground))',
            '::placeholder': { color: 'hsl(var(--muted-foreground))' },
          },
          invalid: {
            color: 'hsl(var(--destructive))',
          },
        },
      })
      cardElement.mount(cardMountRef.current)
      cardElement.on('change', (event) => {
        setCardError(event.error?.message ?? null)
      })
      cardElement.on('ready', () => {
        setCardElementReady(true)
      })
      cardElementRef.current = cardElement
    })

    return () => {
      unmounted = true
      setCardElementReady(false)
      cardElementRef.current?.unmount()
      cardElementRef.current?.destroy()
      cardElementRef.current = null
      elementsRef.current = null
    }
  }, [dialogOpen])

  async function handleSubmit() {
    setSubmitError(null)

    const stripe = stripeRef.current
    const cardElement = cardElementRef.current
    if (!stripe || !cardElement) {
      setSubmitError('Payment collection is not ready yet. Please try again in a moment.')
      return
    }

    const result = await stripe.createPaymentMethod({
      type: 'card',
      card: cardElement,
    })

    if (result.error) {
      setSubmitError(result.error.message ?? 'Could not process this card. Please check the details.')
      return
    }

    const pm = result.paymentMethod
    addPaymentMethod.mutate(
      {
        externalPaymentMethodId: pm.id,
        type: 'card',
        provider: 'stripe',
        cardBrand: pm.card?.brand ?? undefined,
        lastFour: pm.card?.last4 ?? undefined,
        expiresMonth: pm.card?.exp_month,
        expiresYear: pm.card?.exp_year,
        setAsDefault,
      },
      {
        onSuccess: () => {
          setDialogOpen(false)
          setSetAsDefault(false)
          setSubmitError(null)
          cardElementRef.current?.clear()
        },
        onError: (err) => {
          setSubmitError(err instanceof Error ? err.message : 'Failed to save payment method.')
        },
      },
    )
  }

  const stripeConfigured = Boolean(STRIPE_PUBLISHABLE_KEY)

  return (
    <PageContainer>
      <PageHeader
        title="Payment Methods"
        description="Manage saved payment methods."
        actions={
          <Button
            onClick={() => {
              setDialogOpen(true)
            }}
          >
            <PlusIcon className="mr-2 h-4 w-4" />
            Add payment method
          </Button>
        }
      />

      <div className="mt-6">
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : paymentMethods.length === 0 ? (
          <EmptyState
            icon={CreditCardIcon}
            title="No payment methods"
            description="Add a payment method to keep your subscription active."
            action={
              <Button
                onClick={() => {
                  setDialogOpen(true)
                }}
              >
                <PlusIcon className="mr-2 h-4 w-4" />
                Add payment method
              </Button>
            }
          />
        ) : (
          <div className="space-y-3">
            {paymentMethods.map((pm) => (
              <Card key={pm.id}>
                <CardContent className="flex items-center justify-between pt-6">
                  <div>
                    <p className="font-medium">
                      {pm.cardBrand ?? pm.type} {pm.lastFour ? `•••• ${pm.lastFour}` : ''}
                    </p>
                    <p className="text-muted-foreground text-sm">
                      {pm.expiresMonth && pm.expiresYear
                        ? `Expires ${pm.expiresMonth.toString().padStart(2, '0')}/${pm.expiresYear}`
                        : 'No expiry on file'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {pm.isDefault && <Badge variant="secondary">Default</Badge>}
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={pm.isDefault || setDefault.isPending}
                      onClick={() => {
                        setDefault.mutate(pm.id)
                      }}
                    >
                      Set as default
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) {
            setCardError(null)
            setSubmitError(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add payment method</DialogTitle>
          </DialogHeader>

          {!stripeConfigured ? (
            <p className="text-destructive text-sm">
              Payment collection is not configured — contact support.
            </p>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void handleSubmit()
              }}
              className="space-y-4"
            >
              <div className="space-y-2">
                <Label htmlFor="card-element">
                  Card details <span className="text-destructive">*</span>
                </Label>
                <div
                  id="card-element"
                  ref={cardMountRef}
                  className="border-input min-h-[38px] rounded-md border px-3 py-2.5"
                />
                {cardError && <p className="text-destructive text-sm">{cardError}</p>}
                {submitError && <p className="text-destructive text-sm">{submitError}</p>}
              </div>

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="font-medium">Set as default</p>
                  <p className="text-muted-foreground text-sm">
                    Use this payment method for future charges.
                  </p>
                </div>
                <Switch checked={setAsDefault} onCheckedChange={setSetAsDefault} />
              </div>

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setDialogOpen(false)
                  }}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={addPaymentMethod.isPending || !cardElementReady}>
                  {addPaymentMethod.isPending ? 'Adding…' : 'Add payment method'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
