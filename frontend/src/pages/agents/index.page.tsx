import { useState, useCallback } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { type ColumnDef, type SortingState, type RowSelectionState } from '@tanstack/react-table'
import {
  PlusIcon,
  BotIcon,
  SearchIcon,
  RotateCcwIcon,
  Trash2Icon,
  PauseIcon,
  PlayIcon,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/components/ui/alert-dialog'
import { DataTable } from '@/shared/components/data-display/DataTable'
import {
  AgentTypeBadge,
  AgentStatusBadge,
  AGENT_TYPE_LABELS,
  AGENT_STATUS_LABELS,
} from '@/shared/components/data-display/AgentBadges'
import { useAgents, useBulkUpdateAgents, useBulkDeleteAgents } from '@/features/agents/hooks'
import { AGENT_TYPES, AGENT_STATUSES, type AgentResponse } from '@/features/agents/schemas'
import { agentListRoute } from '@/app/router'

// ─── Columns ──────────────────────────────────────────────────────────────────
const columns: ColumnDef<AgentResponse>[] = [
  {
    accessorKey: 'name',
    header: 'Name',
    cell: ({ row }) => (
      <div>
        <p className="font-medium">{row.original.name}</p>
        <p className="text-muted-foreground text-xs">{row.original.slug}</p>
      </div>
    ),
  },
  {
    accessorKey: 'agentType',
    header: 'Type',
    enableSorting: false,
    cell: ({ row }) => <AgentTypeBadge type={row.original.agentType} />,
  },
  {
    accessorKey: 'status',
    header: 'Status',
    enableSorting: false,
    cell: ({ row }) => <AgentStatusBadge status={row.original.status} />,
  },
  {
    accessorKey: 'llmModel',
    header: 'Model',
    cell: ({ row }) => (
      <span className="text-muted-foreground font-mono text-sm">{row.original.llmModel}</span>
    ),
  },
  {
    accessorKey: 'createdAt',
    header: 'Created',
    cell: ({ row }) => (
      <span className="text-muted-foreground text-sm">
        {formatDistanceToNow(new Date(row.original.createdAt), { addSuffix: true })}
      </span>
    ),
  },
]

// ─── Page ─────────────────────────────────────────────────────────────────────
export function AgentListPage() {
  const navigate = useNavigate()
  const search = agentListRoute.useSearch()

  const [sorting, setSorting] = useState<SortingState>([])
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const page = search.page
  const pageSize = 20

  const { data, isLoading } = useAgents({
    page,
    pageSize,
    status: search.status || undefined,
    type: search.type || undefined,
    search: search.search || undefined,
  })

  const bulkUpdate = useBulkUpdateAgents()
  const bulkDelete = useBulkDeleteAgents()

  const agents = data?.agents ?? []
  const rowCount = data?.pagination.total ?? 0

  const selectedIds = Object.keys(rowSelection).filter((k) => rowSelection[k])

  // ── URL helpers ──────────────────────────────────────────────────────────
  const setSearch = useCallback(
    (patch: Partial<typeof search>) => {
      void navigate({
        to: '/agents',
        search: (prev) => ({ ...prev, ...patch, page: patch.page ?? 1 }),
      })
    },
    [navigate],
  )

  function handleRowClick(agent: AgentResponse) {
    void navigate({ to: '/agents/$agentId', params: { agentId: agent.id } })
  }

  function handleBulkPause() {
    bulkUpdate.mutate(
      { ids: selectedIds, status: 'paused' },
      {
        onSuccess: () => {
          setRowSelection({})
        },
      },
    )
  }

  function handleBulkActivate() {
    bulkUpdate.mutate(
      { ids: selectedIds, status: 'active' },
      {
        onSuccess: () => {
          setRowSelection({})
        },
      },
    )
  }

  function handleBulkDelete() {
    bulkDelete.mutate(selectedIds, {
      onSuccess: () => {
        setRowSelection({})
        setBulkDeleteOpen(false)
      },
    })
  }

  const isEmpty =
    !isLoading && agents.length === 0 && !search.search && !search.status && !search.type

  return (
    <PageContainer>
      <PageHeader
        title="Agents"
        description="Create and manage your AI voice agents."
        actions={
          <Button
            onClick={() => {
              void navigate({ to: '/agents/new' })
            }}
          >
            <PlusIcon className="mr-2 h-4 w-4" />
            New Agent
          </Button>
        }
      />

      {isEmpty ? (
        <EmptyState
          onNew={() => {
            void navigate({ to: '/agents/new' })
          }}
        />
      ) : (
        <div className="space-y-4">
          {/* Toolbar */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1">
              <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
              <Input
                placeholder="Search agents…"
                value={search.search}
                onChange={(e) => {
                  setSearch({ search: e.target.value })
                }}
                className="pl-9"
              />
            </div>

            <Select
              value={search.status}
              onValueChange={(v) => {
                setSearch({ status: v })
              }}
            >
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All statuses</SelectItem>
                {AGENT_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {AGENT_STATUS_LABELS[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={search.type}
              onValueChange={(v) => {
                setSearch({ type: v })
              }}
            >
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All types</SelectItem>
                {AGENT_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {AGENT_TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {(search.status || search.type || search.search) && (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Clear filters"
                onClick={() => {
                  setSearch({ status: '', type: '', search: '', page: 1 })
                }}
              >
                <RotateCcwIcon className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Bulk-action bar */}
          {selectedIds.length > 0 && (
            <div className="bg-muted flex items-center gap-2 rounded-md px-4 py-2">
              <span className="text-sm font-medium">{selectedIds.length} selected</span>
              <div className="flex-1" />
              <Button
                variant="outline"
                size="sm"
                onClick={handleBulkActivate}
                disabled={bulkUpdate.isPending}
              >
                <PlayIcon className="mr-1 h-3.5 w-3.5" />
                Activate
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleBulkPause}
                disabled={bulkUpdate.isPending}
              >
                <PauseIcon className="mr-1 h-3.5 w-3.5" />
                Pause
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setBulkDeleteOpen(true)
                }}
              >
                <Trash2Icon className="mr-1 h-3.5 w-3.5" />
                Delete
              </Button>
            </div>
          )}

          {/* Table */}
          <DataTable<AgentResponse>
            columns={columns}
            data={agents}
            isLoading={isLoading}
            onRowClick={handleRowClick}
            sorting={sorting}
            onSortingChange={setSorting}
            pagination={{ pageIndex: page - 1, pageSize }}
            onPaginationChange={(p) => {
              setSearch({ page: p.pageIndex + 1 })
            }}
            rowCount={rowCount}
            rowSelection={rowSelection}
            onRowSelectionChange={setRowSelection}
            enableRowSelection
            getRowId={(r) => r.id}
          />
        </div>
      )}

      {/* Bulk-delete confirmation */}
      <AlertDialog open={bulkDeleteOpen} onOpenChange={setBulkDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedIds.length} agents?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. All configuration for the selected agents will be
              permanently removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleBulkDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────
function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24">
      <BotIcon className="text-muted-foreground h-16 w-16" />
      <div className="text-center">
        <h2 className="text-lg font-semibold">No agents yet</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          Create your first AI voice agent to get started.
        </p>
      </div>
      <Button onClick={onNew}>
        <PlusIcon className="mr-2 h-4 w-4" />
        Create your first agent
      </Button>
    </div>
  )
}
