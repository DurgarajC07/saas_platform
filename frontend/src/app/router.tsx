import {
  createRouter,
  createRootRoute,
  createRoute,
  Outlet,
  redirect,
} from '@tanstack/react-router'
import { useAuthStore } from '@/features/auth/store'

// ─── Layouts ─────────────────────────────────────────────────────────────────
import { AppShell }  from '@/shared/components/layout/AppShell'

// ─── Auth pages ──────────────────────────────────────────────────────────────
import { LoginPage }          from '@/pages/auth/login.page'
import { RegisterPage }       from '@/pages/auth/register.page'
import { ForgotPasswordPage } from '@/pages/auth/forgot-password.page'
import { ResetPasswordPage }  from '@/pages/auth/reset-password.page'
import { VerifyEmailPage }    from '@/pages/auth/verify-email.page'
import { TwoFAVerifyPage }    from '@/pages/auth/2fa-verify.page'

// ─── App pages ───────────────────────────────────────────────────────────────
import { DashboardPage }      from '@/pages/dashboard/index.page'
import { CallsDashboardPage } from '@/pages/dashboard/calls.page'
import { AnalyticsPage }      from '@/pages/dashboard/analytics.page'

import { AgentListPage }          from '@/pages/agents/index.page'
import { AgentNewPage }           from '@/pages/agents/new.page'
import { AgentDetailPage }        from '@/pages/agents/[id]/index.page'
import { AgentEditPage }          from '@/pages/agents/[id]/edit.page'
import { AgentPromptPage }        from '@/pages/agents/[id]/prompt.page'
import { AgentKnowledgeBasePage } from '@/pages/agents/[id]/knowledge-base.page'
import { AgentToolsPage }         from '@/pages/agents/[id]/tools.page'
import { AgentPhoneNumbersPage }  from '@/pages/agents/[id]/phone-numbers.page'
import { AgentCallsPage }         from '@/pages/agents/[id]/calls.page'
import { AgentAnalyticsPage }     from '@/pages/agents/[id]/analytics.page'
import { AgentTestCallPage }      from '@/pages/agents/[id]/test-call.page'

import { CallsListPage }          from '@/pages/calls/index.page'
import { CallDetailPage }         from '@/pages/calls/[id].page'

import { OrgSettingsPage }        from '@/pages/org/settings.page'
import { MembersListPage }        from '@/pages/org/members/index.page'
import { InviteMemberPage }       from '@/pages/org/members/invite.page'
import { InvitationsPage }        from '@/pages/org/invitations.page'
import { DomainsPage }            from '@/pages/org/domains.page'
import { RolesListPage }          from '@/pages/org/roles/index.page'
import { RoleEditorPage }         from '@/pages/org/roles/[id].page'

import { BillingPage }            from '@/pages/billing/index.page'
import { PlansPage }              from '@/pages/billing/plans.page'
import { InvoicesListPage }       from '@/pages/billing/invoices/index.page'
import { InvoiceDetailPage }      from '@/pages/billing/invoices/[id].page'
import { PaymentMethodsPage }     from '@/pages/billing/payment-methods.page'

import { ApiKeysPage }            from '@/pages/developer/api-keys.page'
import { WebhooksListPage }       from '@/pages/developer/webhooks/index.page'
import { WebhookNewPage }         from '@/pages/developer/webhooks/new.page'
import { WebhookDetailPage }      from '@/pages/developer/webhooks/[id].page'
import { WebhookDeliveriesPage }  from '@/pages/developer/webhooks/[id]/deliveries.page'

import { SecurityPage }           from '@/pages/security/index.page'
import { SessionsPage }           from '@/pages/security/sessions.page'
import { TwoFASetupPage }         from '@/pages/security/2fa.page'
import { BlockedIPsPage }         from '@/pages/security/blocked-ips.page'

import { AuditLogsPage }          from '@/pages/audit/index.page'
import { AuditLogDetailPage }     from '@/pages/audit/[id].page'

import { NotificationsPage }      from '@/pages/notifications/index.page'
import { NotificationPrefsPage }  from '@/pages/notifications/preferences.page'

