import { z } from 'zod'

// ─── Shared ───────────────────────────────────────────────────────────────────
const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .regex(/[A-Z]/, 'Must contain an uppercase letter')
  .regex(/[0-9]/, 'Must contain a number')

// ─── Request schemas ──────────────────────────────────────────────────────────
export const loginSchema = z.object({
  email:    z.string().email('Invalid email address'),
  password: z.string().min(1, 'Password is required'),
})

export const registerSchema = z.object({
  email:    z.string().email('Invalid email address'),
  password: passwordSchema,
  fullName: z.string().min(2, 'Full name is required'),
  orgName:  z.string().min(2, 'Organisation name is required'),
  orgSlug:  z
    .string()
    .min(3, 'Slug must be at least 3 characters')
    .regex(/^[a-z0-9-]+$/, 'Slug may only contain lowercase letters, numbers and hyphens'),
})

export const forgotPasswordSchema = z.object({
  email: z.string().email('Invalid email address'),
})

export const resetPasswordSchema = z
  .object({
    token:           z.string().min(1),
    newPassword:     passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: 'Passwords do not match',
    path:    ['confirmPassword'],
  })

export const changePasswordSchema = z
  .object({
    oldPassword:     z.string().min(1, 'Current password is required'),
    newPassword:     passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: 'Passwords do not match',
    path:    ['confirmPassword'],
  })

export const twoFACodeSchema = z.object({
  code: z.string().length(6, 'Code must be 6 digits').regex(/^\d+$/, 'Digits only'),
})

// ─── Response types ──────────────────────────────────────────────────────────
export interface UserResponse {
  id:          string
  email:       string
  fullName:    string
  avatarUrl:   string | null
  isVerified:  boolean
  isSuperuser: boolean
  createdAt:   string
  updatedAt:   string
}

export interface AuthResponse {
  accessToken:  string
  refreshToken: string
  tokenType:    string
  expiresIn:    number
  user:         UserResponse
}

export interface SessionResponse {
  id:          string
  deviceInfo:  string
  ipAddress:   string
  isCurrent:   boolean
  createdAt:   string
  lastUsedAt:  string
}

// Types inferred from Zod schemas
export type LoginInput          = z.infer<typeof loginSchema>
export type RegisterInput       = z.infer<typeof registerSchema>
export type ForgotPasswordInput = z.infer<typeof forgotPasswordSchema>
export type ResetPasswordInput  = z.infer<typeof resetPasswordSchema>
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>
export type TwoFACodeInput      = z.infer<typeof twoFACodeSchema>
