import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, ShieldCheck, ShieldOff, Copy, Check } from 'lucide-react'
import { useCurrentUser, use2FASetup, use2FAConfirm, useDisable2FA } from '@/features/auth/hooks'
import { twoFACodeSchema, type TwoFACodeInput } from '@/features/auth/schemas'
import { toast } from 'sonner'
import { getErrorMessage } from '@/shared/api/error-handler'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Badge } from '@/shared/components/ui/badge'
import { Separator } from '@/shared/components/ui/separator'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/components/ui/card'
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

// ── 2FA Setup flow ────────────────────────────────────────────────────────────

type Step = 'idle' | 'scan' | 'done'

interface SetupData {
  secret: string
  qrUri: string
  backupCodes: string[]
}

function SetupFlow() {
  const [step, setStep] = useState<Step>('idle')
  const [setupData, setSetupData] = useState<SetupData | null>(null)
  const [copied, setCopied] = useState(false)
  const setup2FA = use2FASetup()
  const confirm2FA = use2FAConfirm()

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<TwoFACodeInput>({ resolver: zodResolver(twoFACodeSchema) })

  const handleStart = () => {
    setup2FA.mutate(undefined, {
      onSuccess: (data) => {
        setSetupData(data as unknown as SetupData)
        setStep('scan')
      },
      onError: (err) => {
        toast.error(getErrorMessage(err))
      },
    })
  }

  const copySecret = () => {
    if (setupData?.secret) {
      void navigator.clipboard.writeText(setupData.secret)
      setCopied(true)
      setTimeout(() => {
        setCopied(false)
      }, 2000)
    }
  }

  if (step === 'done' && setupData?.backupCodes) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-green-500" />
            2FA Enabled
          </CardTitle>
          <CardDescription>Save these backup codes in a secure place.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-2 rounded-md border p-4 font-mono text-sm">
            {setupData.backupCodes.map((code) => (
              <span key={code} className="text-muted-foreground">
                {code}
              </span>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Each backup code can be used once if you lose access to your authenticator app.
          </p>
        </CardContent>
      </Card>
    )
  }

  if (step === 'scan' && setupData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Scan QR Code</CardTitle>
          <CardDescription>
            Open your authenticator app and scan the code, or enter the secret manually.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* QR code displayed as an image via Google Charts API */}
          <div className="flex justify-center">
            <img
              src={`https://chart.googleapis.com/chart?chs=200x200&chld=M|0&cht=qr&chl=${encodeURIComponent(setupData.qrUri)}`}
              alt="QR code for authenticator app"
              className="rounded-md border"
              width={200}
              height={200}
            />
          </div>

          <div className="space-y-2">
            <Label>Manual entry secret</Label>
            <div className="flex gap-2">
              <Input readOnly value={setupData.secret} className="font-mono text-sm" />
              <Button variant="outline" size="icon" onClick={copySecret}>
                {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
              </Button>
            </div>
          </div>

          <Separator />

          <form
            onSubmit={(e) => {
              void handleSubmit((data) => {
                confirm2FA.mutate(data.code, {
                  onError: (err) => {
                    setError('root', { message: getErrorMessage(err) })
                  },
                  onSuccess: () => {
                    setStep('done')
                  },
                })
              })(e)
            }}
          >
            <div className="space-y-4">
              {errors.root && (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {errors.root.message}
                </p>
              )}
              <div className="space-y-2">
                <Label htmlFor="code">Verification code</Label>
                <Input
                  id="code"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="000000"
                  className="font-mono text-center text-lg tracking-widest w-36"
                  {...register('code')}
                />
                {errors.code && <p className="text-xs text-destructive">{errors.code.message}</p>}
              </div>
              <Button type="submit" disabled={isSubmitting || confirm2FA.isPending}>
                {(isSubmitting || confirm2FA.isPending) && (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                )}
                Confirm & enable
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Enable Two-Factor Authentication</CardTitle>
        <CardDescription>
          Add an extra layer of security by requiring a code from your authenticator app.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button onClick={handleStart} disabled={setup2FA.isPending}>
          {setup2FA.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
          Set up 2FA
        </Button>
      </CardContent>
    </Card>
  )
}

// ── Disable 2FA ───────────────────────────────────────────────────────────────

function DisableSection() {
  const [open, setOpen] = useState(false)
  const disable2FA = useDisable2FA()

  return (
    <>
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <ShieldOff className="size-5" />
            Disable Two-Factor Authentication
          </CardTitle>
          <CardDescription>Removing 2FA will make your account less secure.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => {
              setOpen(true)
            }}
          >
            Disable 2FA
          </Button>
        </CardContent>
      </Card>

      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disable two-factor authentication?</AlertDialogTitle>
            <AlertDialogDescription>
              Your account will only require a password to log in. This reduces account security.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                disable2FA.mutate()
                setOpen(false)
              }}
            >
              Disable
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function TwoFASetupPage() {
  const { data: user, isLoading } = useCurrentUser()

  return (
    <PageContainer>
      <PageHeader
        title="Two-Factor Authentication"
        description="Add an extra layer of security to your account."
        actions={
          user?.twoFactorEnabled ? (
            <Badge variant="default" className="gap-1">
              <ShieldCheck className="size-3" />
              Enabled
            </Badge>
          ) : (
            <Badge variant="secondary" className="gap-1">
              <ShieldOff className="size-3" />
              Disabled
            </Badge>
          )
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground py-8">
          <Loader2 className="size-4 animate-spin" /> Loading…
        </div>
      ) : (
        <div className="space-y-6 max-w-lg">
          {user?.twoFactorEnabled ? <DisableSection /> : <SetupFlow />}
        </div>
      )}
    </PageContainer>
  )
}
