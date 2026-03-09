import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useCurrentUser, useUpdateProfile, useChangePassword } from '@/features/auth/hooks'
import {
  updateProfileSchema,
  changePasswordSchema,
  type UpdateProfileInput,
  type ChangePasswordInput,
} from '@/features/auth/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Separator } from '@/shared/components/ui/separator'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

// ── Profile details form ──────────────────────────────────────────────────────

function ProfileForm() {
  const { data: user, isLoading } = useCurrentUser()
  const updateProfile = useUpdateProfile()

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<UpdateProfileInput>({
    resolver: zodResolver(updateProfileSchema),
  })

  // Populate form once user data arrives
  useEffect(() => {
    if (user) {
      reset({
        firstName: user.firstName ?? '',
        lastName: user.lastName ?? '',
        displayName: user.displayName ?? '',
        timezone: user.timezone,
        locale: user.locale,
        phone: '',
        avatarUrl: '',
      })
    }
  }, [user, reset])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground py-8">
        <Loader2 className="size-4 animate-spin" /> Loading profile…
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile Details</CardTitle>
        <CardDescription>Update your name, display name and preferences.</CardDescription>
      </CardHeader>
      <form
        onSubmit={(e) => {
          void handleSubmit((data) => {
            updateProfile.mutate(data, {
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

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="firstName">First name</Label>
              <Input id="firstName" {...register('firstName')} />
              {errors.firstName && (
                <p className="text-xs text-destructive">{errors.firstName.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="lastName">Last name</Label>
              <Input id="lastName" {...register('lastName')} />
              {errors.lastName && (
                <p className="text-xs text-destructive">{errors.lastName.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="displayName">Display name</Label>
            <Input id="displayName" placeholder="How others see you" {...register('displayName')} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="timezone">Timezone</Label>
              <Input id="timezone" placeholder="UTC" {...register('timezone')} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="locale">Locale</Label>
              <Input id="locale" placeholder="en" {...register('locale')} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="avatarUrl">Avatar URL</Label>
            <Input id="avatarUrl" type="url" placeholder="https://…" {...register('avatarUrl')} />
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={!isDirty || isSubmitting || updateProfile.isPending}>
              {(isSubmitting || updateProfile.isPending) && (
                <Loader2 className="mr-2 size-4 animate-spin" />
              )}
              Save changes
            </Button>
          </div>
        </CardContent>
      </form>
    </Card>
  )
}

// ── Change password form ──────────────────────────────────────────────────────

function ChangePasswordForm() {
  const changePassword = useChangePassword()

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordInput>({
    resolver: zodResolver(changePasswordSchema),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change Password</CardTitle>
        <CardDescription>Enter your current password and choose a new one.</CardDescription>
      </CardHeader>
      <form
        onSubmit={(e) => {
          void handleSubmit((data) => {
            changePassword.mutate(data, {
              onError: (err) => {
                setError('root', { message: getErrorMessage(err) })
              },
              onSuccess: () => {
                reset()
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
            <Label htmlFor="oldPassword">Current password</Label>
            <Input
              id="oldPassword"
              type="password"
              autoComplete="current-password"
              {...register('oldPassword')}
            />
            {errors.oldPassword && (
              <p className="text-xs text-destructive">{errors.oldPassword.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="newPassword">New password</Label>
            <Input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              {...register('newPassword')}
            />
            {errors.newPassword && (
              <p className="text-xs text-destructive">{errors.newPassword.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Confirm new password</Label>
            <Input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              {...register('confirmPassword')}
            />
            {errors.confirmPassword && (
              <p className="text-xs text-destructive">{errors.confirmPassword.message}</p>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              variant="outline"
              disabled={isSubmitting || changePassword.isPending}
            >
              {(isSubmitting || changePassword.isPending) && (
                <Loader2 className="mr-2 size-4 animate-spin" />
              )}
              Update password
            </Button>
          </div>
        </CardContent>
      </form>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ProfilePage() {
  const { data: user } = useCurrentUser()

  return (
    <PageContainer>
      <PageHeader
        title="Profile"
        description={user?.email ?? 'Manage your personal account settings.'}
      />

      <div className="space-y-6 max-w-2xl">
        <ProfileForm />
        <Separator />
        <ChangePasswordForm />
      </div>
    </PageContainer>
  )
}
