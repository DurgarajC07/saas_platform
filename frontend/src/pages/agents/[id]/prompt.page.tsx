import { useEffect } from 'react'
import { useParams } from '@tanstack/react-router'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Label } from '@/shared/components/ui/label'
import { Textarea } from '@/shared/components/ui/textarea'
import { Skeleton } from '@/shared/components/ui/skeleton'

import { useAgent, usePrompt, useUpdateAgent, useUpdatePrompt } from '@/features/agents/hooks'
import { updatePromptSchema, type UpdatePromptInput } from '@/features/agents/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'

export function AgentPromptPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/prompt' })
  const { data: agent } = useAgent(agentId)
  const { data: prompt, isLoading, isError, error } = usePrompt(agentId)
  const updatePrompt = useUpdatePrompt(agentId)
  const updateAgent = useUpdateAgent(agentId)

  const form = useForm<UpdatePromptInput>({
    resolver: zodResolver(updatePromptSchema),
    defaultValues: { systemPrompt: '', welcomeMessage: '' },
    mode: 'onTouched',
  })
  const {
    register,
    reset,
    formState: { errors },
  } = form

  useEffect(() => {
    if (prompt === undefined && agent === undefined) return
    reset({
      systemPrompt: prompt?.systemPrompt ?? '',
      welcomeMessage: agent?.welcomeMessage ?? '',
    })
  }, [prompt, agent, reset])

  function handleSubmit(values: UpdatePromptInput) {
    updatePrompt.mutate(values.systemPrompt)
    if (values.welcomeMessage !== (agent?.welcomeMessage ?? '')) {
      updateAgent.mutate({ welcomeMessage: values.welcomeMessage })
    }
  }

  if (isLoading) {
    return (
      <PageContainer>
        <PageHeader title="System Prompt" description="Configure the agent system prompt." />
        <div className="mx-auto max-w-2xl space-y-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </PageContainer>
    )
  }

  if (isError) {
    return (
      <PageContainer>
        <PageHeader title="System Prompt" description="Configure the agent system prompt." />
        <p className="text-destructive text-sm">{getErrorMessage(error)}</p>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader title="System Prompt" description="Configure the agent system prompt." />

      <form
        onSubmit={(e) => {
          void form.handleSubmit(handleSubmit)(e)
        }}
        className="mx-auto max-w-2xl space-y-6"
      >
        <div className="space-y-2">
          <Label htmlFor="systemPrompt">
            System prompt <span className="text-destructive">*</span>
          </Label>
          <Textarea
            id="systemPrompt"
            rows={10}
            placeholder="You are a helpful assistant…"
            {...register('systemPrompt')}
          />
          {errors.systemPrompt && (
            <p className="text-destructive text-sm">{errors.systemPrompt.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="welcomeMessage">Welcome message</Label>
          <Textarea
            id="welcomeMessage"
            rows={3}
            placeholder="Hello! How can I help you today?"
            {...register('welcomeMessage')}
          />
          {errors.welcomeMessage && (
            <p className="text-destructive text-sm">{errors.welcomeMessage.message}</p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="submit" disabled={updatePrompt.isPending || updateAgent.isPending}>
            {updatePrompt.isPending || updateAgent.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </form>
    </PageContainer>
  )
}
