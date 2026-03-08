import { Outlet } from '@tanstack/react-router'
import { Sidebar } from './Sidebar'
import { TopBar }  from './TopBar'
import { cn }      from '@/shared/lib/utils'
import { useRootStore } from '@/app/store'

export function AppShell() {
  const collapsed = useRootStore((s) => s.sidebarCollapsed)

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <Sidebar />

      {/* Main content area */}
      <div
        className={cn(
          'flex flex-1 flex-col overflow-hidden transition-all duration-200',
          collapsed ? 'ml-16' : 'ml-60',
        )}
      >
        <TopBar />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
