import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { MailCheck } from 'lucide-react'
import { useForgotPassword } from '@/features/auth/hooks'
import { forgotPasswordSchema, type ForgotPasswordInput } from '@/features/auth/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

const RESEND_COOLDOWN = 60 // seconds

export function ForgotPasswordPage() {
  const forgot = useForgotPassword()
  const [countdown, setCountdown] = useState(0)

  const {
    register,
    handleSubmit,
    getValues,
    setError,
    formState: { errors },
  } = useForm<ForgotPasswordInput>({ resolver: zodResolver(forgotPasswordSchema) })

  // Start countdown when email is sent
  useEffect(() => {
    if (!forgot.isSuccess) return
    setCountdown(RESEND_COOLDOWN)
    const id = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(id)
          return 0
        }
        return c - 1
      })
    }, 1000)
    return () => {
      clearInterval(id)
    }
  }, [forgot.isSuccess, forgot.data]) // re-start whenever a new success occurs

  if (forgot.isSuccess) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <MailCheck className="size-6" />
            </div>
            <CardTitle>Check your email</CardTitle>
            <CardDescription>
              We sent a password reset link to <strong>{getValues('email')}</strong>.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-center space-y-3">
            {countdown > 0 ? (
              <p className="text-sm text-muted-foreground">
                Resend link in <span className="font-medium tabular-nums">{countdown}s</span>
              </p>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  forgot.mutate(getValues())
                }}
                loading={forgot.isPending}
              >
                Resend link
              </Button>
            )}
          </CardContent>
          <CardFooter className="justify-center">
            <Link to="/auth/login" className="text-sm text-muted-foreground hover:text-primary">
              Back to sign in
            </Link>
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
        <form
          onSubmit={(e) => {
            void handleSubmit((data) => {
              forgot.mutate(data, {
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
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="alice@example.com"
                {...register('email')}
              />
              {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
            </div>
          </CardContent>
          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" loading={forgot.isPending}>
              Send reset link
            </Button>
            <Link to="/auth/login" className="text-sm text-muted-foreground hover:text-primary">
              Back to sign in
            </Link>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
