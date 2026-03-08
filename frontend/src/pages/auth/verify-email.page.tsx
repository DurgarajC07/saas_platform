import { Link } from '@tanstack/react-router'
import { CheckCircle2, XCircle, Loader2, MailCheck } from 'lucide-react'
import { useVerifyEmail } from '@/features/auth/hooks'
import { Button } from '@/shared/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'

export function VerifyEmailPage() {
  const token = new URLSearchParams(window.location.search).get('token') ?? ''

  const verification = useVerifyEmail(token)

  // No token in URL — show generic info page
  if (!token) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
              <MailCheck className="size-6" />
            </div>
            <CardTitle>Verify your email</CardTitle>
            <CardDescription>
              We sent a verification link to your email address. Please check your inbox and click
              the link to activate your account.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-center">
            <Link to="/auth/login">
              <Button variant="outline">Back to sign in</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (verification.isPending) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-10">
            <Loader2 className="size-10 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Verifying your email…</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (verification.isError) {
    return (
      <div className="w-full max-w-md">
        <Card>
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <XCircle className="size-6" />
            </div>
            <CardTitle>Verification failed</CardTitle>
            <CardDescription>
              The verification link is invalid or has expired. Please request a new one.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <Link to="/auth/login">
              <Button variant="outline">Back to sign in</Button>
            </Link>
          </CardFooter>
        </Card>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md">
      <Card>
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-green-100 text-green-600 dark:bg-green-900 dark:text-green-400">
            <CheckCircle2 className="size-6" />
          </div>
          <CardTitle>Email verified!</CardTitle>
          <CardDescription>
            Your email has been verified. You can now sign in to your account.
          </CardDescription>
        </CardHeader>
        <CardFooter className="justify-center">
          <Link to="/auth/login">
            <Button>Sign in</Button>
          </Link>
        </CardFooter>
      </Card>
    </div>
  )
}
