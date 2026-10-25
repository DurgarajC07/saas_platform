import { useParams } from '@tanstack/react-router'
import { format } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { useInvoice } from '@/features/billing/hooks'

function formatCurrency(amount: string, currency: string): string {
  return `${currency} ${Number(amount).toFixed(2)}`
}

export function InvoiceDetailPage() {
  const { invoiceId } = useParams({ from: '/billing/invoices/$invoiceId' })
  const { data: invoice, isLoading } = useInvoice(invoiceId)

  const billingDetails = invoice ? Object.entries(invoice.billingDetails) : []

  return (
    <PageContainer>
      <PageHeader
        title="Invoice"
        description="Invoice details and download."
        actions={
          invoice?.invoicePdfUrl ? (
            <Button asChild>
              <a href={invoice.invoicePdfUrl} target="_blank" rel="noreferrer">
                Download PDF
              </a>
            </Button>
          ) : undefined
        }
      />

      <div className="mt-6">
        {isLoading ? (
          <Skeleton className="h-96 w-full" />
        ) : !invoice ? (
          <p className="text-muted-foreground text-sm">Invoice not found.</p>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                {invoice.invoiceNumber}
                <Badge variant="secondary">{invoice.status}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
                <div>
                  <p className="text-muted-foreground">Amount</p>
                  <p className="font-medium">{formatCurrency(invoice.amount, invoice.currency)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Tax</p>
                  <p className="font-medium">
                    {formatCurrency(invoice.taxAmount, invoice.currency)}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Total</p>
                  <p className="font-medium">
                    {formatCurrency(invoice.totalAmount, invoice.currency)}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Due date</p>
                  <p className="font-medium">
                    {invoice.dueDate ? format(new Date(invoice.dueDate), 'MMM d, yyyy') : '—'}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Paid date</p>
                  <p className="font-medium">
                    {invoice.paidAt ? format(new Date(invoice.paidAt), 'MMM d, yyyy') : 'Unpaid'}
                  </p>
                </div>
              </div>

              {billingDetails.length > 0 && (
                <div className="border-t pt-4">
                  <p className="text-muted-foreground mb-2 text-xs uppercase tracking-wide">
                    Billing details
                  </p>
                  <div className="space-y-1">
                    {billingDetails.map(([key, value]) => (
                      <div key={key} className="flex justify-between text-sm">
                        <span className="text-muted-foreground">{key}</span>
                        <span>{String(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  )
}
