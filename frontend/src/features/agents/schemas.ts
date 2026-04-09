import { z } from 'zod'

// ── Constants that mirror backend frozensets ──────────────────────────────────
export const AGENT_TYPES = ['speaker_only', 'conversational', 'rag_bot', 'db_bot'] as const
export const AGENT_STATUSES = ['draft', 'active', 'paused', 'archived'] as const
export const NOISE_LEVELS = ['none', 'rnnoise', 'deepfilternet'] as const

export type AgentType = (typeof AGENT_TYPES)[number]
export type AgentStatus = (typeof AGENT_STATUSES)[number]

// ── Response interfaces ───────────────────────────────────────────────────────
export interface AgentResponse {
  id: string
  orgId: string
  createdBy: string | null
  name: string
  slug: string
  agentType: AgentType
  status: AgentStatus
  llmModel: string
  temperature: number
  maxTokens: number
  language: string | null
  ttsVoice: string
  ttsSpeed: number
  vadThreshold: number
  minSpeechMs: number
  silenceMs: number
  allowInterruptions: boolean
  noiseRemovalLevel: string
  qdrantCollection: string | null
  ragTopK: number
  welcomeMessage: string | null
  maxCallDurationSec: number
  recordCalls: boolean
  metadata: Record<string, unknown>
  createdAt: string
  updatedAt: string
  deletedAt: string | null
}

export interface AgentListResponse {
  agents: AgentResponse[]
  pagination: {
    page: number
    pageSize: number
    total: number
    pages: number
  }
}

// ── Step 1: Basics ────────────────────────────────────────────────────────────
export const step1Schema = z.object({
  name: z.string().min(1, 'Name is required').max(255),
  agentType: z.enum(AGENT_TYPES),
  description: z.string().max(1000).optional(),
})

// ── Step 2: AI Config ─────────────────────────────────────────────────────────
export const step2Schema = z.object({
  llmModel: z.string().min(1, 'Model is required').max(100),
  temperature: z.number().min(0).max(2),
  maxTokens: z.number().int().min(1).max(32768),
  language: z.string().max(10).optional(),
})

// ── Step 3: Voice & Behaviour ─────────────────────────────────────────────────
export const step3Schema = z.object({
  ttsVoice: z.string().min(1).max(100),
  ttsSpeed: z.number().min(0.25).max(4),
  vadThreshold: z.number().min(0).max(1),
  allowInterruptions: z.boolean(),
  noiseRemovalLevel: z.enum(NOISE_LEVELS),
})

// ── Step 4: Review & Create ───────────────────────────────────────────────────
export const step4Schema = z.object({
  systemPrompt: z.string().optional(),
  welcomeMessage: z.string().max(1000).optional(),
})

// ── Full wizard schema (merged) ───────────────────────────────────────────────
export const createAgentSchema = step1Schema
  .merge(step2Schema)
  .merge(step3Schema)
  .merge(step4Schema)

export type CreateAgentInput = z.infer<typeof createAgentSchema>

// ── Defaults ──────────────────────────────────────────────────────────────────
export const CREATE_AGENT_DEFAULTS: CreateAgentInput = {
  name: '',
  agentType: 'conversational',
  description: '',
  llmModel: 'qwen2.5:3b',
  temperature: 0.7,
  maxTokens: 512,
  language: '',
  ttsVoice: 'af_heart',
  ttsSpeed: 1.0,
  vadThreshold: 0.5,
  allowInterruptions: true,
  noiseRemovalLevel: 'none',
  systemPrompt: '',
  welcomeMessage: '',
}

// ── URL filter schema ─────────────────────────────────────────────────────────
export const agentListSearchSchema = z.object({
  status: z
    .enum([...AGENT_STATUSES, '' as const])
    .optional()
    .default(''),
  type: z
    .enum([...AGENT_TYPES, '' as const])
    .optional()
    .default(''),
  search: z.string().optional().default(''),
  page: z.number().int().positive().optional().default(1),
})

export type AgentListSearch = z.infer<typeof agentListSearchSchema>
