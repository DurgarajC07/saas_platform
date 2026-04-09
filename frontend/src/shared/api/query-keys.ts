/**
 * Centralized query-key factory.
 *
 * Rules:
 *  - Every feature imports from this file — no inline string keys
 *  - Keys are nested arrays so TanStack Query can do precise invalidation:
 *      queryClient.invalidateQueries({ queryKey: queryKeys.agents.all() })
 *      invalidates every agents.* query
 */

// ─── Filter shape types ───────────────────────────────────────────────────────
export interface AgentFilters {
  page?: number
  pageSize?: number
  search?: string
  status?: string
  type?: string
}
export interface CallFilters {
  page?: number
  pageSize?: number
  status?: string
  agentId?: string
}
export interface AuditFilters {
  page?: number
  pageSize?: number
  action?: string
  from?: string
  to?: string
}
export interface NotifFilters {
  page?: number
  pageSize?: number
  isRead?: boolean
}

// ─────────────────────────────────────────────────────────────────────────────
export const queryKeys = {
  // Auth
  auth: {
    me: () => ['auth', 'me'] as const,
  },

  // Agents
  agents: {
    all: () => ['agents'] as const,
    list: (f: AgentFilters) => ['agents', 'list', f] as const,
    detail: (id: string) => ['agents', id] as const,
    prompt: (id: string) => ['agents', id, 'prompt'] as const,
    calls: (id: string, f: CallFilters) => ['agents', id, 'calls', f] as const,
    analytics: (id: string, days?: number) => ['agents', id, 'analytics', days] as const,
    kb: (id: string) => ['agents', id, 'kb'] as const,
    phones: (id: string) => ['agents', id, 'phones'] as const,
    usage: () => ['agents', 'usage'] as const,
  },

  // Calls
  calls: {
    all: () => ['calls'] as const,
    list: (f: CallFilters) => ['calls', 'list', f] as const,
    detail: (id: string) => ['calls', id] as const,
    live: () => ['calls', 'live'] as const,
  },

  // Dashboard
  dashboard: {
    overview: () => ['dashboard', 'overview'] as const,
    latency: (min?: number) => ['dashboard', 'latency', min] as const,
    callVolume: (period: string) => ['dashboard', 'call-volume', period] as const,
    agentPerf: (days?: number) => ['dashboard', 'agent-performance', days] as const,
    analytics: (from: string, to: string) => ['dashboard', 'analytics', from, to] as const,
    gpuStatus: () => ['dashboard', 'gpu-status'] as const,
    queueStatus: () => ['dashboard', 'queue-status'] as const,
  },

  // Billing
  billing: {
    plans: () => ['billing', 'plans'] as const,
    plan: (id: string) => ['billing', 'plans', id] as const,
    subscription: () => ['billing', 'subscription'] as const,
    invoices: (page: number) => ['billing', 'invoices', page] as const,
    invoice: (id: string) => ['billing', 'invoices', id] as const,
    paymentMethods: () => ['billing', 'payment-methods'] as const,
    usage: () => ['billing', 'usage'] as const,
    preview: () => ['billing', 'invoice-preview'] as const,
  },

  // RBAC
  rbac: {
    roles: () => ['rbac', 'roles'] as const,
    role: (id: string) => ['rbac', 'roles', id] as const,
    permissions: () => ['rbac', 'permissions'] as const,
    rolePerms: (id: string) => ['rbac', 'roles', id, 'permissions'] as const,
    memberRoles: (id: string) => ['rbac', 'members', id, 'roles'] as const,
  },

  // Features
  features: {
    all: () => ['features'] as const,
    check: (key: string) => ['features', 'check', key] as const,
    overrides: (orgId: string) => ['features', 'overrides', orgId] as const,
  },

  // Notifications
  notifications: {
    list: (f: NotifFilters) => ['notifications', 'list', f] as const,
    count: () => ['notifications', 'count'] as const,
    prefs: () => ['notifications', 'preferences'] as const,
  },

  // Files
  files: {
    all: () => ['files'] as const,
    list: (page: number) => ['files', 'list', page] as const,
    detail: (id: string) => ['files', id] as const,
  },

  // API Keys
  apiKeys: {
    all: () => ['api-keys'] as const,
  },

  // Webhooks
  webhooks: {
    all: () => ['webhooks'] as const,
    list: (page: number) => ['webhooks', 'list', page] as const,
    detail: (id: string) => ['webhooks', id] as const,
    deliveries: (id: string) => ['webhooks', id, 'deliveries'] as const,
  },

  // Audit
  audit: {
    list: (f: AuditFilters) => ['audit', 'list', f] as const,
    detail: (id: string) => ['audit', id] as const,
  },

  // Security
  security: {
    attempts: (page: number) => ['security', 'attempts', page] as const,
    blockedIPs: (page: number) => ['security', 'blocked-ips', page] as const,
    events: () => ['security', 'events'] as const,
  },

  // Tenancy
  tenancy: {
    org: (slug: string) => ['orgs', slug] as const,
    members: (orgId: string) => ['orgs', orgId, 'members'] as const,
    invitations: (orgId: string) => ['orgs', orgId, 'invitations'] as const,
    domains: (orgId: string) => ['orgs', orgId, 'domains'] as const,
  },

  // System
  system: {
    health: () => ['system', 'health'] as const,
    stats: () => ['system', 'stats'] as const,
    settings: () => ['system', 'settings'] as const,
  },
} as const
