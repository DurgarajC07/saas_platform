import { z } from 'zod'

// ── Response interfaces ───────────────────────────────────────────────────────
export interface PlanResponse {
  id: string
  name: string
  slug: string
  description: string | null
  isActive: boolean
  priceMonthly: string | null
  priceYearly: string | null
  currency: string
  trialDays: number
  maxSeats: number | null
  maxStorageMb: number | null
  displayOrder: number
  features: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export interface PlanListResponse {
  plans: PlanResponse[]
  total: number
}

export interface SubscriptionPlanSummary {
  id: string
  name: string
  slug: string
  priceMonthly: string | null
  priceYearly: string | null
  currency: string
}

export interface SubscriptionResponse {
  id: string
  organizationId: string
  plan: SubscriptionPlanSummary | null
  status: string
  billingCycle: string
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  trialEndsAt: string | null
  canceledAt: string | null
  cancellationReason: string | null
  externalProvider: string | null
  externalSubscriptionId: string | null
  createdAt: string
  updatedAt: string
}

export interface PaginationMeta {
  page: number
  pageSize: number
  totalItems: number
  totalPages: number
  hasNext: boolean
  hasPrevious: boolean
}

export interface InvoiceResponse {
  id: string
  organizationId: string
  subscriptionId: string | null
  invoiceNumber: string
  amount: string
  currency: string
  taxAmount: string
  totalAmount: string
  status: string
  dueDate: string | null
  paidAt: string | null
  externalInvoiceId: string | null
  invoicePdfUrl: string | null
  billingDetails: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export interface InvoiceListResponse {
  invoices: InvoiceResponse[]
  pagination: PaginationMeta
}

export interface PaymentMethodResponse {
  id: string
  organizationId: string
  type: string
  provider: string | null
  externalPaymentMethodId: string | null
  isDefault: boolean
  lastFour: string | null
  cardBrand: string | null
  expiresMonth: number | null
  expiresYear: number | null
  billingAddress: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export interface PaymentMethodListResponse {
  paymentMethods: PaymentMethodResponse[]
  total: number
}

export interface BillingUsageResponse {
  orgId: string
  period: string
  usedSeconds: number
  usedMinutes: number
  allowedMinutes: number | null
  remainingMinutes: number | null
  creditBalance: number
  planName: string
}

export interface InvoiceLineItem {
  description: string
  quantity: number
  unitPrice: number
  amount: number
}

export interface InvoicePreviewResponse {
  orgId: string
  period: string
  lineItems: InvoiceLineItem[]
  subtotal: number
  currency: string
  estimatedAt: string
}

// ── Form schemas ──────────────────────────────────────────────────────────────
export const subscribeSchema = z.object({
  planId: z.string().uuid(),
  billingCycle: z.enum(['monthly', 'yearly']).default('monthly'),
})

export type SubscribeInput = z.infer<typeof subscribeSchema>

export const addPaymentMethodSchema = z.object({
  externalPaymentMethodId: z
    .string()
    .min(1, 'Required — e.g. a tokenized payment-method id from your provider'),
  type: z.string().default('card'),
  provider: z.string().optional(),
  lastFour: z.string().length(4).optional(),
  cardBrand: z.string().optional(),
  expiresMonth: z.coerce.number().int().min(1).max(12).optional(),
  expiresYear: z.coerce.number().int().min(2024).optional(),
  setAsDefault: z.boolean().default(false),
})

export type AddPaymentMethodInput = z.infer<typeof addPaymentMethodSchema>
