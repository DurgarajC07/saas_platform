import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { type ColumnDef } from '@tanstack/react-table'
import { formatDistanceToNow } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Badge } from '@/shared/components/ui/badge'
import { DataTable } from '@/shared/components/data-display/DataTable'
import { useCalls } from '@/features/calls/hooks'
import { type CallLogResponse } from '@/features/calls/schemas'

const PAGE_SIZE = 20

function formatDuration(sec: number | null): string {
  if (sec === null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function directionVariant(direction: string): 'info' | 'secondary' {
  return direction === 'inbound' ? 'info' : 'secondary'
}

function statusVariant(status: string): 'success' | 'destructive' | 'warning' | 'secondary' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'no-answer') return 'destructive'
  if (status === 'connected') return 'warning'
  return 'secondary'
}

const columns: ColumnDef<CallLogResponse>[] = [
  {
    accessorKey: 'callerId',
    header: 'Caller',
    cell: ({ row }) => <span className="font-medium">{row.original.callerId ?? '—'}</span>,
  },
  {
    accessorKey: 'direction',
    header: 'Direction',
    enableSorting: false,
    cell: ({ row }) => (
      <Badge variant={directionVariant(row.original.direction)}>{row.original.direction}</Badge>
    ),
  },
  {
    accessorKey: 'status',
    header: 'Status',
    enableSorting: false,
    cell: ({ row }) => <Badge variant={statusVariant(row.original.status)}>{row.original.status}</Badge>,
  },
  {
    accessorKey: 'durationSec',
    header: 'Duration',
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">{formatDuration(row.original.durationSec)}</span>
    ),
  },
  {
    accessorKey: 'startedAt',
    header: 'Started',
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {row.original.startedAt
          ? formatDistanceToNow(new Date(row.original.startedAt), { addSuffix: true })
          : '—'}
      </span>
    ),
  },
]

export function CallsListPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)

  const { data, isLoading } = useCalls({ page, pageSize: PAGE_SIZE })

  const calls = data?.calls ?? []
  const rowCount = data?.pagination.totalItems ?? 0

  function handleRowClick(call: CallLogResponse) {
    void navigate({ to: '/calls/$callId', params: { callId: call.id } })
  }

  return (
    <PageContainer>
      <PageHeader title="Calls" description="Browse all inbound and outbound calls across every agent." />

      <div className="mt-6">
        <DataTable<CallLogResponse>
          columns={columns}
          data={calls}
          isLoading={isLoading}
          onRowClick={handleRowClick}
          pagination={{ pageIndex: page - 1, pageSize: PAGE_SIZE }}
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
