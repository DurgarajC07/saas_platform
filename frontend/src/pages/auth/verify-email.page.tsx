import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Button } from '@/shared/components/ui/button'
import { Link }   from '@tanstack/react-router'
import { MailCheck } from 'lucide-react'

export function VerifyEmailPage() {
  return (
    <div className="w-full max-w-md">
      <Card>
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <MailCheck className="size-6" />
          </div>
          <CardTitle>Verify your email</CardTitle>
          <CardDescription>
            We sent a verification link to your email address. Please check your inbox.
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
