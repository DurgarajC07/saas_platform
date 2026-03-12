import { Badge } from '@/shared/components/ui/badge'
import {
  MessageSquareIcon,
  MicIcon,
  DatabaseIcon,
  BookOpenIcon,
  CircleDotIcon,
  CircleIcon,
  PauseCircleIcon,
  ArchiveIcon,
} from 'lucide-react'
import type { AgentType, AgentStatus } from '@/features/agents/schemas'

// ─── Labels ───────────────────────────────────────────────────────────────────
export const AGENT_TYPE_LABELS: Record<AgentType, string> = {
  conversational: 'Conversational',
  speaker_only: 'Speaker Only',
  rag_bot: 'RAG Bot',
  db_bot: 'DB Bot',
}

export const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  paused: 'Paused',
  archived: 'Archived',
}

// ─── AgentTypeIcon ────────────────────────────────────────────────────────────
interface AgentTypeIconProps {
  type: AgentType
  className?: string
}

export function AgentTypeIcon({ type, className }: AgentTypeIconProps) {
  switch (type) {
    case 'conversational':
      return <MessageSquareIcon className={className} />
    case 'speaker_only':
      return <MicIcon className={className} />
    case 'rag_bot':
      return <BookOpenIcon className={className} />
    case 'db_bot':
      return <DatabaseIcon className={className} />
  }
}

// ─── AgentTypeBadge ───────────────────────────────────────────────────────────
interface AgentTypeBadgeProps {
  type: AgentType
}

const TYPE_VARIANT: Record<AgentType, 'default' | 'secondary' | 'outline'> = {
  conversational: 'default',
  speaker_only: 'secondary',
  rag_bot: 'outline',
  db_bot: 'outline',
}

export function AgentTypeBadge({ type }: AgentTypeBadgeProps) {
  return (
    <Badge variant={TYPE_VARIANT[type]} className="gap-1 font-normal">
      <AgentTypeIcon type={type} className="h-3 w-3" />
      {AGENT_TYPE_LABELS[type]}
    </Badge>
  )
}

// ─── AgentStatusBadge ─────────────────────────────────────────────────────────
interface AgentStatusBadgeProps {
  status: AgentStatus
}

type BadgeVariant = 'default' | 'secondary' | 'outline' | 'destructive'

const STATUS_VARIANT: Record<AgentStatus, BadgeVariant> = {
  active: 'default',
  draft: 'secondary',
  paused: 'outline',
  archived: 'destructive',
}

const STATUS_ICON: Record<AgentStatus, typeof CircleDotIcon> = {
  active: CircleDotIcon,
  draft: CircleIcon,
  paused: PauseCircleIcon,
  archived: ArchiveIcon,
}

export function AgentStatusBadge({ status }: AgentStatusBadgeProps) {
  const Icon = STATUS_ICON[status]
  return (
    <Badge variant={STATUS_VARIANT[status]} className="gap-1 font-normal">
      <Icon className="h-3 w-3" />
      {AGENT_STATUS_LABELS[status]}
    </Badge>
  )
}
