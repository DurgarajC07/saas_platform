import { useMemo } from 'react'
import { cn } from '@/shared/lib/utils'

interface PasswordStrengthProps {
  password: string
  className?: string
}

interface StrengthResult {
  score: 0 | 1 | 2 | 3 | 4
  label: string
  color: string
}

function calcStrength(password: string): StrengthResult {
  if (!password) return { score: 0, label: '', color: '' }

  let score = 0
  if (password.length >= 8) score++
  if (password.length >= 12) score++
  if (/[A-Z]/.test(password)) score++
  if (/[0-9]/.test(password)) score++
  if (/[^A-Za-z0-9]/.test(password)) score++

  // Map to 4-level scale
  const clamped = Math.min(score, 4) as 0 | 1 | 2 | 3 | 4

  const meta: Record<1 | 2 | 3 | 4, { label: string; color: string }> = {
    1: { label: 'Weak', color: 'bg-destructive' },
    2: { label: 'Fair', color: 'bg-orange-500' },
    3: { label: 'Good', color: 'bg-yellow-500' },
    4: { label: 'Strong', color: 'bg-green-500' },
  }

  if (clamped === 0) return { score: 0, label: '', color: '' }
  return { score: clamped, ...meta[clamped] }
}

/**
 * Visual password-strength bar.
 * Renders 4 segments that fill based on score derived from the given password.
 */
export function PasswordStrength({ password, className }: PasswordStrengthProps) {
  const { score, label, color } = useMemo(() => calcStrength(password), [password])

  if (!password) return null

  return (
    <div className={cn('space-y-1', className)}>
      <div className="flex gap-1">
        {([1, 2, 3, 4] as const).map((seg) => (
          <div
            key={seg}
            className={cn(
              'h-1.5 flex-1 rounded-full transition-colors duration-300',
              score >= seg ? color : 'bg-muted',
            )}
          />
        ))}
      </div>
      {label && (
        <p className="text-xs text-muted-foreground">
          Strength: <span className="font-medium">{label}</span>
        </p>
      )}
    </div>
  )
}
