import { Link, useRouterState } from '@tanstack/react-router'
import {
  LayoutDashboard,
  Bot,
  PhoneCall,
  CreditCard,
  Users,
  Shield,
  Key,
  Webhook,
  FileText,
  Bell,
  Settings,
  ChevronLeft,
  ChevronRight,
  Activity,
  Lock,
  BarChart3,
  Cpu,
  Sliders,
} from 'lucide-react'
import { cn } from '@/shared/lib/utils'
import { useRootStore } from '@/app/store'
import { useAuthStore, selectIsPlatformAdmin } from '@/features/auth/store'

interface NavItem {
  label: string
  href: string
  icon: React.ElementType
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  // ── Dashboard ─────────────────────────────────────────────────────────────
  { label: 'Dashboard', href: '/', icon: LayoutDashboard },
  { label: 'Calls', href: '/dashboard/calls', icon: PhoneCall },
  { label: 'Analytics', href: '/dashboard/analytics', icon: BarChart3 },
  // ── Agents ────────────────────────────────────────────────────────────────
  { label: 'Agents', href: '/agents', icon: Bot },
  // ── Organisation ──────────────────────────────────────────────────────────
  { label: 'Members', href: '/org/members', icon: Users },
  { label: 'Roles', href: '/org/roles', icon: Shield },
  { label: 'Settings', href: '/org/settings', icon: Settings },
  // ── Billing ───────────────────────────────────────────────────────────────
  { label: 'Billing', href: '/billing', icon: CreditCard },
  // ── Developer ─────────────────────────────────────────────────────────────
  { label: 'API Keys', href: '/developer/api-keys', icon: Key },
  { label: 'Webhooks', href: '/developer/webhooks', icon: Webhook },
  // ── Security / Audit ──────────────────────────────────────────────────────
  { label: 'Security', href: '/security', icon: Lock },
  { label: 'Audit Logs', href: '/audit', icon: FileText },
  { label: 'Notifications', href: '/notifications', icon: Bell },
  // ── Admin (superuser only) ───────────────────────────────────────────────
  { label: 'Admin', href: '/admin', icon: Cpu, adminOnly: true },
  { label: 'GPU Status', href: '/admin/gpu-status', icon: Activity, adminOnly: true },
  { label: 'System', href: '/admin/system-settings', icon: Sliders, adminOnly: true },
]

export function Sidebar() {
  const collapsed = useRootStore((s) => s.sidebarCollapsed)
  const toggle = useRootStore((s) => s.toggleSidebar)
  const isSuperuser = useAuthStore(selectIsPlatformAdmin)
  const routerState = useRouterState()
  const currentPath = routerState.location.pathname

  const items = NAV_ITEMS.filter((i) => !i.adminOnly || isSuperuser)

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-50 flex flex-col border-r bg-card transition-all duration-200',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center border-b px-3">
        {!collapsed && <span className="ml-2 text-lg font-bold tracking-tight">VoiceSaaS</span>}
        {collapsed && <span className="text-lg font-bold">VS</span>}
      </div>

      {/* Nav items */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {items.map((item) => {
          const active =
            currentPath === item.href || (item.href !== '/' && currentPath.startsWith(item.href))
          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
              )}
            >
              <item.icon className="size-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          )
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t p-2">
        <button
          onClick={toggle}
          className="flex w-full items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
          {!collapsed && <span className="ml-2 text-sm">Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
