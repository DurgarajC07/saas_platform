import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { type ColumnDef } from '@tanstack/react-table'
import { format } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Badge } from '@/shared/components/ui/badge'
import { DataTable } from '@/shared/components/data-display/DataTable'

import { useInvoices } from '@/features/billing/hooks'
import type { InvoiceResponse } from '@/features/billing/schemas'

function formatCurrency(amount: string, currency: string): string {
  return `${currency} ${Number(amount).toFixed(2)}`
}

function statusVariant(status: string): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'paid') return 'success'
  if (status === 'pending' || status === 'open') return 'warning'
  if (status === 'failed' || status === 'void') return 'destructive'
  return 'secondary'
}

const columns: ColumnDef<InvoiceResponse>[] = [
  {
    accessorKey: 'invoiceNumber',
    header: 'Invoice #',
    cell: ({ row }) => <span className="font-medium">{row.original.invoiceNumber}</span>,
  },
  {
    accessorKey: 'status',
    header: 'Status',
    enableSorting: false,
    cell: ({ row }) => (
      <Badge variant={statusVariant(row.original.status)}>{row.original.status}</Badge>
    ),
  },
  {
    accessorKey: 'totalAmount',
    header: 'Total',
    cell: ({ row }) => formatCurrency(row.original.totalAmount, row.original.currency),
  },
  {
    accessorKey: 'dueDate',
    header: 'Due date',
    cell: ({ row }) =>
      row.original.dueDate ? format(new Date(row.original.dueDate), 'MMM d, yyyy') : '—',
  },
  {
    accessorKey: 'paidAt',
    header: 'Paid',
    cell: ({ row }) =>
      row.original.paidAt ? format(new Date(row.original.paidAt), 'MMM d, yyyy') : 'Unpaid',
  },
]

export function InvoicesListPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const pageSize = 20

  const { data, isLoading } = useInvoices(page, pageSize)
  const invoices = data?.invoices ?? []
  const rowCount = data?.pagination.totalItems ?? 0

  function handleRowClick(invoice: InvoiceResponse) {
    void navigate({ to: '/billing/invoices/$invoiceId', params: { invoiceId: invoice.id } })
  }

  return (
    <PageContainer>
      <PageHeader title="Invoices" description="View all invoices and payment history." />

      <div className="mt-6">
        <DataTable<InvoiceResponse>
          columns={columns}
          data={invoices}
          isLoading={isLoading}
          onRowClick={handleRowClick}
          pagination={{ pageIndex: page - 1, pageSize }}
          onPaginationChange={(p) => {
            setPage(p.pageIndex + 1)
          }}
          rowCount={rowCount}
          getRowId={(r) => r.id}
        />
      </div>
    </PageContainer>
  )
}
