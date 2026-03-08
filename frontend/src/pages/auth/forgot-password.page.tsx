import { useForm }            from 'react-hook-form'
import { zodResolver }        from '@hookform/resolvers/zod'
import { Link }               from '@tanstack/react-router'
import { useForgotPassword }  from '@/features/auth/hooks'
import { forgotPasswordSchema, type ForgotPasswordInput } from '@/features/auth/schemas'
import { Button }             from '@/shared/components/ui/button'
import { Input }              from '@/shared/components/ui/input'
import { Label }              from '@/shared/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'

export function ForgotPasswordPage() {
  const forgot = useForgotPassword()
  const { register, handleSubmit, formState: { errors } } =
    useForm<ForgotPasswordInput>({ resolver: zodResolver(forgotPasswordSchema) })

  if (forgot.isSuccess) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Check your email</CardTitle>
            <CardDescription>We sent a password reset link to your inbox.</CardDescription>
          </CardHeader>
          <CardFooter>
            <Link to="/auth/login" className="text-sm text-primary hover:underline">Back to sign in</Link>
          </CardFooter>
        </Card>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md">
      <Card>
        <CardHeader>
          <CardTitle>Forgot password</CardTitle>
          <CardDescription>Enter your email and we'll send a reset link.</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit((data) => forgot.mutate(data))}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="alice@example.com" {...register('email')} />
              {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
            </div>
          </CardContent>
          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" loading={forgot.isPending}>Send reset link</Button>
            <Link to="/auth/login" className="text-sm text-muted-foreground hover:text-primary">Back to sign in</Link>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
