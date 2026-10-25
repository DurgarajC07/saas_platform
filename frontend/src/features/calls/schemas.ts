// ── Constants that mirror backend frozensets ──────────────────────────────────
export const CALL_STATUSES = ['connected', 'completed', 'failed', 'no-answer'] as const
export const CALL_DIRECTIONS = ['inbound', 'outbound'] as const

export type CallStatus = (typeof CALL_STATUSES)[number]
export type CallDirection = (typeof CALL_DIRECTIONS)[number]

// ── Response interfaces ───────────────────────────────────────────────────────
export interface CallLogResponse {
  id: string
  agentId: string
  orgId: string
  sessionId: string | null
  callerId: string | null
  direction: CallDirection
  transport: 'webrtc' | 'websocket' | 'twilio'
  status: CallStatus
  startedAt: string | null
  endedAt: string | null
  durationSec: number | null
  transcript: string | null
  recordingUrl: string | null
  costCredits: number | null
  sttMs: number | null
  llmTtftMs: number | null
  ttsTtfbMs: number | null
  metadata: Record<string, unknown>
  createdAt: string
}

export interface PaginationMeta {
  page: number
  pageSize: number
  totalItems: number
  totalPages: number
  hasNext: boolean
  hasPrevious: boolean
}

export interface CallLogListResponse {
  calls: CallLogResponse[]
  pagination: PaginationMeta
}

export interface RecordingUrlResponse {
  url: string
  expiresAt: string
}

export interface LatencyStats {
  avgMs: number | null
  p50Ms: number | null
  p95Ms: number | null
  minMs: number | null
  maxMs: number | null
}

export interface AgentAnalyticsResponse {
  agentId: string
  periodDays: number
  totalCalls: number
  completedCalls: number
  failedCalls: number
  successRatePct: number | null
  avgDurationSec: number | null
  totalDurationSec: number
  sttLatency: LatencyStats
  llmLatency: LatencyStats
  ttsLatency: LatencyStats
  inboundCalls: number
  outboundCalls: number
}