import { ProfilePage }            from '@/pages/profile/index.page'

import { AdminDashboardPage }     from '@/pages/admin/index.page'
import { GpuStatusPage }          from '@/pages/admin/gpu-status.page'
import { FeaturesAdminPage }      from '@/pages/admin/features.page'
import { SystemSettingsPage }     from '@/pages/admin/system-settings.page'

// ─────────────────────────────────────────────────────────────────────────────
// Auth guard
// ─────────────────────────────────────────────────────────────────────────────
function requireAuth() {
  const token = useAuthStore.getState().token
  if (!token) throw redirect({ to: '/auth/login' })
}

// ─────────────────────────────────────────────────────────────────────────────
// Route tree
// ─────────────────────────────────────────────────────────────────────────────

// Root
const rootRoute = createRootRoute({ component: Outlet })

// ── Auth layout ───────────────────────────────────────────────────────────────
const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth-layout',
  component: () => (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <Outlet />
    </div>
  ),
})

const loginRoute            = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/login',            component: LoginPage })
const registerRoute         = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/register',         component: RegisterPage })
const forgotPasswordRoute   = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/forgot-password',  component: ForgotPasswordPage })
const resetPasswordRoute    = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/reset-password',   component: ResetPasswordPage })
const verifyEmailRoute      = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/verify-email',     component: VerifyEmailPage })
const twoFAVerifyRoute      = createRoute({ getParentRoute: () => authLayoutRoute, path: '/auth/2fa-verify',       component: TwoFAVerifyPage })

// ── App layout (protected) ────────────────────────────────────────────────────
const appLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app-layout',
  beforeLoad: requireAuth,
  component: AppShell,
})

// Dashboard
const dashboardRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/',                   component: DashboardPage })
const dashboardCallsRoute   = createRoute({ getParentRoute: () => appLayoutRoute, path: '/dashboard/calls',    component: CallsDashboardPage })
const analyticsRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/dashboard/analytics', component: AnalyticsPage })

// Agents
const agentListRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents',                          component: AgentListPage })
const agentNewRoute         = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/new',                      component: AgentNewPage })
const agentDetailRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId',                 component: AgentDetailPage })
const agentEditRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/edit',            component: AgentEditPage })
const agentPromptRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/prompt',          component: AgentPromptPage })
const agentKBRoute          = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/knowledge-base',  component: AgentKnowledgeBasePage })
const agentToolsRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/tools',           component: AgentToolsPage })
const agentPhonesRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/phone-numbers',   component: AgentPhoneNumbersPage })
const agentCallsRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/calls',           component: AgentCallsPage })
const agentAnalyticsRoute   = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/analytics',      component: AgentAnalyticsPage })
const agentTestCallRoute    = createRoute({ getParentRoute: () => appLayoutRoute, path: '/agents/$agentId/test-call',       component: AgentTestCallPage })

// Calls
const callsListRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/calls',              component: CallsListPage })
const callDetailRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/calls/$callId',      component: CallDetailPage })

// Org
const orgSettingsRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/settings',             component: OrgSettingsPage })
const membersListRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/members',              component: MembersListPage })
const inviteMemberRoute     = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/members/invite',       component: InviteMemberPage })
const invitationsRoute      = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/invitations',          component: InvitationsPage })
const domainsRoute          = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/domains',              component: DomainsPage })
const rolesListRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/roles',                component: RolesListPage })
const roleEditorRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/org/roles/$roleId',        component: RoleEditorPage })

// Billing
const billingRoute          = createRoute({ getParentRoute: () => appLayoutRoute, path: '/billing',                  component: BillingPage })
const plansRoute            = createRoute({ getParentRoute: () => appLayoutRoute, path: '/billing/plans',            component: PlansPage })
const invoicesListRoute     = createRoute({ getParentRoute: () => appLayoutRoute, path: '/billing/invoices',          component: InvoicesListPage })
const invoiceDetailRoute    = createRoute({ getParentRoute: () => appLayoutRoute, path: '/billing/invoices/$invoiceId', component: InvoiceDetailPage })
const paymentMethodsRoute   = createRoute({ getParentRoute: () => appLayoutRoute, path: '/billing/payment-methods',  component: PaymentMethodsPage })

