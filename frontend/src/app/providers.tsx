import { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { ThemeProvider } from '@/shared/components/theme-provider'
import { toast, Toaster } from 'sonner'

// ─────────────────────────────────────────────────────────────────────────────
// QueryClient — singleton, created once at module level
// ─────────────────────────────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000, // 1 min before background refetch
      gcTime: 5 * 60_000, // 5 min in-memory cache
      retry: (count, err) => count < 3 && (err as { status?: number }).status !== 401,
      refetchOnWindowFocus: false,
    },
    mutations: {
      onError: (err: unknown) => {
        const message = err instanceof Error ? err.message : 'An unexpected error occurred.'
        toast.error(message)
      },
    },
  },
})

// ─────────────────────────────────────────────────────────────────────────────
// Root provider tree
// ─────────────────────────────────────────────────────────────────────────────
interface ProvidersProps {
  children: ReactNode
}

export function Providers({ children }: ProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" storageKey="ui-theme">
        {children}
        <Toaster position="bottom-right" richColors closeButton />
      </ThemeProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}

export { queryClient }
