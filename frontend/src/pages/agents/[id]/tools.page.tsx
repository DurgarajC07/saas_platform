import { useEffect } from 'react'
import { useParams } from '@tanstack/react-router'
import { useForm, useFieldArray, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { PlusIcon, Trash2Icon } from 'lucide-react'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Textarea } from '@/shared/components/ui/textarea'
import { Switch } from '@/shared/components/ui/switch'
import { Card, CardContent, CardHeader } from '@/shared/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { EmptyState } from '@/shared/components/data-display/EmptyState'

import { useAgent, useUpdateTools } from '@/features/agents/hooks'
import {
  toolsFormSchema,
  toolsToFormValues,
  formValuesToToolsJson,
  EXECUTOR_TYPES,
  PARAMETER_TYPES,
  type ToolsFormInput,
} from '@/features/agents/schemas'

function ParameterRows({
  toolIndex,
  form,
}: {
  toolIndex: number
  form: ReturnType<typeof useForm<ToolsFormInput>>
}) {
  const { control, register } = form
  const { fields, append, remove } = useFieldArray({
    control,
    name: `tools.${toolIndex}.parameters`,
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Parameters</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            append({ name: '', type: 'string', description: '', required: false })
          }}
        >
          <PlusIcon className="mr-1 h-3.5 w-3.5" />
          Add parameter
        </Button>
      </div>

      {fields.length === 0 && (
        <p className="text-muted-foreground text-sm">No parameters defined.</p>
      )}

      {fields.map((field, paramIndex) => (
        <div key={field.id} className="flex flex-wrap items-end gap-2 rounded-md border p-3">
          <div className="min-w-[140px] flex-1 space-y-1">
            <Label className="text-xs">Name</Label>
            <Input {...register(`tools.${toolIndex}.parameters.${paramIndex}.name`)} />
          </div>
          <div className="w-32 space-y-1">
            <Label className="text-xs">Type</Label>
            <Controller
              control={control}
              name={`tools.${toolIndex}.parameters.${paramIndex}.type`}
              render={({ field: typeField }) => (
                <Select value={typeField.value} onValueChange={typeField.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PARAMETER_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
          <div className="min-w-[160px] flex-1 space-y-1">
            <Label className="text-xs">Description</Label>
            <Input {...register(`tools.${toolIndex}.parameters.${paramIndex}.description`)} />
          </div>
          <div className="flex items-center gap-2 pb-1.5">
            <Controller
              control={control}
              name={`tools.${toolIndex}.parameters.${paramIndex}.required`}
              render={({ field: reqField }) => (
                <Switch checked={reqField.value} onCheckedChange={reqField.onChange} />
              )}
            />
            <Label className="text-xs">Required</Label>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => {
              remove(paramIndex)
            }}
            aria-label="Remove parameter"
          >
            <Trash2Icon className="h-4 w-4" />
          </Button>
        </div>
      ))}
    </div>
  )
}

export function AgentToolsPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/tools' })
  const { data: agent, isLoading } = useAgent(agentId)
  const updateTools = useUpdateTools(agentId)

  const form = useForm<ToolsFormInput>({
    resolver: zodResolver(toolsFormSchema),
    defaultValues: { tools: [] },
  })
  const { control, register, reset, handleSubmit } = form
  const { fields, append, remove } = useFieldArray({ control, name: 'tools' })

  useEffect(() => {
    if (!agent) return
    reset({ tools: toolsToFormValues(agent.toolsJson) })
  }, [agent, reset])

  function onSubmit(values: ToolsFormInput) {
    updateTools.mutate(formValuesToToolsJson(values))
  }

  if (isLoading || !agent) {
    return (
      <PageContainer>
        <PageHeader title="Tools" description="Configure agent tools and integrations." />
        <div className="space-y-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader title="Tools" description="Configure agent tools and integrations." />

      <form
        onSubmit={(e) => {
          void handleSubmit(onSubmit)(e)
        }}
        className="space-y-6"
      >
        {fields.length === 0 ? (
          <EmptyState
            title="No tools configured"
            description="Add a tool to let this agent call external APIs or databases."
          />
        ) : (
          <div className="space-y-4">
            {fields.map((field, index) => (
              <Card key={field.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-4 pb-2">
                  <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label className="text-xs">Tool name</Label>
                      <Input {...register(`tools.${index}.name`)} placeholder="get_order_status" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Description</Label>
                      <Input
                        {...register(`tools.${index}.description`)}
                        placeholder="Looks up an order's current status"
                      />
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      remove(index)
                    }}
                    aria-label="Remove tool"
                  >
                    <Trash2Icon className="h-4 w-4" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Controller
                    control={control}
                    name={`tools.${index}.executorType`}
                    render={({ field: execField }) => (
                      <div className="space-y-1">
                        <Label className="text-xs">Executor type</Label>
                        <Select value={execField.value} onValueChange={execField.onChange}>
                          <SelectTrigger className="w-48">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {EXECUTOR_TYPES.map((t) => (
                              <SelectItem key={t} value={t}>
                                {t}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                  />

                  <Controller
                    control={control}
                    name={`tools.${index}.executorType`}
                    render={({ field: execField }) =>
                      execField.value === 'sql_query' ? (
                        <div className="space-y-1">
                          <Label className="text-xs">SQL query</Label>
                          <Textarea
                            rows={3}
                            {...register(`tools.${index}.sqlQuery`)}
                            placeholder="SELECT * FROM orders WHERE id = :order_id"
                          />
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <Label className="text-xs">URL</Label>
                          <Input
                            {...register(`tools.${index}.url`)}
                            placeholder="https://api.example.com/orders/{order_id}"
                          />
                        </div>
                      )
                    }
                  />

                  <ParameterRows toolIndex={index} form={form} />
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              append({
                name: '',
                description: '',
                executorType: 'http_get',
                url: '',
                sqlQuery: '',
                parameters: [],
              })
            }}
          >
            <PlusIcon className="mr-2 h-4 w-4" />
            Add tool
          </Button>

          <Button type="submit" disabled={updateTools.isPending}>
            {updateTools.isPending ? 'Saving…' : 'Save Tools'}
          </Button>
        </div>
      </form>
    </PageContainer>
  )
}
