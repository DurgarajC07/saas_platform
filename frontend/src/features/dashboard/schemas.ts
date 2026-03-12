/**
 * Dashboard — TypeScript interfaces for all API responses.
 * No Zod schemas needed here (read-only data, not form input).
 */

// ── Overview / Stat Cards ─────────────────────────────────────────────────────
export interface DashboardOverview {
  activeCalls: number
  callsToday: number
  agentsLive: number
  avgLatencyMs: number
  deltaActiveCalls: number | null // % change vs previous period
  deltaCallsToday: number | null
  deltaAgentsLive: number | null
  deltaAvgLatency: number | null
}

// ── Call Volume ───────────────────────────────────────────────────────────────
export interface CallVolumeDailyPoint {
  date: string // "YYYY-MM-DD"
  completed: number
  failed: number
  total: number
}

export interface CallVolumeResponse {
  daily: CallVolumeDailyPoint[]
  totalCompleted: number
  totalFailed: number
  periodLabel: string
}

// ── Agent Performance ─────────────────────────────────────────────────────────
export interface AgentPerfRow {
  agentId: string
  agentName: string
  callsToday: number
  avgDurationSec: number
  successRate: number // 0-100
  isLive: boolean
}

// ── Analytics ─────────────────────────────────────────────────────────────────
export interface LatencyPoint {
  timestamp: string // ISO or "HH:mm"
  p50: number // ms
  p95: number
  p99: number
}

export interface BreakdownPoint {
  component: 'STT' | 'LLM' | 'TTS'
  avgMs: number
  p95Ms: number
}

export interface AnalyticsResponse {
  latency: LatencyPoint[]
  breakdown: BreakdownPoint[]
  successRate: number // 0-100
  failureRate: number
  totalCalls: number
  fromDate: string
  toDate: string
}

// ── Live Calls (SSE + REST) ───────────────────────────────────────────────────
export interface LiveCall {
  id: string
  agentId: string
  agentName: string
  callerNumber: string
  startedAt: string // ISO
  durationSec: number
  status: 'active' | 'ringing' | 'on_hold'
  direction: 'inbound' | 'outbound'
}

export interface LiveCallsSnapshot {
  calls: LiveCall[]
  total: number
}

// ── Date-range picker shape ───────────────────────────────────────────────────
export interface DateRange {
  from: string // "YYYY-MM-DD"
  to: string
}
