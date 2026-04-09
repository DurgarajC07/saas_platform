import { useState, useCallback } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useAgentPerformance } from '../hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { cn } from '@/shared/lib/utils'
import type { AgentPerfRow } from '../schemas'

function SortIcon({ sorted }: { sorted: false | 'asc' | 'desc' }) {
  if (sorted === 'asc') return <ArrowUp className="ml-1 inline h-3 w-3" />
  if (sorted === 'desc') return <ArrowDown className="ml-1 inline h-3 w-3" />
  return <ArrowUpDown className="ml-1 inline h-3 w-3 opacity-40" />
}

const columns: ColumnDef<AgentPerfRow>[] = [
  {
    accessorKey: 'agentName',
    header: 'Agent',
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span className="font-medium">{row.original.agentName}</span>
        {row.original.isLive && (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
        )}
      </div>
    ),
  },
  {
    accessorKey: 'callsToday',
    header: 'Calls Today',
    cell: ({ getValue }) => <span className="tabular-nums">{getValue<number>()}</span>,
  },
  {
    accessorKey: 'avgDurationSec',
    header: 'Avg Duration',
    cell: ({ getValue }) => {
      const s = getValue<number>()
      const m = Math.floor(s / 60)
      const r = Math.round(s % 60)
      return (
        <span className="tabular-nums">
          {m}m {r}s
        </span>
      )
    },
  },
  {
    accessorKey: 'successRate',
    header: 'Success Rate',
    cell: ({ getValue }) => {
      const v = getValue<number>()
      return (
        <Badge
          variant={v >= 90 ? 'default' : v >= 75 ? 'secondary' : 'destructive'}
          className="tabular-nums"
        >
          {v.toFixed(1)}%
        </Badge>
      )
    },
  },
]

export function AgentPerfTable() {
  const { data, isLoading } = useAgentPerformance()
  const [sorting, setSorting] = useState<SortingState>([])

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const handleSort = useCallback(
    (columnId: string) => table.getColumn(columnId)?.toggleSorting(),
    [table],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Performance</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full rounded" />
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((h) => (
                    <TableHead
                      key={h.id}
                      className={cn(h.column.getCanSort() && 'cursor-pointer select-none')}
                      onClick={() => {
                        if (h.column.getCanSort()) handleSort(h.column.id)
                      }}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      <SortIcon sorted={h.column.getIsSorted()} />
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
                    className="py-8 text-center text-muted-foreground"
                  >
                    No data for this period.
                  </TableCell>
                </TableRow>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
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
  )
}
