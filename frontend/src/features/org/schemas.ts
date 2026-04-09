import { z } from 'zod'

// ─── Request schemas ──────────────────────────────────────────────────────────

export const createOrgSchema = z.object({
  name: z.string().min(2, 'Name must be at least 2 characters').max(255),
  timezone: z.string().max(100).default('UTC'),
  locale: z.string().max(20).default('en'),
  currency: z.string().max(10).default('USD'),
  website: z.string().url('Invalid URL').max(255).optional().or(z.literal('')),
  industry: z.string().max(150).optional().or(z.literal('')),
})

export const updateOrgSchema = z.object({
  name: z.string().min(2).max(255).optional(),
  timezone: z.string().max(100).optional(),
  locale: z.string().max(20).optional(),
  currency: z.string().max(10).optional(),
  website: z.string().url('Invalid URL').max(255).optional().or(z.literal('')),
  industry: z.string().max(150).optional().or(z.literal('')),
  logoUrl: z.string().url().max(1024).optional().or(z.literal('')),
})

export const inviteMemberSchema = z.object({
  email: z.string().email('Invalid email address'),
  orgRole: z.enum(['admin', 'member', 'viewer']).default('member'),
})

export const updateMemberRoleSchema = z.object({
  orgRole: z.enum(['owner', 'admin', 'member', 'viewer']),
})

export const addDomainSchema = z.object({
  domain: z.string().min(3, 'Enter a valid domain').max(255),
})

// ─── Response interfaces (camelCase from backend) ─────────────────────────────

export interface OrgResponse {
  id: string
  name: string
  slug: string
  logoUrl: string | null
  website: string | null
  industry: string | null
  ownerUserId: string | null
  timezone: string
  locale: string
  currency: string
  maxSeats: number | null
  isActive: boolean
  onboardingCompletedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface UserBrief {
  id: string
  email: string
  firstName: string | null
  lastName: string | null
  displayName: string | null
  avatarUrl: string | null
}

export interface MemberResponse {
  id: string
  organizationId: string
  user: UserBrief
  orgRole: string
  status: string
  joinedAt: string
  createdAt: string
  suspendedAt: string | null
  suspensionReason: string | null
}

export interface MemberListResponse {
  members: MemberResponse[]
  total: number
  page: number
  pageSize: number
  totalPages: number
}

export interface InvitationResponse {
  id: string
  organizationId: string
  email: string
  orgRole: string
  status: string
  invitedBy: string
  expiresAt: string
  acceptedAt: string | null
  createdAt: string
  token: string
}

export interface DomainResponse {
  id: string
  organizationId: string
  domain: string
  isVerified: boolean
  verificationToken: string | null
  verifiedAt: string | null
  createdAt: string
}

// ─── Inferred types ───────────────────────────────────────────────────────────
export type CreateOrgInput = z.infer<typeof createOrgSchema>
export type UpdateOrgInput = z.infer<typeof updateOrgSchema>
export type InviteMemberInput = z.infer<typeof inviteMemberSchema>
export type UpdateMemberRoleInput = z.infer<typeof updateMemberRoleSchema>
export type AddDomainInput = z.infer<typeof addDomainSchema>
