import { useNavigate } from '@tanstack/react-router'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  MessageSquareIcon,
  MicIcon,
  BookOpenIcon,
  DatabaseIcon,
  CheckCircle2Icon,
} from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Textarea } from '@/shared/components/ui/textarea'
import { Switch } from '@/shared/components/ui/switch'
import { Slider } from '@/shared/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Card, CardContent } from '@/shared/components/ui/card'
import { cn } from '@/shared/lib/utils'

import { useCreateAgent } from '@/features/agents/hooks'
import {
  createAgentSchema,
  CREATE_AGENT_DEFAULTS,
  AGENT_TYPES,
  NOISE_LEVELS,
  type CreateAgentInput,
  type AgentType,
} from '@/features/agents/schemas'
import { agentNewRoute } from '@/app/router'

// ─── Step meta ────────────────────────────────────────────────────────────────
const STEPS = [
  { label: 'Basics', description: 'Name and type' },
  { label: 'AI Config', description: 'Model and params' },
  { label: 'Voice', description: 'TTS and VAD' },
  { label: 'Review', description: 'Confirm and create' },
] as const

const AGENT_TYPE_CONFIG: Record<
  AgentType,
  { icon: typeof MessageSquareIcon; label: string; description: string }
> = {
  conversational: {
    icon: MessageSquareIcon,
    label: 'Conversational',
    description: 'Two-way dialogue with LLM reasoning',
  },
  speaker_only: {
    icon: MicIcon,
    label: 'Speaker Only',
    description: 'Text-to-speech playback, no LLM',
  },
  rag_bot: {
    icon: BookOpenIcon,
    label: 'RAG Bot',
    description: 'Answers from a document knowledge base',
  },
  db_bot: {
    icon: DatabaseIcon,
    label: 'DB Bot',
    description: 'Queries structured database sources',
  },
}

const LLM_MODELS = [
  'qwen2.5:3b',
  'qwen2.5:7b',
  'qwen2.5:14b',
  'llama3.2:3b',
  'llama3.1:8b',
  'mistral:7b',
  'phi3:mini',
]

const TTS_VOICES = [
  { value: 'af_heart', label: 'Heart (EN-AF)' },
  { value: 'af_bella', label: 'Bella (EN-AF)' },
  { value: 'af_sarah', label: 'Sarah (EN-AF)' },
  { value: 'am_adam', label: 'Adam (EN-AM)' },
  { value: 'am_michael', label: 'Michael (EN-AM)' },
  { value: 'bf_emma', label: 'Emma (EN-BF)' },
  { value: 'bm_george', label: 'George (EN-BM)' },
]

