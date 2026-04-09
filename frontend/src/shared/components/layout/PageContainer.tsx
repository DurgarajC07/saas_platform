import { type ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type MaxWidth = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full'

interface PageContainerProps {
  children: ReactNode
  maxWidth?: MaxWidth
  className?: string
}

// ─────────────────────────────────────────────────────────────────────────────
// Width map — tailwind classes get statically analysed, must be complete strings
// ─────────────────────────────────────────────────────────────────────────────
const widths: Record<MaxWidth, string> = {
  sm: 'max-w-2xl',
  md: 'max-w-4xl',
  lg: 'max-w-5xl',
  xl: 'max-w-6xl',
  '2xl': 'max-w-7xl',
  full: 'max-w-none',
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
/**
 * Every page wraps its content in PageContainer.
 * Enforces consistent max-width, padding, and scroll behaviour.
 */
export function PageContainer({ children, maxWidth = '2xl', className }: PageContainerProps) {
  return (
    <div className={cn('mx-auto w-full px-4 py-6 sm:px-6 lg:px-8', widths[maxWidth], className)}>
      {children}
    </div>
  )
}
