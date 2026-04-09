import { Link } from '@tanstack/react-router'
import { Loader2, UserPlus, X } from 'lucide-react'
import { format } from 'date-fns'
import { useAuthStore } from '@/features/auth/store'
import { useOrgInvitations, useRevokeInvitation } from '@/features/org/hooks'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

export function InvitationsPage() {
  const orgId = useAuthStore((s) => s.orgId)
  const { data: invitations, isLoading } = useOrgInvitations(orgId)
  const revokeInvitation = useRevokeInvitation(orgId ?? '')

  return (
    <PageContainer>
      <PageHeader
        title="Invitations"
        description="Pending invitations to your organization."
        actions={
          <Button asChild size="sm">
            <Link to="/org/members/invite">
              <UserPlus className="mr-2 size-4" />
              Invite member
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="size-4 animate-spin" /> Loading…
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(invitations ?? []).map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="font-medium">{inv.email}</TableCell>
                  <TableCell className="capitalize">{inv.orgRole}</TableCell>
                  <TableCell>
                    <Badge
                      variant={inv.status === 'pending' ? 'secondary' : 'outline'}
                      className="capitalize text-xs"
                    >
                      {inv.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {format(new Date(inv.expiresAt), 'MMM d, yyyy')}
                  </TableCell>
                  <TableCell>
                    {inv.status === 'pending' && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-muted-foreground hover:text-destructive"
                        disabled={revokeInvitation.isPending}
                        onClick={() => {
                          revokeInvitation.mutate(inv.id)
                        }}
                      >
                        <X className="size-4" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}

              {(invitations ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    No pending invitations.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </PageContainer>
  )
}
