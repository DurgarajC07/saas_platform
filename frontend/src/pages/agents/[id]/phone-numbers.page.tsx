import { useState } from 'react'
import { useParams } from '@tanstack/react-router'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { PlusIcon, PhoneIcon, Trash2Icon } from 'lucide-react'
import { format } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/shared/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { EmptyState } from '@/shared/components/data-display/EmptyState'
import { ConfirmDialog } from '@/shared/components/feedback/ConfirmDialog'

import { usePhoneNumbers, useAssignPhoneNumber, useUnassignPhoneNumber } from '@/features/agents/hooks'
import {
  assignPhoneNumberSchema,
  PHONE_PROVIDERS,
  type AssignPhoneNumberInput,
} from '@/features/agents/schemas'

export function AgentPhoneNumbersPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/phone-numbers' })
  const { data: phoneNumbers, isLoading } = usePhoneNumbers(agentId)
  const assignPhoneNumber = useAssignPhoneNumber(agentId)
  const unassignPhoneNumber = useUnassignPhoneNumber(agentId)
  const [assignOpen, setAssignOpen] = useState(false)
  const [unassignTarget, setUnassignTarget] = useState<string | null>(null)

  const form = useForm<AssignPhoneNumberInput>({
    resolver: zodResolver(assignPhoneNumberSchema),
    defaultValues: { phoneNumber: '', provider: 'twilio' },
  })
  const {
    register,
    control,
    reset,
    formState: { errors },
  } = form

  function handleAssign(values: AssignPhoneNumberInput) {
    assignPhoneNumber.mutate(values, {
      onSuccess: () => {
        setAssignOpen(false)
        reset({ phoneNumber: '', provider: 'twilio' })
      },
    })
  }

  const numbers = phoneNumbers ?? []

  return (
    <PageContainer>
      <PageHeader
        title="Phone Numbers"
        description="Manage phone numbers assigned to this agent."
        actions={
          <Button
            onClick={() => {
              setAssignOpen(true)
            }}
          >
            <PlusIcon className="mr-2 h-4 w-4" />
            Assign number
          </Button>
        }
      />

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : numbers.length === 0 ? (
        <EmptyState
          icon={PhoneIcon}
          title="No phone numbers assigned"
          description="Assign a phone number so callers can reach this agent."
        />
      ) : (
        <div className="space-y-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Phone number</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Assigned</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {numbers.map((n) => (
                <TableRow key={n.id}>
                  <TableCell className="font-mono text-sm">{n.phoneNumber}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="capitalize">
                      {n.provider}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={n.isActive ? 'default' : 'secondary'}>
                      {n.isActive ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {format(new Date(n.createdAt), 'MMM d, yyyy')}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Unassign ${n.phoneNumber}`}
                      onClick={() => {
                        setUnassignTarget(n.id)
                      }}
                    >
                      <Trash2Icon className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ConfirmDialog
        open={unassignTarget !== null}
        onOpenChange={(open) => {
          if (!open) setUnassignTarget(null)
        }}
        title="Unassign phone number?"
        description="Callers to this number will no longer reach this agent until it's reassigned."
        confirmLabel="Unassign"
        loading={unassignPhoneNumber.isPending}
        onConfirm={() => {
          if (!unassignTarget) return
          unassignPhoneNumber.mutate(unassignTarget, {
            onSuccess: () => {
              setUnassignTarget(null)
            },
          })
        }}
      />

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign a phone number</DialogTitle>
          </DialogHeader>

          <form
            onSubmit={(e) => {
              void form.handleSubmit(handleAssign)(e)
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="phoneNumber">Phone number</Label>
              <Input id="phoneNumber" placeholder="+14155551234" {...register('phoneNumber')} />
              {errors.phoneNumber && (
                <p className="text-destructive text-sm">{errors.phoneNumber.message}</p>
              )}
            </div>

            <Controller
              control={control}
              name="provider"
              render={({ field }) => (
                <div className="space-y-2">
                  <Label>Provider</Label>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PHONE_PROVIDERS.map((p) => (
                        <SelectItem key={p} value={p} className="capitalize">
                          {p}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setAssignOpen(false)
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={assignPhoneNumber.isPending}>
                {assignPhoneNumber.isPending ? 'Assigning…' : 'Assign'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
