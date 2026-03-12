import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type PaginationState,
  type Row,
  type RowSelectionState,
} from '@tanstack/react-table'
import {
  ChevronUpIcon,
  ChevronDownIcon,
  ChevronsUpDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from 'lucide-react'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { cn } from '@/shared/lib/utils'

// ─── Types ────────────────────────────────────────────────────────────────────
export interface DataTableProps<TData> {
  columns: ColumnDef<TData>[]
  data: TData[]
  isLoading?: boolean
  onRowClick?: (row: TData) => void
  sorting?: SortingState
  onSortingChange?: (s: SortingState) => void
  pagination?: PaginationState
  onPaginationChange?: (p: PaginationState) => void
  rowCount?: number
  rowSelection?: RowSelectionState
  onRowSelectionChange?: (s: RowSelectionState) => void
  enableRowSelection?: boolean
  getRowId?: (row: TData) => string
}

// ─── Skeleton rows while loading ──────────────────────────────────────────────
function TableSkeletonRows({ count, colCount }: { count: number; colCount: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i} className="pointer-events-none">
          {Array.from({ length: colCount }).map((__, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

// ─── Sort icon ────────────────────────────────────────────────────────────────
function SortIcon({ sorted }: { sorted: false | 'asc' | 'desc' }) {
  if (sorted === 'asc') return <ChevronUpIcon className="ml-1 inline-block h-3 w-3" />
  if (sorted === 'desc') return <ChevronDownIcon className="ml-1 inline-block h-3 w-3" />
  return <ChevronsUpDownIcon className="ml-1 inline-block h-3 w-3 opacity-40" />
}

// ─── Pagination bar ───────────────────────────────────────────────────────────
function DataTablePagination({
  pageIndex,
  pageSize,
  rowCount,
  onPrev,
  onNext,
}: {
  pageIndex: number
  pageSize: number
  rowCount: number
  onPrev: () => void
  onNext: () => void
}) {
  const from = rowCount === 0 ? 0 : pageIndex * pageSize + 1
  const to = Math.min((pageIndex + 1) * pageSize, rowCount)
  const pages = Math.ceil(rowCount / pageSize)
  return (
    <div className="flex items-center justify-between px-2 py-3">
      <p className="text-muted-foreground text-sm">
        {rowCount === 0 ? 'No results' : `${from}–${to} of ${rowCount}`}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onPrev}
          disabled={pageIndex === 0}
          aria-label="Previous page"
        >
          <ChevronLeftIcon className="h-4 w-4" />
        </Button>
        <span className="text-sm">
          Page {pageIndex + 1} of {Math.max(1, pages)}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={onNext}
          disabled={pageIndex >= pages - 1}
          aria-label="Next page"
        >
          <ChevronRightIcon className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

// ─── Main DataTable ───────────────────────────────────────────────────────────
export function DataTable<TData>({
  columns,
  data,
  isLoading = false,
  onRowClick,
  sorting = [],
  onSortingChange,
  pagination,
  onPaginationChange,
  rowCount = 0,
  rowSelection = {},
  onRowSelectionChange,
  enableRowSelection = false,
  getRowId,
}: DataTableProps<TData>) {
  // Prepend a select-all checkbox column when row-selection is enabled
  const allColumns: ColumnDef<TData>[] = enableRowSelection
    ? [
        {
          id: 'select',
          header: ({ table }) => (
            <Checkbox
              checked={
                table.getIsAllPageRowsSelected()
                  ? true
                  : table.getIsSomePageRowsSelected()
                    ? 'indeterminate'
                    : false
              }
              onCheckedChange={(v) => {
                table.toggleAllPageRowsSelected(Boolean(v))
              }}
              aria-label="Select all"
            />
          ),
          cell: ({ row }: { row: Row<TData> }) => (
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(v) => {
                row.toggleSelected(Boolean(v))
              }}
              aria-label="Select row"
              onClick={(e) => {
                e.stopPropagation()
              }}
            />
          ),
          size: 40,
          enableSorting: false,
        },
        ...columns,
      ]
    : columns

  const table = useReactTable<TData>({
    data,
    columns: allColumns,
    state: {
      sorting,
      ...(pagination && { pagination }),
      rowSelection,
    },
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater
      onSortingChange?.(next)
    },
    onPaginationChange: onPaginationChange
      ? (updater) => {
          const next =
            typeof updater === 'function'
              ? updater(pagination ?? { pageIndex: 0, pageSize: 20 })
              : updater
          onPaginationChange(next)
        }
      : undefined,
    onRowSelectionChange: onRowSelectionChange
      ? (updater) => {
          const next = typeof updater === 'function' ? updater(rowSelection) : updater
          onRowSelectionChange(next)
        }
      : undefined,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    rowCount,
    ...(getRowId && { getRowId }),
  })

  return (
    <div className="flex flex-col gap-0">
      <div className="overflow-auto rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => {
                  const canSort = header.column.getCanSort()
                  const sorted = header.column.getIsSorted()
                  return (
                    <TableHead
                      key={header.id}
                      style={{
                        width:
                          header.column.getSize() !== 150 ? header.column.getSize() : undefined,
                      }}
                      className={cn(canSort && 'cursor-pointer select-none')}
                      onClick={
                        canSort
                          ? () => {
                              header.column.toggleSorting()
                            }
                          : undefined
                      }
                    >
                      {header.isPlaceholder ? null : (
                        <span className="flex items-center">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {canSort && <SortIcon sorted={sorted} />}
                        </span>
                      )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>

          <TableBody>
            {isLoading ? (
              <TableSkeletonRows count={10} colCount={allColumns.length} />
            ) : table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={allColumns.length}
                  className="text-muted-foreground h-32 text-center"
                >
                  No results found.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() ? 'selected' : undefined}
                  className={cn(onRowClick && 'cursor-pointer hover:bg-muted/50')}
                  onClick={
                    onRowClick
                      ? () => {
                          onRowClick(row.original)
                        }
                      : undefined
                  }
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
      </div>

      {pagination && onPaginationChange && (
        <DataTablePagination
          pageIndex={pagination.pageIndex}
          pageSize={pagination.pageSize}
          rowCount={rowCount}
          onPrev={() => {
            onPaginationChange({ ...pagination, pageIndex: pagination.pageIndex - 1 })
          }}
          onNext={() => {
            onPaginationChange({ ...pagination, pageIndex: pagination.pageIndex + 1 })
          }}
        />
      )}
    </div>
  )
}
