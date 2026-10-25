import { useEffect } from 'react'
import { useNavigate, useParams } from '@tanstack/react-router'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'

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
import { Skeleton } from '@/shared/components/ui/skeleton'

import { useAgent, useUpdateAgent } from '@/features/agents/hooks'
import {
  createAgentSchema,
  NOISE_LEVELS,
  type CreateAgentInput,
} from '@/features/agents/schemas'

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

export function AgentEditPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/edit' })
  const navigate = useNavigate()
  const { data: agent, isLoading } = useAgent(agentId)
  const updateAgent = useUpdateAgent(agentId)

  const form = useForm<CreateAgentInput>({
    resolver: zodResolver(createAgentSchema),
    mode: 'onTouched',
  })
  const {
    register,
    control,
    watch,
    reset,
    formState: { errors },
  } = form

  useEffect(() => {
    if (!agent) return
    reset({
      name: agent.name,
      agentType: agent.agentType,
      description: agent.welcomeMessage ?? '',
      llmModel: agent.llmModel,
      temperature: agent.temperature,
      maxTokens: agent.maxTokens,
      language: agent.language ?? '',
      ttsVoice: agent.ttsVoice,
      ttsSpeed: agent.ttsSpeed,
      vadThreshold: agent.vadThreshold,
      allowInterruptions: agent.allowInterruptions,
      noiseRemovalLevel: agent.noiseRemovalLevel as CreateAgentInput['noiseRemovalLevel'],
      systemPrompt: '',
      welcomeMessage: agent.welcomeMessage ?? '',
    })
  }, [agent, reset])

  const temperature = watch('temperature')
  const maxTokens = watch('maxTokens')
  const ttsSpeed = watch('ttsSpeed')
  const vadThreshold = watch('vadThreshold')

  function handleSubmit(values: CreateAgentInput) {
    updateAgent.mutate(
      {
        name: values.name,
        llmModel: values.llmModel,
        temperature: values.temperature,
        maxTokens: values.maxTokens,
        language: values.language,
        ttsVoice: values.ttsVoice,
        ttsSpeed: values.ttsSpeed,
        vadThreshold: values.vadThreshold,
        allowInterruptions: values.allowInterruptions,
        noiseRemovalLevel: values.noiseRemovalLevel,
        welcomeMessage: values.welcomeMessage,
      },
      {
        onSuccess: () => {
          void navigate({ to: '/agents/$agentId', params: { agentId } })
        },
      },
    )
  }

  if (isLoading || !agent) {
    return (
      <PageContainer>
        <PageHeader title="Edit Agent" description="Update agent settings." />
        <div className="mx-auto max-w-2xl space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader title="Edit Agent" description="Update agent settings." />

      <form
        onSubmit={(e) => {
          void form.handleSubmit(handleSubmit)(e)
        }}
        className="mx-auto max-w-2xl space-y-10"
      >
        {/* ── Basics ─────────────────────────────────────────────── */}
        <section className="space-y-6">
          <h2 className="text-lg font-semibold">Basics</h2>

          <div className="space-y-2">
            <Label htmlFor="name">
              Agent name <span className="text-destructive">*</span>
            </Label>
            <Input id="name" {...register('name')} />
            {errors.name && <p className="text-destructive text-sm">{errors.name.message}</p>}
          </div>

          <div className="space-y-2">
            <Label>Agent type</Label>
            <Input value={agent.agentType.replace(/_/g, ' ')} disabled className="capitalize" />
            <p className="text-muted-foreground text-xs">
              Agent type cannot be changed after creation.
            </p>
          </div>
        </section>

        {/* ── AI Config ──────────────────────────────────────────── */}
        <section className="space-y-6">
          <h2 className="text-lg font-semibold">AI Config</h2>

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
                    {temperature?.toFixed(1)}
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
            {errors.maxTokens && (
              <p className="text-destructive text-sm">{errors.maxTokens.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="language">Language (STT)</Label>
            <Input
              id="language"
              placeholder="e.g. en, fr, de — leave blank for auto-detect"
              {...register('language')}
            />
          </div>
        </section>

        {/* ── Voice & Behaviour ──────────────────────────────────── */}
        <section className="space-y-6">
          <h2 className="text-lg font-semibold">Voice & Behaviour</h2>

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
                    {ttsSpeed?.toFixed(2)}×
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
                    {vadThreshold?.toFixed(2)}
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
        </section>

        {/* ── Prompt ─────────────────────────────────────────────── */}
        <section className="space-y-6">
          <h2 className="text-lg font-semibold">Prompt</h2>

          <div className="space-y-2">
            <Label htmlFor="welcomeMessage">Welcome message</Label>
            <Textarea id="welcomeMessage" rows={3} {...register('welcomeMessage')} />
          </div>
        </section>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void navigate({ to: '/agents/$agentId', params: { agentId } })
            }}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={updateAgent.isPending}>
            {updateAgent.isPending ? 'Saving…' : 'Save Changes'}
          </Button>
        </div>
      </form>
    </PageContainer>
  )
}