// ─── Step Indicator ───────────────────────────────────────────────────────────
function StepIndicator({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-0">
      {STEPS.map((step, i) => {
        const num = i + 1
        const isActive = num === current
        const isDone = num < current
        return (
          <li key={num} className="flex items-center">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors',
                  isActive && 'border-primary bg-primary text-primary-foreground',
                  isDone && 'border-primary bg-primary/20 text-primary',
                  !isActive && !isDone && 'border-muted-foreground/30 text-muted-foreground',
                )}
              >
                {isDone ? <CheckCircle2Icon className="h-4 w-4" /> : num}
              </div>
              <span
                className={cn(
                  'mt-1 hidden text-xs sm:block',
                  isActive ? 'font-medium' : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={cn(
                  'mb-4 h-px w-8 sm:w-16',
                  num < current ? 'bg-primary/60' : 'bg-muted-foreground/20',
                )}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}

// ─── Step 1: Basics ───────────────────────────────────────────────────────────
function Step1Basics({ form }: { form: ReturnType<typeof useForm<CreateAgentInput>> }) {
  const {
    register,
    control,
    formState: { errors },
  } = form
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="name">
          Agent name <span className="text-destructive">*</span>
        </Label>
        <Input id="name" placeholder="e.g. Support Bot, Sales Assistant" {...register('name')} />
        {errors.name && <p className="text-destructive text-sm">{errors.name.message}</p>}
      </div>

      <div className="space-y-2">
        <Label>
          Agent type <span className="text-destructive">*</span>
        </Label>
        <Controller
          control={control}
          name="agentType"
          render={({ field }) => (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {AGENT_TYPES.map((type) => {
                const cfg = AGENT_TYPE_CONFIG[type]
                const Icon = cfg.icon
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => {
                      field.onChange(type)
                    }}
                    className={cn(
                      'flex items-start gap-3 rounded-lg border p-4 text-left transition-colors',
                      field.value === type
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-muted-foreground/50 hover:bg-muted/50',
                    )}
                  >
                    <Icon
                      className={cn(
                        'mt-0.5 h-5 w-5 shrink-0',
                        field.value === type ? 'text-primary' : 'text-muted-foreground',
                      )}
                    />
                    <div>
                      <p className="font-medium">{cfg.label}</p>
                      <p className="text-muted-foreground mt-0.5 text-xs">{cfg.description}</p>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Welcome message</Label>
        <Textarea
          id="description"
          placeholder="Hello! How can I help you today?"
          rows={3}
          {...register('description')}
        />
        <p className="text-muted-foreground text-xs">
          Optional greeting played at the start of every call.
        </p>
      </div>
    </div>
  )
}

// ─── Step 2: AI Config ────────────────────────────────────────────────────────
function Step2AIConfig({ form }: { form: ReturnType<typeof useForm<CreateAgentInput>> }) {
  const {
    register,
    control,
    watch,
    formState: { errors },
  } = form
  const temperature = watch('temperature')
  const maxTokens = watch('maxTokens')
  return (
    <div className="space-y-6">
      <Controller
        control={control}
        name="llmModel"
        render={({ field }) => (
          <div className="space-y-2">
            <Label>LLM model</Label>
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger>
                <SelectValue placeholder="Select a model" />
              </SelectTrigger>
              <SelectContent>
                {LLM_MODELS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.llmModel && (
              <p className="text-destructive text-sm">{errors.llmModel.message}</p>
            )}
          </div>
        )}
      />

      <Controller
        control={control}
        name="temperature"
        render={({ field }) => (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Temperature</Label>
              <span className="text-muted-foreground text-sm tabular-nums">
                {temperature.toFixed(1)}
              </span>
            </div>
            <Slider
              min={0}
              max={2}
              step={0.1}
              value={[field.value]}
              onValueChange={([v]) => {
                field.onChange(v)
              }}
            />
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Focused (0)</span>
              <span>Creative (2)</span>
            </div>
          </div>
        )}
      />

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="maxTokens">Max tokens</Label>
          <span className="text-muted-foreground text-sm tabular-nums">{maxTokens}</span>
        </div>
        <Input
          id="maxTokens"
          type="number"
          min={1}
          max={32768}
          {...register('maxTokens', { valueAsNumber: true })}
        />
        {errors.maxTokens && <p className="text-destructive text-sm">{errors.maxTokens.message}</p>}
      </div>

      <div className="space-y-2">
        <Label htmlFor="language">Language (STT)</Label>
        <Input
          id="language"
          placeholder="e.g. en, fr, de — leave blank for auto-detect"
          {...register('language')}
        />
      </div>
    </div>
  )
}

// ─── Step 3: Voice & VAD ─────────────────────────────────────────────────────
function Step3Voice({ form }: { form: ReturnType<typeof useForm<CreateAgentInput>> }) {
  const { control, watch } = form
  const ttsSpeed = watch('ttsSpeed')
  const vadThreshold = watch('vadThreshold')
  return (
    <div className="space-y-6">
      <Controller
        control={control}
        name="ttsVoice"
        render={({ field }) => (
          <div className="space-y-2">
            <Label>TTS voice</Label>
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TTS_VOICES.map((v) => (
                  <SelectItem key={v.value} value={v.value}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      />

      <Controller
        control={control}
        name="ttsSpeed"
        render={({ field }) => (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Speech speed</Label>
              <span className="text-muted-foreground text-sm tabular-nums">
                {ttsSpeed.toFixed(2)}×
              </span>
            </div>
            <Slider
              min={0.25}
              max={4}
              step={0.05}
              value={[field.value]}
              onValueChange={([v]) => {
                field.onChange(v)
              }}
            />
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>0.25× (slow)</span>
              <span>4× (fast)</span>
            </div>
          </div>
        )}
      />

      <Controller
        control={control}
        name="vadThreshold"
        render={({ field }) => (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>VAD sensitivity</Label>
              <span className="text-muted-foreground text-sm tabular-nums">
                {vadThreshold.toFixed(2)}
              </span>
            </div>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={[field.value]}
              onValueChange={([v]) => {
                field.onChange(v)
              }}
            />
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>Low (0)</span>
              <span>High (1)</span>
            </div>
          </div>
        )}
      />

      <Controller
        control={control}
        name="allowInterruptions"
        render={({ field }) => (
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div>
              <p className="font-medium">Allow interruptions</p>
              <p className="text-muted-foreground text-sm">
                Callers can interrupt the agent mid-speech.
              </p>
            </div>
            <Switch checked={field.value} onCheckedChange={field.onChange} />
          </div>
        )}
      />

      <Controller
        control={control}
        name="noiseRemovalLevel"
        render={({ field }) => (
          <div className="space-y-2">
            <Label>Noise removal</Label>
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NOISE_LEVELS.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l === 'none' ? 'None' : l === 'rnnoise' ? 'RNNoise' : 'DeepFilterNet'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      />
    </div>
  )
}

// ─── Step 4: Review & Create ──────────────────────────────────────────────────
function Step4Review({ form }: { form: ReturnType<typeof useForm<CreateAgentInput>> }) {
  const {
    register,
    watch,
    formState: { errors },
  } = form
  const values = watch()
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card>
          <CardContent className="pt-4 space-y-1">
            <p className="text-muted-foreground text-xs uppercase tracking-wide">Basics</p>
            <p className="font-medium">{values.name || '—'}</p>
            <p className="text-muted-foreground text-sm capitalize">
              {values.agentType.replace(/_/g, ' ')}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 space-y-1">
            <p className="text-muted-foreground text-xs uppercase tracking-wide">AI Model</p>
            <p className="font-medium font-mono">{values.llmModel}</p>
            <p className="text-muted-foreground text-sm">
              temp {values.temperature} · {values.maxTokens} tokens
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 space-y-1">
            <p className="text-muted-foreground text-xs uppercase tracking-wide">Voice</p>
            <p className="font-medium">{values.ttsVoice}</p>
            <p className="text-muted-foreground text-sm">
              speed {values.ttsSpeed}× · VAD {values.vadThreshold}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 space-y-1">
            <p className="text-muted-foreground text-xs uppercase tracking-wide">Behaviour</p>
            <p className="font-medium">
              {values.allowInterruptions ? 'Interruptions on' : 'No interruptions'}
            </p>
            <p className="text-muted-foreground text-sm">Noise: {values.noiseRemovalLevel}</p>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-2">
        <Label htmlFor="systemPrompt">System prompt</Label>
        <Textarea
          id="systemPrompt"
          placeholder="You are a helpful assistant…"
          rows={5}
          {...register('systemPrompt')}
        />
        {errors.systemPrompt && (
          <p className="text-destructive text-sm">{errors.systemPrompt.message}</p>
        )}
      </div>
    </div>
  )
}

// ─── Main wizard page ─────────────────────────────────────────────────────────
export function AgentNewPage() {
  const navigate = useNavigate()
  const { step } = agentNewRoute.useSearch()
  const current = Math.min(Math.max(step, 1), 4)

  const form = useForm<CreateAgentInput>({
    resolver: zodResolver(createAgentSchema),
    defaultValues: CREATE_AGENT_DEFAULTS,
    mode: 'onTouched',
  })

  const createAgent = useCreateAgent()

  function goTo(s: number) {
    void navigate({
      to: '/agents/new',
      search: (prev) => ({ ...prev, step: s }),
    })
  }

  function handleNextStep() {
    const fieldsPerStep: (keyof CreateAgentInput)[][] = [
      ['name', 'agentType'],
      ['llmModel', 'temperature', 'maxTokens'],
      ['ttsVoice', 'ttsSpeed', 'vadThreshold', 'allowInterruptions', 'noiseRemovalLevel'],
      ['systemPrompt'],
    ]
    void form.trigger(fieldsPerStep[current - 1]).then((ok) => {
      if (ok) goTo(current + 1)
    })
  }

  function handleSubmit(values: CreateAgentInput) {
    createAgent.mutate(values, {
      onSuccess: (agent) => {
        void navigate({ to: '/agents/$agentId', params: { agentId: agent.id } })
      },
    })
  }

  return (
    <PageContainer>
      <PageHeader title="New Agent" description="Configure your AI voice agent step by step." />

      <div className="mx-auto max-w-2xl space-y-8">
        <StepIndicator current={current} />

        <div>
          <h2 className="text-lg font-semibold">{STEPS[current - 1].label}</h2>
          <p className="text-muted-foreground text-sm">{STEPS[current - 1].description}</p>
        </div>

        <form
          onSubmit={(e) => {
            void form.handleSubmit(handleSubmit)(e)
          }}
          className="space-y-6"
        >
          {current === 1 && <Step1Basics form={form} />}
          {current === 2 && <Step2AIConfig form={form} />}
          {current === 3 && <Step3Voice form={form} />}
          {current === 4 && <Step4Review form={form} />}

          {/* Nav buttons */}
          <div className="flex items-center justify-between pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (current === 1) {
                  void navigate({ to: '/agents' })
                } else {
                  goTo(current - 1)
                }
              }}
            >
              {current === 1 ? 'Cancel' : 'Back'}
            </Button>

            {current < 4 ? (
              <Button type="button" onClick={handleNextStep}>
                Next
              </Button>
            ) : (
              <Button type="submit" disabled={createAgent.isPending}>
                {createAgent.isPending ? 'Creating…' : 'Create Agent'}
              </Button>
            )}
          </div>
        </form>
      </div>
    </PageContainer>
  )
}
