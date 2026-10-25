import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryKeys } from '@/shared/api/query-keys'
import { getErrorMessage } from '@/shared/api/error-handler'
import { billingApi } from './api'
import type { SubscribeInput, AddPaymentMethodInput } from './schemas'

// ─── usePlans ─────────────────────────────────────────────────────────────────
export function usePlans() {
  return useQuery({
    queryKey: queryKeys.billing.plans(),
    queryFn: () => billingApi.listPlans(),
    staleTime: 5 * 60_000,
  })
}

// ─── useSubscription ──────────────────────────────────────────────────────────
export function useSubscription() {
  return useQuery({
    queryKey: queryKeys.billing.subscription(),
    queryFn: () => billingApi.getSubscription(),
  })
}

// ─── useSubscribe ─────────────────────────────────────────────────────────────
export function useSubscribe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SubscribeInput) => billingApi.subscribe(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billing.subscription() })
      toast.success('Subscription updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useCancelSubscription ────────────────────────────────────────────────────
export function useCancelSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params?: { reason?: string; atPeriodEnd?: boolean }) =>
      billingApi.cancelSubscription(params),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billing.subscription() })
      toast.success('Subscription canceled.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useInvoices ──────────────────────────────────────────────────────────────
export function useInvoices(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: queryKeys.billing.invoices(page),
    queryFn: () => billingApi.listInvoices(page, pageSize),
    placeholderData: (prev) => prev,
  })
}

// ─── useInvoice ───────────────────────────────────────────────────────────────
export function useInvoice(id: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.billing.invoice(id ?? ''),
    queryFn: () => billingApi.getInvoice(id ?? ''),
    enabled: Boolean(id),
  })
}

// ─── usePaymentMethods ────────────────────────────────────────────────────────
export function usePaymentMethods() {
  return useQuery({
    queryKey: queryKeys.billing.paymentMethods(),
    queryFn: () => billingApi.listPaymentMethods(),
  })
}

// ─── useAddPaymentMethod ──────────────────────────────────────────────────────
export function useAddPaymentMethod() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AddPaymentMethodInput) => billingApi.addPaymentMethod(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billing.paymentMethods() })
      toast.success('Payment method added.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useSetDefaultPaymentMethod ───────────────────────────────────────────────
export function useSetDefaultPaymentMethod() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pmId: string) => billingApi.setDefaultPaymentMethod(pmId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.billing.paymentMethods() })
      toast.success('Default payment method updated.')
    },
    onError: (err) => {
      toast.error(getErrorMessage(err))
    },
  })
}

// ─── useBillingUsage ──────────────────────────────────────────────────────────
export function useBillingUsage() {
  return useQuery({
    queryKey: queryKeys.billing.usage(),
    queryFn: () => billingApi.getUsage(),
    refetchInterval: 60_000,
  })
}

// ─── useInvoicePreview ────────────────────────────────────────────────────────
export function useInvoicePreview() {
  return useQuery({
    queryKey: queryKeys.billing.preview(),
    queryFn: () => billingApi.getInvoicePreview(),
  })
}
