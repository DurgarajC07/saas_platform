import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate } from '@tanstack/react-router'
import { Loader2, ChevronLeft, Save } from 'lucide-react'
import { roleEditorRoute } from '@/app/router'
import {
  useRoles,
  useCreateRole,
  useUpdateRole,
  useRolePermissions,
  useSetRolePermissions,
  usePermissions,
} from '@/features/rbac/hooks'
import {
  createRoleSchema,
  updateRoleSchema,
  type CreateRoleInput,
  type UpdateRoleInput,
} from '@/features/rbac/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Checkbox } from '@/shared/components/ui/checkbox'
import { Separator } from '@/shared/components/ui/separator'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/shared/components/ui/card'

// ── New role form ──────────────────────────────────────────────────────────────

function NewRoleForm() {
  const createRole = useCreateRole()
  const navigate = useNavigate()

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateRoleInput>({ resolver: zodResolver(createRoleSchema) })

  return (
    <div className="max-w-xl">
      <Card>
        <CardHeader>
          <CardTitle>New Custom Role</CardTitle>
          <CardDescription>
            Define a role name and configure its permissions after creation.
          </CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            void handleSubmit((data) => {
              createRole.mutate(data, {
                onError: (err) => {
                  setError('root', { message: getErrorMessage(err) })
                },
                onSuccess: (role) =>
                  void navigate({ to: '/org/roles/$roleId', params: { roleId: role.id } }),
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
              <Label htmlFor="name">Name (slug)</Label>
              <Input id="name" placeholder="e.g. support_agent" {...register('name')} />
              {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="displayName">Display name</Label>
              <Input id="displayName" placeholder="Support Agent" {...register('displayName')} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                placeholder="Can view and respond to calls"
                {...register('description')}
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => void navigate({ to: '/org/roles' })}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting || createRole.isPending}>
                {(isSubmitting || createRole.isPending) && (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                )}
                Create role
              </Button>
            </div>
          </CardContent>
        </form>
      </Card>
    </div>
  )
}

// ── Edit role + permissions ────────────────────────────────────────────────────

function EditRoleContent({ roleId }: { roleId: string }) {
  const { data: rolesData, isLoading: loadingRoles } = useRoles()
  const { data: rolePerms, isLoading: loadingPerms } = useRolePermissions(roleId)
  const { data: allPerms, isLoading: loadingAllPerms } = usePermissions()
  const updateRole = useUpdateRole(roleId)
  const setPerms = useSetRolePermissions(roleId)

  const role = rolesData?.roles.find((r) => r.id === roleId)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [permsDirty, setPermsDirty] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<UpdateRoleInput>({ resolver: zodResolver(updateRoleSchema) })

  useEffect(() => {
    if (role) {
      reset({
        name: role.name,
        displayName: role.displayName ?? '',
        description: role.description ?? '',
        priority: role.priority,
      })
    }
  }, [role, reset])

  useEffect(() => {
    if (rolePerms) {
      setSelected(new Set(rolePerms.permissions.map((p) => p.id)))
    }
  }, [rolePerms])

  const isLoading = loadingRoles || loadingPerms || loadingAllPerms

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground py-8">
        <Loader2 className="size-4 animate-spin" /> Loading…
      </div>
    )
  }

  if (!role) {
    return <p className="text-muted-foreground">Role not found.</p>
  }

  const togglePerm = (id: string) => {
    setPermsDirty(true)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Role metadata card */}
      <Card>
        <CardHeader>
          <CardTitle>Role Details</CardTitle>
        </CardHeader>
        <form
          onSubmit={(e) => {
            void handleSubmit((data) => {
              updateRole.mutate(data, {
                onError: (err) => {
                  setError('root', { message: getErrorMessage(err) })
                },
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
              <Label htmlFor="name">Name (slug)</Label>
              <Input id="name" disabled={role.isSystemRole} {...register('name')} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="displayName">Display name</Label>
              <Input id="displayName" {...register('displayName')} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input id="description" {...register('description')} />
            </div>

            <div className="flex justify-end">
              <Button
                type="submit"
                size="sm"
                disabled={!isDirty || isSubmitting || updateRole.isPending || role.isSystemRole}
              >
                {(isSubmitting || updateRole.isPending) && (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                )}
                Save details
              </Button>
            </div>
          </CardContent>
        </form>
      </Card>

      {/* Permissions card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Permissions</CardTitle>
              <CardDescription>
                {selected.size} permission{selected.size !== 1 ? 's' : ''} selected
              </CardDescription>
            </div>
            <Button
              size="sm"
              disabled={!permsDirty || setPerms.isPending}
              onClick={() => {
                setPerms.mutate([...selected], {
                  onSuccess: () => {
                    setPermsDirty(false)
                  },
                })
              }}
            >
              {setPerms.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Save className="mr-2 size-4" />
              )}
              Save permissions
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {(allPerms?.groups ?? []).map((group) => (
            <div key={group.module}>
              <h4 className="text-sm font-semibold capitalize mb-3">{group.module}</h4>
              <div className="grid gap-2 sm:grid-cols-2">
                {group.permissions.map((perm) => (
                  <div key={perm.id} className="flex items-start gap-2">
                    <Checkbox
                      id={perm.id}
                      checked={selected.has(perm.id)}
                      onCheckedChange={() => {
                        togglePerm(perm.id)
                      }}
                    />
                    <div className="grid gap-0.5">
                      <label
                        htmlFor={perm.id}
                        className="text-sm font-medium leading-none cursor-pointer"
                      >
                        {perm.displayName ?? perm.name}
                      </label>
                      {perm.description && (
                        <p className="text-xs text-muted-foreground">{perm.description}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <Separator className="mt-4" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function RoleEditorPage() {
  const { roleId } = roleEditorRoute.useParams()
  const navigate = useNavigate()
  const isNew = roleId === 'new'

  return (
    <PageContainer>
      <PageHeader
        title={isNew ? 'New Role' : 'Edit Role'}
        description={isNew ? 'Create a custom role for this organization.' : `Role ID: ${roleId}`}
        actions={
          <Button variant="ghost" size="sm" onClick={() => void navigate({ to: '/org/roles' })}>
            <ChevronLeft className="mr-1 size-4" />
            Back to roles
          </Button>
        }
      />

      {isNew ? <NewRoleForm /> : <EditRoleContent roleId={roleId} />}
    </PageContainer>
  )
}
