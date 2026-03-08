import { useForm }         from 'react-hook-form'
import { zodResolver }     from '@hookform/resolvers/zod'
import { Link }            from '@tanstack/react-router'
import { useResetPassword } from '@/features/auth/hooks'
import { resetPasswordSchema, type ResetPasswordInput } from '@/features/auth/schemas'
import { Button }          from '@/shared/components/ui/button'
import { Input }           from '@/shared/components/ui/input'
import { Label }           from '@/shared/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'

export function ResetPasswordPage() {
  const reset = useResetPassword()
  const { register, handleSubmit, formState: { errors } } =
    useForm<ResetPasswordInput>({ resolver: zodResolver(resetPasswordSchema) })

  if (reset.isSuccess) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Password updated</CardTitle>
            <CardDescription>Your password has been reset successfully.</CardDescription>
          </CardHeader>
          <CardFooter>
            <Link to="/auth/login" className="text-sm text-primary hover:underline">Sign in</Link>
          </CardFooter>
        </Card>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md">
      <Card>
        <CardHeader>
          <CardTitle>Reset password</CardTitle>
          <CardDescription>Enter your new password below.</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit((data) => reset.mutate(data))}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="newPassword">New password</Label>
              <Input id="newPassword" type="password" placeholder="••••••••" {...register('newPassword')} />
              {errors.newPassword && <p className="text-xs text-destructive">{errors.newPassword.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm password</Label>
              <Input id="confirmPassword" type="password" placeholder="••••••••" {...register('confirmPassword')} />
              {errors.confirmPassword && <p className="text-xs text-destructive">{errors.confirmPassword.message}</p>}
            </div>
          </CardContent>
          <CardFooter>
            <Button className="w-full" type="submit" loading={reset.isPending}>Reset password</Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
