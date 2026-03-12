import { useMemo, useState } from 'react'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'
import { formatDistanceToNow, format } from 'date-fns'
import { PhoneIncoming, PhoneOutgoing, Wifi, WifiOff, Loader2 } from 'lucide-react'
import { useLiveCallTable } from '@/features/dashboard/hooks'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import type { LiveCall } from '@/features/dashboard/schemas'

// ── Column definitions ────────────────────────────────────────────────────────
const columns: ColumnDef<LiveCall>[] = [
  {
    accessorKey: 'direction',
    header: '',
    size: 32,
    cell: ({ getValue }) =>
      getValue<string>() === 'inbound' ? (
        <PhoneIncoming className="h-4 w-4 text-emerald-500" />
      ) : (
        <PhoneOutgoing className="h-4 w-4 text-sky-500" />
      ),
  },
  {
    accessorKey: 'callerNumber',
    header: 'Caller',
    cell: ({ getValue }) => <span className="font-mono text-sm">{getValue<string>()}</span>,
  },
  {
    accessorKey: 'agentName',
    header: 'Agent',
  },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ getValue }) => {
      const s = getValue<string>()
      const variant =
        s === 'active' ? 'default' : s === 'ringing' ? 'secondary' : ('outline' as const)
      return (
        <Badge variant={variant} className="capitalize">
          {s.replace('_', ' ')}
        </Badge>
      )
    },
  },
  {
    accessorKey: 'startedAt',
    header: 'Started',
    cell: ({ getValue }) => (
      <span className="text-sm text-muted-foreground">
        {format(new Date(getValue<string>()), 'HH:mm:ss')}
      </span>
    ),
  },
  {
    accessorKey: 'durationSec',
    header: 'Duration',
    cell: ({ row }) => {
      const started = new Date(row.original.startedAt)
      const elapsed = formatDistanceToNow(started, { addSuffix: false, includeSeconds: true })
      return <span className="tabular-nums text-sm">{elapsed}</span>
    },
  },
]

// ── Call detail sheet ─────────────────────────────────────────────────────────
function CallDetailSheet({
  call,
  open,
  onClose,
}: {
  call: LiveCall | null
  open: boolean
  onClose: () => void
}) {
  if (!call) return null
  return (
    <Sheet
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose()
      }}
    >
      <SheetContent className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{call.callerNumber}</SheetTitle>
        </SheetHeader>
        <div className="mt-4 space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-2 rounded-lg border p-4">
            <span className="text-muted-foreground">Agent</span>
            <span className="font-medium">{call.agentName}</span>

            <span className="text-muted-foreground">Direction</span>
            <span className="capitalize">{call.direction}</span>

            <span className="text-muted-foreground">Status</span>
            <Badge variant="default" className="w-fit capitalize">
              {call.status.replace('_', ' ')}
            </Badge>

            <span className="text-muted-foreground">Started</span>
            <span className="font-mono">{format(new Date(call.startedAt), 'HH:mm:ss')}</span>

            <span className="text-muted-foreground">Duration</span>
            <span className="font-mono tabular-nums">
              {formatDistanceToNow(new Date(call.startedAt), { includeSeconds: true })}
            </span>

            <span className="text-muted-foreground">Call ID</span>
            <span className="break-all font-mono text-xs">{call.id}</span>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ── SSE status indicator ──────────────────────────────────────────────────────
function StreamIndicator({ status }: { status: string }) {
  if (status === 'connected') {
    return (
      <div className="flex items-center gap-1.5 text-xs text-emerald-600">
        <Wifi className="h-3.5 w-3.5" />
        Live
      </div>
    )
  }
  if (status === 'connecting') {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Connecting…
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-xs text-rose-600">
      <WifiOff className="h-3.5 w-3.5" />
      Disconnected
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function CallsDashboardPage() {
  const { calls, isLoading, sseStatus } = useLiveCallTable()
  const [selectedCall, setSelectedCall] = useState<LiveCall | null>(null)

  const activeCount = useMemo(() => calls.filter((c) => c.status === 'active').length, [calls])
  const ringingCount = useMemo(() => calls.filter((c) => c.status === 'ringing').length, [calls])

  const table = useReactTable({
    data: calls,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <PageContainer>
      <PageHeader
        title="Live Calls"
        description="Real-time call activity — rows update automatically via SSE."
        actions={<StreamIndicator status={sseStatus} />}
      />

      {/* Summary badges */}
      <div className="flex gap-3">
        <Badge variant="default" className="h-7 gap-1.5 px-3">
          {activeCount} active
        </Badge>
        <Badge variant="secondary" className="h-7 gap-1.5 px-3">
          {ringingCount} ringing
        </Badge>
        <Badge variant="outline" className="h-7 gap-1.5 px-3">
          {calls.length} total
        </Badge>
      </div>

      {/* Live call table */}
      <Card>
        <CardHeader>
          <CardTitle>Active &amp; Recent Calls</CardTitle>
          <CardDescription>Click a row to view call details.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full rounded" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id}>
                    {hg.headers.map((h) => (
                      <TableHead key={h.id}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="py-12 text-center text-muted-foreground"
                    >
                      No active calls right now.
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => {
                        setSelectedCall(row.original)
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CallDetailSheet
        call={selectedCall}
        open={Boolean(selectedCall)}
        onClose={() => {
          setSelectedCall(null)
        }}
      />
    </PageContainer>
  )
}
