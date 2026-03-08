import { z } from 'zod'

// ─── Shared ───────────────────────────────────────────────────────────────────
export const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .regex(/[A-Z]/, 'Must contain an uppercase letter')
  .regex(/[0-9]/, 'Must contain a number')

// ─── Request schemas ──────────────────────────────────────────────────────────
export const loginSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(1, 'Password is required'),
})

// Matches backend RegisterRequest: firstName + lastName + email + password
export const registerSchema = z.object({
  firstName: z.string().min(1, 'First name is required').max(150),
  lastName: z.string().min(1, 'Last name is required').max(150),
  email: z.string().email('Invalid email address'),
  password: passwordSchema,
})

export const forgotPasswordSchema = z.object({
  email: z.string().email('Invalid email address'),
})

export const resetPasswordSchema = z
  .object({
    token: z.string().min(1),
    newPassword: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

export const changePasswordSchema = z
  .object({
    oldPassword: z.string().min(1, 'Current password is required'),
    newPassword: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

export const twoFACodeSchema = z.object({
  code: z.string().length(6, 'Code must be 6 digits').regex(/^\d+$/, 'Digits only'),
})

// ─── Response types (aligned with backend camelCase serialisation) ────────────

/** Returned by POST /auth/login (success), POST /auth/refresh, POST /auth/2fa/verify */
export interface TokenResponse {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresIn: number
}

/** Returned by POST /auth/login when 2FA is enabled (HTTP 200) */
export interface TwoFactorChallengeResponse {
  code: string // "TWO_FACTOR_REQUIRED"
  message: string
  userId: string
}

/** Returned by GET /auth/me and POST /auth/register */
export interface UserResponse {
  id: string
  email: string
  firstName: string | null
  lastName: string | null
  displayName: string | null
  isActive: boolean
  isPlatformAdmin: boolean
  emailVerified: boolean
  twoFactorEnabled: boolean
  timezone: string
  locale: string
  createdAt: string
}

/** Backward-compat alias */
export type AuthResponse = TokenResponse

export interface SessionResponse {
  id: string
  ipAddress: string | null
  userAgent: string | null
  deviceType: string | null
  lastActiveAt: string
  createdAt: string
  isCurrent: boolean
}

// Types inferred from Zod schemas
export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
export type ForgotPasswordInput = z.infer<typeof forgotPasswordSchema>
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>
export type TwoFACodeInput = z.infer<typeof twoFACodeSchema>
