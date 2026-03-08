import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { ShieldCheck } from 'lucide-react'
import { use2FAVerify } from '@/features/auth/hooks'
import { twoFACodeSchema, type TwoFACodeInput } from '@/features/auth/schemas'
import { getErrorMessage } from '@/shared/api/error-handler'
import { Button } from '@/shared/components/ui/button'
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/shared/components/ui/input-otp'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

export function TwoFAVerifyPage() {
  const verify = use2FAVerify()

  const {
    control,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<TwoFACodeInput>({ resolver: zodResolver(twoFACodeSchema) })

  const onSubmit = (data: TwoFACodeInput) => {
    const userId = sessionStorage.getItem('2fa_user_id') ?? null
    if (!userId) return
    verify.mutate(
      { userId, code: data.code },
      {
        onError: (err) => {
          setError('root', { message: getErrorMessage(err) })
        },
      },
    )
  }

  return (
    <div className="w-full max-w-md">
      <Card>
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <ShieldCheck className="size-6" />
          </div>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>Enter the 6-digit code from your authenticator app.</CardDescription>
        </CardHeader>

        <form
          onSubmit={(e) => {
            void handleSubmit(onSubmit)(e)
          }}
        >
          <CardContent className="flex flex-col items-center gap-4">
            {errors.root && (
              <p className="w-full rounded-md bg-destructive/10 px-3 py-2 text-center text-sm text-destructive">
                {errors.root.message}
              </p>
            )}

            <Controller
              name="code"
              control={control}
              render={({ field }) => (
                <InputOTP maxLength={6} value={field.value} onChange={field.onChange} autoFocus>
                  <InputOTPGroup>
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <InputOTPSlot key={i} index={i} className="size-12 text-lg" />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              )}
            />

            {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
          </CardContent>

          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" loading={verify.isPending}>
              Verify
            </Button>
            <Link to="/auth/login" className="text-xs text-muted-foreground hover:text-primary">
              Use a different account
            </Link>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
