import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/features/auth/store'
import { useOrg, useUpdateOrg } from '@/features/org/hooks'
import { updateOrgSchema, type UpdateOrgInput } from '@/features/org/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

// NOTE: This page reads the org by its ID, stored as orgId in the auth store.
// We pass that as the "slug" to the API for now; the backend also accepts the
// UUID directly since TenancyService.get_organization_by_slug accepts both.

export function OrgSettingsPage() {
  const orgId = useAuthStore((s) => s.orgId)
  const { data: org, isLoading } = useOrg(orgId)
  const updateOrg = useUpdateOrg(orgId ?? '')

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<UpdateOrgInput>({ resolver: zodResolver(updateOrgSchema) })

  useEffect(() => {
    if (org) {
      reset({
        name: org.name,
        timezone: org.timezone,
        locale: org.locale,
        currency: org.currency,
        website: org.website ?? '',
        industry: org.industry ?? '',
        logoUrl: org.logoUrl ?? '',
      })
    }
  }, [org, reset])

  if (isLoading) {
    return (
      <PageContainer>
        <PageHeader title="Organization Settings" description="" />
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="size-4 animate-spin" /> Loading…
        </div>
      </PageContainer>
    )
  }

  if (!org) {
    return (
      <PageContainer>
        <PageHeader title="Organization Settings" description="" />
        <p className="text-muted-foreground">No organization found.</p>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader title="Organization Settings" description={`/${org.slug} · ${org.currency}`} />

      <div className="max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle>General</CardTitle>
            <CardDescription>Update the organization name and preferences.</CardDescription>
          </CardHeader>
          <form
            onSubmit={(e) => {
              void handleSubmit((data) => {
                updateOrg.mutate(data, {
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
                <Label htmlFor="name">Organization name</Label>
                <Input id="name" {...register('name')} />
                {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Input id="timezone" placeholder="UTC" {...register('timezone')} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="locale">Locale</Label>
                  <Input id="locale" placeholder="en" {...register('locale')} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="currency">Currency</Label>
                  <Input id="currency" placeholder="USD" {...register('currency')} />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="website">Website</Label>
                <Input
                  id="website"
                  type="url"
                  placeholder="https://example.com"
                  {...register('website')}
                />
                {errors.website && (
                  <p className="text-xs text-destructive">{errors.website.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="industry">Industry</Label>
                <Input id="industry" placeholder="Technology" {...register('industry')} />
              </div>

              <div className="space-y-2">
                <Label htmlFor="logoUrl">Logo URL</Label>
                <Input id="logoUrl" type="url" placeholder="https://…" {...register('logoUrl')} />
              </div>

              <div className="flex justify-end">
                <Button type="submit" disabled={!isDirty || isSubmitting || updateOrg.isPending}>
                  {(isSubmitting || updateOrg.isPending) && (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  )}
                  Save changes
                </Button>
              </div>
            </CardContent>
          </form>
        </Card>
      </div>
    </PageContainer>
  )
}
