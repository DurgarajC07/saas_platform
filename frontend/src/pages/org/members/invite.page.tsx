import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/features/auth/store'
import { useInviteMember } from '@/features/org/hooks'
import { inviteMemberSchema, type InviteMemberInput } from '@/features/org/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

export function InviteMemberPage() {
  const orgId = useAuthStore((s) => s.orgId)
  const invite = useInviteMember(orgId ?? '')
  const navigate = useNavigate()

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<InviteMemberInput>({
    resolver: zodResolver(inviteMemberSchema),
    defaultValues: { orgRole: 'member' },
  })

  const roleValue = watch('orgRole')

  return (
    <PageContainer>
      <PageHeader
        title="Invite Member"
        description="Send an invitation email to a new team member."
      />

      <div className="max-w-lg">
        <Card>
          <CardHeader>
            <CardTitle>New invitation</CardTitle>
            <CardDescription>
              The recipient will receive an email with instructions to join.
            </CardDescription>
          </CardHeader>
          <form
            onSubmit={(e) => {
              void handleSubmit((data) => {
                invite.mutate(data, {
                  onError: (err) => {
                    setError('root', { message: getErrorMessage(err) })
                  },
                  onSuccess: () => void navigate({ to: '/org/members' }),
                })
              })(e)
            }}
          >
            <CardContent className="space-y-4">
              {errors.root && (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {errors.root.message}
                </p>
              )}

              <div className="space-y-2">
                <Label htmlFor="email">Email address</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="off"
                  placeholder="colleague@example.com"
                  {...register('email')}
                />
                {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="orgRole">Role</Label>
                <Select
                  value={roleValue}
                  onValueChange={(v) => {
                    setValue('orgRole', v as InviteMemberInput['orgRole'], { shouldValidate: true })
                  }}
                >
                  <SelectTrigger id="orgRole">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="member">Member</SelectItem>
                    <SelectItem value="viewer">Viewer</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void navigate({ to: '/org/members' })}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isSubmitting || invite.isPending}>
                  {(isSubmitting || invite.isPending) && (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  )}
                  Send invitation
                </Button>
              </div>
            </CardContent>
          </form>
        </Card>
      </div>
    </PageContainer>
  )
}
