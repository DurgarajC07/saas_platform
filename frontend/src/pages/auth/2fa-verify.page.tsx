import { useForm }      from 'react-hook-form'
import { zodResolver }  from '@hookform/resolvers/zod'
import { use2FAVerify } from '@/features/auth/hooks'
import { twoFACodeSchema, type TwoFACodeInput } from '@/features/auth/schemas'
import { Button }       from '@/shared/components/ui/button'
import { Input }        from '@/shared/components/ui/input'
import { Label }        from '@/shared/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { ShieldCheck }  from 'lucide-react'

export function TwoFAVerifyPage() {
  const verify = use2FAVerify()

  const { register, handleSubmit, formState: { errors } } =
    useForm<TwoFACodeInput>({ resolver: zodResolver(twoFACodeSchema) })

  const onSubmit = (data: TwoFACodeInput) => {
    const mfaToken = sessionStorage.getItem('mfa_token') ?? ''
    verify.mutate({ mfaToken, code: data.code })
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
        <form onSubmit={handleSubmit(onSubmit)}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="code">Verification code</Label>
              <Input
                id="code"
                placeholder="000000"
                maxLength={6}
                className="text-center text-2xl tracking-widest"
                {...register('code')}
              />
              {errors.code && <p className="text-xs text-destructive">{errors.code.message}</p>}
            </div>
          </CardContent>
          <CardFooter>
            <Button className="w-full" type="submit" loading={verify.isPending}>Verify</Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
