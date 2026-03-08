import { type ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface PageContainerProps {
  children:  ReactNode
  className?: string
  /** Full-width — removes max-w constraint */
  fluid?:     boolean
}

export function PageContainer({ children, className, fluid = false }: PageContainerProps) {
  return (
    <div
      className={cn(
        'mx-auto w-full space-y-6 p-6',
        !fluid && 'max-w-7xl',
        className,
      )}
    >
      {children}
    </div>
  )
}
