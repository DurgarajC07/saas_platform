export const APP_NAME = 'VoiceSaaS'
export const APP_VERSION = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? '1.0.0'

// API
export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1'

// Pagination
export const DEFAULT_PAGE_SIZE = 20
export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

// Query stale times (ms)
export const STALE_1MIN = 60_000
export const STALE_5MIN = 300_000
export const STALE_30MIN = 1_800_000

// Local-storage keys
export const LS_AUTH_KEY = 'voicesaas-auth'
export const LS_SIDEBAR_KEY = 'voicesaas-sidebar'

// Routes (centralized for type-safe navigation)
export const ROUTES = {
  login: '/auth/login',
  register: '/auth/register',
  forgotPassword: '/auth/forgot-password',
  resetPassword: '/auth/reset-password',
  verifyEmail: '/auth/verify-email',
  twoFA: '/auth/2fa',
  dashboard: '/dashboard',
  agents: '/agents',
  agentNew: '/agents/new',
  calls: '/calls',
  billing: '/billing',
  developer: '/developer/api-keys',
  security: '/security',
  audit: '/audit',
  notifications: '/notifications',
  profile: '/profile',
  admin: '/admin',
} as const
