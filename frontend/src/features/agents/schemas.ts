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
  toolsJson: Record<string, unknown>[] | null
  createdAt: string
  updatedAt: string
  deletedAt: string | null
}

export interface AgentPromptResponse {
  agentId: string
  systemPrompt: string | null
}

export const PHONE_PROVIDERS = ['twilio', 'vonage', 'own'] as const
export type PhoneProvider = (typeof PHONE_PROVIDERS)[number]

export interface AgentPhoneNumberResponse {
  id: string
  agentId: string
  phoneNumber: string
  provider: string
  isActive: boolean
  createdAt: string
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

// ── Prompt editing ─────────────────────────────────────────────────────────────
export const updatePromptSchema = z.object({
  systemPrompt: z.string().min(1, 'System prompt is required'),
  welcomeMessage: z.string().max(1000).optional(),
})

export type UpdatePromptInput = z.infer<typeof updatePromptSchema>

// ── Phone number assignment ───────────────────────────────────────────────────
export const assignPhoneNumberSchema = z.object({
  phoneNumber: z.string().min(7).max(30),
  provider: z.enum(PHONE_PROVIDERS),
})

export type AssignPhoneNumberInput = z.infer<typeof assignPhoneNumberSchema>

// ── Tool definitions (flat form shape) ────────────────────────────────────────
export const EXECUTOR_TYPES = ['http_get', 'http_post', 'sql_query'] as const
export type ExecutorType = (typeof EXECUTOR_TYPES)[number]

export const PARAMETER_TYPES = ['string', 'number', 'boolean', 'integer'] as const

export const toolParameterSchema = z.object({
  name: z.string().min(1, 'Parameter name is required'),
  type: z.enum(PARAMETER_TYPES),
  description: z.string().optional(),
  required: z.boolean().default(false),
})

export const toolDefinitionSchema = z.object({
  name: z.string().min(1, 'Tool name is required'),
  description: z.string().optional(),
  executorType: z.enum(EXECUTOR_TYPES),
  url: z.string().optional(),
  sqlQuery: z.string().optional(),
  parameters: z.array(toolParameterSchema).default([]),
})

export const toolsFormSchema = z.object({
  tools: z.array(toolDefinitionSchema).default([]),
})

export type ToolParameterInput = z.infer<typeof toolParameterSchema>
export type ToolDefinitionInput = z.infer<typeof toolDefinitionSchema>
export type ToolsFormInput = z.infer<typeof toolsFormSchema>

// ── Mapping helpers: OpenAI tool JSON <-> flat form shape ─────────────────────
interface ToolJsonShape {
  type?: string
  function?: {
    name?: string
    description?: string
    parameters?: {
      type?: string
      properties?: Record<string, { type?: string; description?: string }>
      required?: string[]
    }
  }
  executor?: {
    type?: string
    url?: string
    method?: string
    headers?: Record<string, string>
    query?: string
  }
}

export function toolsToFormValues(toolsJson: Record<string, unknown>[] | null | undefined): ToolDefinitionInput[] {
  if (!toolsJson) return []
  return toolsJson.map((raw) => {
    const tool = raw as ToolJsonShape
    const props = tool.function?.parameters?.properties ?? {}
    const required = tool.function?.parameters?.required ?? []
    const parameters: ToolParameterInput[] = Object.entries(props).map(([name, def]) => ({
      name,
      type: (PARAMETER_TYPES as readonly string[]).includes(def.type ?? '')
        ? (def.type as ToolParameterInput['type'])
        : 'string',
      description: def.description ?? '',
      required: required.includes(name),
    }))
    const executorType = (EXECUTOR_TYPES as readonly string[]).includes(tool.executor?.type ?? '')
      ? (tool.executor?.type as ExecutorType)
      : 'http_get'
    return {
      name: tool.function?.name ?? '',
      description: tool.function?.description ?? '',
      executorType,
      url: tool.executor?.url ?? '',
      sqlQuery: tool.executor?.query ?? '',
      parameters,
    }
  })
}

export function formValuesToToolsJson(values: ToolsFormInput): Record<string, unknown>[] {
  return values.tools.map((tool) => {
    const properties: Record<string, { type: string; description?: string }> = {}
    const required: string[] = []
    for (const param of tool.parameters) {
      properties[param.name] = { type: param.type, description: param.description || undefined }
      if (param.required) required.push(param.name)
    }

    const executor: Record<string, unknown> = { type: tool.executorType }
    if (tool.executorType === 'sql_query') {
      executor.query = tool.sqlQuery || ''
    } else {
      executor.url = tool.url || ''
      executor.method = tool.executorType === 'http_post' ? 'POST' : 'GET'
    }

    return {
      type: 'function',
      function: {
        name: tool.name,
        description: tool.description || '',
        parameters: {
          type: 'object',
          properties,
          required,
        },
      },
      executor,
    }
  })
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