// Developer
const apiKeysRoute          = createRoute({ getParentRoute: () => appLayoutRoute, path: '/developer/api-keys',               component: ApiKeysPage })
const webhooksListRoute     = createRoute({ getParentRoute: () => appLayoutRoute, path: '/developer/webhooks',               component: WebhooksListPage })
const webhookNewRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/developer/webhooks/new',           component: WebhookNewPage })
const webhookDetailRoute    = createRoute({ getParentRoute: () => appLayoutRoute, path: '/developer/webhooks/$webhookId',    component: WebhookDetailPage })
const webhookDeliveriesRoute= createRoute({ getParentRoute: () => appLayoutRoute, path: '/developer/webhooks/$webhookId/deliveries', component: WebhookDeliveriesPage })

// Security
const securityRoute         = createRoute({ getParentRoute: () => appLayoutRoute, path: '/security',               component: SecurityPage })
const sessionsRoute         = createRoute({ getParentRoute: () => appLayoutRoute, path: '/security/sessions',      component: SessionsPage })
const twoFASetupRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/security/2fa',           component: TwoFASetupPage })
const blockedIPsRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/security/blocked-ips',   component: BlockedIPsPage })

// Audit
const auditLogsRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/audit',          component: AuditLogsPage })
const auditLogDetailRoute   = createRoute({ getParentRoute: () => appLayoutRoute, path: '/audit/$logId',   component: AuditLogDetailPage })

// Notifications
const notificationsRoute    = createRoute({ getParentRoute: () => appLayoutRoute, path: '/notifications',              component: NotificationsPage })
const notifPrefsRoute       = createRoute({ getParentRoute: () => appLayoutRoute, path: '/notifications/preferences',  component: NotificationPrefsPage })

// Profile
const profileRoute          = createRoute({ getParentRoute: () => appLayoutRoute, path: '/profile',        component: ProfilePage })

// Admin
const adminRoute            = createRoute({ getParentRoute: () => appLayoutRoute, path: '/admin',                  component: AdminDashboardPage })
const gpuStatusRoute        = createRoute({ getParentRoute: () => appLayoutRoute, path: '/admin/gpu-status',        component: GpuStatusPage })
const featuresAdminRoute    = createRoute({ getParentRoute: () => appLayoutRoute, path: '/admin/features',          component: FeaturesAdminPage })
const systemSettingsRoute   = createRoute({ getParentRoute: () => appLayoutRoute, path: '/admin/system-settings',   component: SystemSettingsPage })

// ─────────────────────────────────────────────────────────────────────────────
// Build the route tree
// ─────────────────────────────────────────────────────────────────────────────
const routeTree = rootRoute.addChildren([
  authLayoutRoute.addChildren([
    loginRoute, registerRoute, forgotPasswordRoute,
    resetPasswordRoute, verifyEmailRoute, twoFAVerifyRoute,
  ]),
  appLayoutRoute.addChildren([
    dashboardRoute, dashboardCallsRoute, analyticsRoute,
    agentListRoute, agentNewRoute,
    agentDetailRoute, agentEditRoute, agentPromptRoute,
    agentKBRoute, agentToolsRoute, agentPhonesRoute,
    agentCallsRoute, agentAnalyticsRoute, agentTestCallRoute,
    callsListRoute, callDetailRoute,
    orgSettingsRoute, membersListRoute, inviteMemberRoute,
    invitationsRoute, domainsRoute, rolesListRoute, roleEditorRoute,
    billingRoute, plansRoute, invoicesListRoute, invoiceDetailRoute, paymentMethodsRoute,
    apiKeysRoute, webhooksListRoute, webhookNewRoute, webhookDetailRoute, webhookDeliveriesRoute,
    securityRoute, sessionsRoute, twoFASetupRoute, blockedIPsRoute,
    auditLogsRoute, auditLogDetailRoute,
    notificationsRoute, notifPrefsRoute,
    profileRoute,
    adminRoute, gpuStatusRoute, featuresAdminRoute, systemSettingsRoute,
  ]),
])

export const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
