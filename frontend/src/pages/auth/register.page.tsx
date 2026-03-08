import { useForm }       from 'react-hook-form'
import { zodResolver }   from '@hookform/resolvers/zod'
import { Link }          from '@tanstack/react-router'
import { Bot }           from 'lucide-react'
import { useRegister }   from '@/features/auth/hooks'
import { registerSchema, type RegisterInput } from '@/features/auth/schemas'
import { Button }        from '@/shared/components/ui/button'
import { Input }         from '@/shared/components/ui/input'
import { Label }         from '@/shared/components/ui/label'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/components/ui/card'

export function RegisterPage() {
  const register_  = useRegister()

  const { register, handleSubmit, formState: { errors } } =
    useForm<RegisterInput>({ resolver: zodResolver(registerSchema) })

  return (
    <div className="w-full max-w-md space-y-6">
      <div className="flex flex-col items-center gap-2">
        <div className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Bot className="size-6" />
        </div>
        <h1 className="text-2xl font-bold">VoiceSaaS</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Create account</CardTitle>
          <CardDescription>Start your free trial today</CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit((data) => register_.mutate(data))}>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="first_name">First name</Label>
                <Input id="first_name" placeholder="Alice" {...register('first_name')} />
                {errors.first_name && <p className="text-xs text-destructive">{errors.first_name.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="last_name">Last name</Label>
                <Input id="last_name" placeholder="Smith" {...register('last_name')} />
                {errors.last_name && <p className="text-xs text-destructive">{errors.last_name.message}</p>}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="alice@example.com" {...register('email')} />
              {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" placeholder="••••••••" {...register('password')} />
              {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
            </div>
          </CardContent>

          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" loading={register_.isPending}>
              Create account
            </Button>
            <p className="text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link to="/auth/login" className="text-primary hover:underline">Sign in</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
