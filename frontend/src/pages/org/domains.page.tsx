import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, Plus, RefreshCw, Trash2, CheckCircle2, Clock } from 'lucide-react'
import { format } from 'date-fns'
import { useAuthStore } from '@/features/auth/store'
import { useOrgDomains, useAddDomain, useDeleteDomain, useVerifyDomain } from '@/features/org/hooks'
import { addDomainSchema, type AddDomainInput } from '@/features/org/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Badge } from '@/shared/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

function AddDomainCard({ orgId }: { orgId: string }) {
  const addDomain = useAddDomain(orgId)
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AddDomainInput>({ resolver: zodResolver(addDomainSchema) })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add Domain</CardTitle>
        <CardDescription>
          Add a domain to verify ownership with a DNS TXT record at{' '}
          <code className="text-xs">_saas-verify.&lt;yourdomain.com&gt;</code>.
        </CardDescription>
      </CardHeader>
      <form
        onSubmit={(e) => {
          void handleSubmit((data) => {
            addDomain.mutate(data, {
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
          <div className="flex gap-2">
            <div className="flex-1 space-y-1">
              <Label htmlFor="domain">Domain</Label>
              <Input id="domain" placeholder="example.com" {...register('domain')} />
              {errors.domain && <p className="text-xs text-destructive">{errors.domain.message}</p>}
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={isSubmitting || addDomain.isPending}>
                {isSubmitting || addDomain.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Plus className="size-4" />
                )}
                <span className="ml-2">Add</span>
              </Button>
            </div>
          </div>
        </CardContent>
      </form>
    </Card>
  )
}

export function DomainsPage() {
  const orgId = useAuthStore((s) => s.orgId)
  const { data: domains, isLoading } = useOrgDomains(orgId)
  const deleteDomain = useDeleteDomain(orgId ?? '')
  const verifyDomain = useVerifyDomain(orgId ?? '')

  return (
    <PageContainer>
      <PageHeader title="Domains" description="Manage and verify organization domains." />

      <div className="space-y-6 max-w-2xl">
        {orgId && <AddDomainCard orgId={orgId} />}

        <Card>
          <CardHeader>
            <CardTitle>Registered Domains</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center gap-2 text-muted-foreground py-4">
                <Loader2 className="size-4 animate-spin" /> Loading…
              </div>
            ) : (domains ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-4">No domains registered yet.</p>
            ) : (
              <div className="divide-y">
                {(domains ?? []).map((d) => (
                  <div key={d.id} className="flex items-center justify-between py-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        {d.isVerified ? (
                          <CheckCircle2 className="size-4 text-green-500" />
                        ) : (
                          <Clock className="size-4 text-muted-foreground" />
                        )}
                        <span className="font-medium text-sm">{d.domain}</span>
                        <Badge variant={d.isVerified ? 'default' : 'secondary'} className="text-xs">
                          {d.isVerified ? 'Verified' : 'Pending'}
                        </Badge>
                      </div>
                      {!d.isVerified && d.verificationToken && (
                        <p className="text-xs text-muted-foreground ml-6">
                          TXT record value:{' '}
                          <code className="font-mono bg-muted px-1 rounded">
                            {d.verificationToken}
                          </code>
                        </p>
                      )}
                      {d.verifiedAt && (
                        <p className="text-xs text-muted-foreground ml-6">
                          Verified {format(new Date(d.verifiedAt), 'MMM d, yyyy')}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {!d.isVerified && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={verifyDomain.isPending}
                          onClick={() => {
                            verifyDomain.mutate(d.id)
                          }}
                        >
                          <RefreshCw className="mr-1 size-3" />
                          Verify
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-muted-foreground hover:text-destructive"
                        disabled={deleteDomain.isPending}
                        onClick={() => {
                          deleteDomain.mutate(d.id)
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}
