import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { MoreHorizontal, Loader2, UserPlus } from 'lucide-react'
import { useAuthStore } from '@/features/auth/store'
import { useOrgMembers, useRemoveMember, useUpdateMemberRole } from '@/features/org/hooks'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/components/ui/alert-dialog'

const ROLE_VARIANT: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  owner: 'default',
  admin: 'secondary',
  member: 'outline',
  viewer: 'outline',
}

export function MembersListPage() {
  const orgId = useAuthStore((s) => s.orgId)
  const currentUserId = useAuthStore((s) => s.user?.id)
  const { data, isLoading } = useOrgMembers(orgId)
  const removeMember = useRemoveMember(orgId ?? '')
  const updateRole = useUpdateMemberRole(orgId ?? '')
  const [removeTarget, setRemoveTarget] = useState<string | null>(null)

  return (
    <PageContainer>
      <PageHeader
        title="Members"
        description={`${data?.total ?? 0} members`}
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
          <Loader2 className="size-4 animate-spin" /> Loading members…
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.members ?? []).map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-medium">
                    {(m.user.displayName ??
                      `${m.user.firstName ?? ''} ${m.user.lastName ?? ''}`.trim()) ||
                      '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{m.user.email}</TableCell>
                  <TableCell>
                    <Select
                      value={m.orgRole}
                      disabled={
                        m.orgRole === 'owner' || m.user.id === currentUserId || updateRole.isPending
                      }
                      onValueChange={(val) => {
                        updateRole.mutate({
                          uid: m.user.id,
                          body: { orgRole: val as 'owner' | 'admin' | 'member' | 'viewer' },
                        })
                      }}
                    >
                      <SelectTrigger className="h-7 w-28 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="owner">Owner</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                        <SelectItem value="member">Member</SelectItem>
                        <SelectItem value="viewer">Viewer</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={ROLE_VARIANT[m.orgRole] ?? 'outline'}
                      className="capitalize text-xs"
                    >
                      {m.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {m.user.id !== currentUserId && m.orgRole !== 'owner' && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="size-8">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onSelect={() => {
                              setRemoveTarget(m.user.id)
                            }}
                          >
                            Remove member
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </TableCell>
                </TableRow>
              ))}

              {(data?.members ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    No members found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Remove confirmation dialog */}
      <AlertDialog
        open={Boolean(removeTarget)}
        onOpenChange={() => {
          setRemoveTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove member?</AlertDialogTitle>
            <AlertDialogDescription>
              This will deactivate the member's access to the organization. They will need a new
              invitation to rejoin.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (removeTarget) {
                  removeMember.mutate(removeTarget)
                  setRemoveTarget(null)
                }
              }}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
