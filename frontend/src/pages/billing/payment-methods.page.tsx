import { useState } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { CreditCardIcon, PlusIcon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent } from '@/shared/components/ui/card'
import { Badge } from '@/shared/components/ui/badge'
import { Input } from '@/shared/components/ui/input'
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

import {
  usePaymentMethods,
  useAddPaymentMethod,
  useSetDefaultPaymentMethod,
} from '@/features/billing/hooks'
import { addPaymentMethodSchema, type AddPaymentMethodInput } from '@/features/billing/schemas'

export function PaymentMethodsPage() {
  const { data, isLoading } = usePaymentMethods()
  const addPaymentMethod = useAddPaymentMethod()
  const setDefault = useSetDefaultPaymentMethod()
  const [dialogOpen, setDialogOpen] = useState(false)

  const form = useForm<AddPaymentMethodInput>({
    resolver: zodResolver(addPaymentMethodSchema),
    defaultValues: {
      externalPaymentMethodId: '',
      type: 'card',
      cardBrand: '',
      lastFour: '',
      setAsDefault: false,
    },
  })

  const paymentMethods = data?.paymentMethods ?? []

  function handleSubmit(values: AddPaymentMethodInput) {
    addPaymentMethod.mutate(values, {
      onSuccess: () => {
        setDialogOpen(false)
        form.reset()
      },
    })
  }

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

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add payment method</DialogTitle>
          </DialogHeader>

          {/* Real tokenized card collection (e.g. Stripe Elements) isn't wired up yet — this attaches an already-tokenized/provider payment-method id. */}
          <form
            onSubmit={(e) => {
              void form.handleSubmit(handleSubmit)(e)
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="externalPaymentMethodId">
                Provider payment-method id <span className="text-destructive">*</span>
              </Label>
              <Input
                id="externalPaymentMethodId"
                placeholder="pm_1234567890"
                {...form.register('externalPaymentMethodId')}
              />
              {form.formState.errors.externalPaymentMethodId && (
                <p className="text-destructive text-sm">
                  {form.formState.errors.externalPaymentMethodId.message}
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cardBrand">Card brand</Label>
                <Input id="cardBrand" placeholder="Visa" {...form.register('cardBrand')} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastFour">Last 4 digits</Label>
                <Input
                  id="lastFour"
                  placeholder="4242"
                  maxLength={4}
                  {...form.register('lastFour')}
                />
                {form.formState.errors.lastFour && (
                  <p className="text-destructive text-sm">
                    {form.formState.errors.lastFour.message}
                  </p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="expiresMonth">Expiry month</Label>
                <Input
                  id="expiresMonth"
                  type="number"
                  min={1}
                  max={12}
                  placeholder="12"
                  {...form.register('expiresMonth')}
                />
                {form.formState.errors.expiresMonth && (
                  <p className="text-destructive text-sm">
                    {form.formState.errors.expiresMonth.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="expiresYear">Expiry year</Label>
                <Input
                  id="expiresYear"
                  type="number"
                  min={2024}
                  placeholder="2030"
                  {...form.register('expiresYear')}
                />
                {form.formState.errors.expiresYear && (
                  <p className="text-destructive text-sm">
                    {form.formState.errors.expiresYear.message}
                  </p>
                )}
              </div>
            </div>

            <Controller
              control={form.control}
              name="setAsDefault"
              render={({ field }) => (
                <div className="flex items-center justify-between rounded-lg border p-4">
                  <div>
                    <p className="font-medium">Set as default</p>
                    <p className="text-muted-foreground text-sm">
                      Use this payment method for future charges.
                    </p>
                  </div>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </div>
              )}
            />

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
              <Button type="submit" disabled={addPaymentMethod.isPending}>
                {addPaymentMethod.isPending ? 'Adding…' : 'Add payment method'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
