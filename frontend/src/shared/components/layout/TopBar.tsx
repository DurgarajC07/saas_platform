import { Bell, User, LogOut, Settings, ChevronDown } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { useAuthStore } from '@/features/auth/store'
import { useLogout } from '@/features/auth/hooks'
import { cn } from '@/shared/lib/utils'

export function TopBar() {
  const user = useAuthStore((s) => s.user)
  const logout = useLogout()

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b bg-card px-4">
      {/* Left: breadcrumb / page title rendered by child pages via portal or context */}
      <div id="topbar-title" />

      {/* Right: notifications + user menu */}
      <div className="flex items-center gap-2">
        <Link
          to="/notifications"
          className={cn(
            'relative rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors',
          )}
          aria-label="Notifications"
        >
          <Bell className="size-4" />
        </Link>

        {/* User dropdown — simple for now, expanded in profile page */}
        <div className="group relative">
          <button className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-accent transition-colors">
            <div className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
              {(user?.displayName?.[0] ?? user?.firstName?.[0] ?? 'U').toUpperCase()}
            </div>
            <span className="hidden sm:block max-w-32 truncate">
              {user?.displayName ?? user?.firstName ?? 'User'}
            </span>
            <ChevronDown className="size-3 text-muted-foreground" />
          </button>

          {/* Dropdown */}
          <div className="invisible absolute right-0 top-full z-50 mt-1 w-48 rounded-md border bg-popover shadow-md group-focus-within:visible group-hover:visible">
            <Link
              to="/profile"
              className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent"
            >
              <User className="size-4" /> Profile
            </Link>
            <Link
              to="/org/settings"
              className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent"
            >
              <Settings className="size-4" /> Org Settings
            </Link>
            <hr className="my-1" />
            <button
              onClick={() => {
                logout.mutate()
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-destructive hover:bg-destructive/10"
            >
              <LogOut className="size-4" /> Sign out
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
