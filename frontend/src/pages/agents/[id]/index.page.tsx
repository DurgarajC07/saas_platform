import { useState } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import {
  PencilIcon,
  PhoneCallIcon,
  Trash2Icon,
  PlayIcon,
  PauseIcon,
  MessageSquareTextIcon,
  BookOpenIcon,
  WrenchIcon,
  PhoneIcon,
  HistoryIcon,
  BarChart3Icon,
} from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { ConfirmDialog } from '@/shared/components/feedback/ConfirmDialog'
import { AgentTypeBadge, AgentStatusBadge } from '@/shared/components/data-display/AgentBadges'
import { useAgent, useDeleteAgent, useSetAgentStatus } from '@/features/agents/hooks'
import { getErrorMessage } from '@/shared/api/error-handler'

const SUB_PAGES = [
  { to: '/agents/$agentId/prompt' as const, label: 'Prompt', icon: MessageSquareTextIcon },
  { to: '/agents/$agentId/knowledge-base' as const, label: 'Knowledge Base', icon: BookOpenIcon },
  { to: '/agents/$agentId/tools' as const, label: 'Tools', icon: WrenchIcon },
  { to: '/agents/$agentId/phone-numbers' as const, label: 'Phone Numbers', icon: PhoneIcon },
  { to: '/agents/$agentId/calls' as const, label: 'Calls', icon: HistoryIcon },
  { to: '/agents/$agentId/analytics' as const, label: 'Analytics', icon: BarChart3Icon },
]

export function AgentDetailPage() {
  const { agentId } = useParams({ from: '/agents/$agentId' })
  const navigate = useNavigate()
  const { data: agent, isLoading, isError, error } = useAgent(agentId)
  const deleteAgent = useDeleteAgent()
  const setStatus = useSetAgentStatus()
  const [deleteOpen, setDeleteOpen] = useState(false)

  function handleDelete() {
    deleteAgent.mutate(agentId, {
      onSuccess: () => {
        setDeleteOpen(false)
        void navigate({ to: '/agents' })
      },
    })
  }

  function handleToggleStatus() {
    if (!agent) return
    setStatus.mutate({ id: agentId, status: agent.status === 'active' ? 'paused' : 'active' })
  }

  if (isLoading) {
    return (
      <PageContainer>
        <PageHeader title="Agent Detail" description="View agent configuration and performance." />
        <div className="space-y-4">
          <Skeleton className="h-10 w-1/3" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-28 w-full rounded-xl" />
            ))}
          </div>
        </div>
      </PageContainer>
    )
  }

  if (isError || !agent) {
    return (
      <PageContainer>
        <PageHeader title="Agent Detail" description="View agent configuration and performance." />
        <p className="text-destructive text-sm">
          {error ? getErrorMessage(error) : 'Agent not found.'}
        </p>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader
        title={agent.name}
        description="View agent configuration and performance."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => {
                void navigate({ to: '/agents/$agentId/edit', params: { agentId } })
              }}
            >
              <PencilIcon className="mr-2 h-4 w-4" />
              Edit
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                void navigate({ to: '/agents/$agentId/test-call', params: { agentId } })
              }}
            >
              <PhoneCallIcon className="mr-2 h-4 w-4" />
              Test Call
            </Button>
            <Button variant="outline" onClick={handleToggleStatus} disabled={setStatus.isPending}>
              {agent.status === 'active' ? (
                <>
                  <PauseIcon className="mr-2 h-4 w-4" />
                  Pause
                </>
              ) : (
                <>
                  <PlayIcon className="mr-2 h-4 w-4" />
                  Activate
                </>
              )}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setDeleteOpen(true)
              }}
            >
              <Trash2Icon className="mr-2 h-4 w-4" />
              Delete
            </Button>
          </div>
        }
      />

      <div className="flex items-center gap-2">
        <AgentTypeBadge type={agent.agentType} />
        <AgentStatusBadge status={agent.status} />
        <span className="text-muted-foreground text-sm">/{agent.slug}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">AI Model</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="font-mono text-sm">{agent.llmModel}</p>
            <p className="text-muted-foreground text-sm">
              temp {agent.temperature} · {agent.maxTokens} tokens
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Language</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{agent.language || 'Auto-detect'}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Voice</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="text-sm">{agent.ttsVoice}</p>
            <p className="text-muted-foreground text-sm">speed {agent.ttsSpeed}×</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">VAD</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="text-sm">threshold {agent.vadThreshold}</p>
            <p className="text-muted-foreground text-sm">noise: {agent.noiseRemovalLevel}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Behaviour</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="text-sm">
              {agent.allowInterruptions ? 'Interruptions allowed' : 'No interruptions'}
            </p>
            <p className="text-muted-foreground text-sm">
              Max call: {Math.round(agent.maxCallDurationSec / 60)} min
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Recording</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{agent.recordCalls ? 'Calls are recorded' : 'Not recorded'}</p>
          </CardContent>
        </Card>

        <Card className="sm:col-span-2 lg:col-span-3">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Welcome message
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{agent.welcomeMessage || 'No welcome message set.'}</p>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Configure</h2>
        <div className="flex flex-wrap gap-2">
          {SUB_PAGES.map(({ to, label, icon: Icon }) => (
            <Button
              key={to}
              variant="outline"
              size="sm"
              onClick={() => {
                void navigate({ to, params: { agentId } })
              }}
            >
              <Icon className="mr-2 h-3.5 w-3.5" />
              {label}
            </Button>
          ))}
        </div>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={handleDelete}
        title="Delete this agent?"
        description="This action cannot be undone. All configuration for this agent will be permanently removed."
        confirmLabel="Delete"
        variant="destructive"
        loading={deleteAgent.isPending}
      />
    </PageContainer>
  )
}
