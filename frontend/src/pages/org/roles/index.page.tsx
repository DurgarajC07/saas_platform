import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Plus, Loader2, MoreHorizontal, Shield } from 'lucide-react'
import { useRoles, useDeleteRole } from '@/features/rbac/hooks'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
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

export function RolesListPage() {
  const { data, isLoading } = useRoles()
  const deleteRole = useDeleteRole()
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  return (
    <PageContainer>
      <PageHeader
        title="Roles"
        description="Manage custom roles and their permissions."
        actions={
          <Button asChild size="sm">
            <Link to="/org/roles/$roleId" params={{ roleId: 'new' }}>
              <Plus className="mr-2 size-4" />
              New role
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="size-4 animate-spin" /> Loading roles…
        </div>
      ) : (
        <div className="grid gap-3 max-w-2xl">
          {(data?.roles ?? []).map((role) => (
            <Card key={role.id} className="flex items-center">
              <CardHeader className="flex-row items-center gap-3 flex-1 py-4">
                <Shield className="size-5 text-muted-foreground shrink-0" />
                <div className="space-y-1 flex-1">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-sm font-medium">
                      {role.displayName ?? role.name}
                    </CardTitle>
                    {role.isSystemRole && (
                      <Badge variant="outline" className="text-xs">
                        System
                      </Badge>
                    )}
                  </div>
                  {role.description && (
                    <CardDescription className="text-xs">{role.description}</CardDescription>
                  )}
                </div>
              </CardHeader>
              <CardContent className="py-4 pr-4 pl-0">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="size-8">
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem asChild>
                      <Link to="/org/roles/$id" params={{ id: role.id }}>
                        Edit permissions
                      </Link>
                    </DropdownMenuItem>
                    {!role.isSystemRole && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onSelect={() => {
                            setDeleteTarget(role.id)
                          }}
                        >
                          Delete role
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </CardContent>
            </Card>
          ))}

          {(data?.roles ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground py-8">
              No roles found. Create your first custom role.
            </p>
          )}
        </div>
      )}

      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={() => {
          setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete role?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the role and remove it from all assigned members.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteTarget) {
                  deleteRole.mutate(deleteTarget)
                  setDeleteTarget(null)
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
