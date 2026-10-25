import { apiClient } from '@/shared/api/client'
import type {
  PlanListResponse,
  SubscriptionResponse,
  InvoiceListResponse,
  InvoiceResponse,
  PaymentMethodListResponse,
  PaymentMethodResponse,
  BillingUsageResponse,
  InvoicePreviewResponse,
  SubscribeInput,
  AddPaymentMethodInput,
} from './schemas'

interface CancelSubscriptionParams {
  reason?: string
  atPeriodEnd?: boolean
}

// ─────────────────────────────────────────────────────────────────────────────
// Billing API  —  all endpoints under /billing
// ─────────────────────────────────────────────────────────────────────────────

export const billingApi = {
  /** GET /billing/plans */
  listPlans: async (): Promise<PlanListResponse> => {
    const { data } = await apiClient.get<PlanListResponse>('/billing/plans')
    return data
  },

  /** GET /billing/subscription */
  getSubscription: async (): Promise<SubscriptionResponse | null> => {
    const { data } = await apiClient.get<SubscriptionResponse | null>('/billing/subscription')
    return data
  },

  /** POST /billing/subscribe */
  subscribe: async (body: SubscribeInput): Promise<SubscriptionResponse> => {
    const { data } = await apiClient.post<SubscriptionResponse>('/billing/subscribe', {
      plan_id: body.planId,
      billing_cycle: body.billingCycle,
    })
    return data
  },

  /** POST /billing/cancel */
  cancelSubscription: async (params?: CancelSubscriptionParams): Promise<SubscriptionResponse> => {
    const { data } = await apiClient.post<SubscriptionResponse>('/billing/cancel', {
      ...(params?.reason && { reason: params.reason }),
      at_period_end: params?.atPeriodEnd ?? true,
    })
    return data
  },

  /** GET /billing/invoices */
  listInvoices: async (page = 1, pageSize = 20): Promise<InvoiceListResponse> => {
    const { data } = await apiClient.get<InvoiceListResponse>('/billing/invoices', {
      params: { page, page_size: pageSize },
    })
    return data
  },

  /** GET /billing/invoices/:invoiceId */
  getInvoice: async (invoiceId: string): Promise<InvoiceResponse> => {
    const { data } = await apiClient.get<InvoiceResponse>(`/billing/invoices/${invoiceId}`)
    return data
  },

  /** GET /billing/payment-methods */
  listPaymentMethods: async (): Promise<PaymentMethodListResponse> => {
    const { data } = await apiClient.get<PaymentMethodListResponse>('/billing/payment-methods')
    return data
  },

  /** POST /billing/payment-methods */
  addPaymentMethod: async (body: AddPaymentMethodInput): Promise<PaymentMethodResponse> => {
    const { data } = await apiClient.post<PaymentMethodResponse>('/billing/payment-methods', {
      external_payment_method_id: body.externalPaymentMethodId,
      type: body.type,
      ...(body.provider && { provider: body.provider }),
      ...(body.lastFour && { last_four: body.lastFour }),
      ...(body.cardBrand && { card_brand: body.cardBrand }),
      ...(body.expiresMonth !== undefined && { expires_month: body.expiresMonth }),
      ...(body.expiresYear !== undefined && { expires_year: body.expiresYear }),
      set_as_default: body.setAsDefault,
    })
    return data
  },

  /** PUT /billing/payment-methods/:pmId/default */
  setDefaultPaymentMethod: async (pmId: string): Promise<PaymentMethodResponse> => {
    const { data } = await apiClient.put<PaymentMethodResponse>(
      `/billing/payment-methods/${pmId}/default`,
    )
    return data
  },

  /** GET /billing/usage */
  getUsage: async (): Promise<BillingUsageResponse> => {
    const { data } = await apiClient.get<BillingUsageResponse>('/billing/usage')
    return data
  },

  /** GET /billing/invoice-preview */
  getInvoicePreview: async (): Promise<InvoicePreviewResponse> => {
    const { data } = await apiClient.get<InvoicePreviewResponse>('/billing/invoice-preview')
    return data
  },
}
