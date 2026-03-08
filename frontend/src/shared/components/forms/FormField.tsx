import type { ReactNode } from 'react'
import type { FieldError } from 'react-hook-form'
import {
  FormControl,
  FormDescription,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/shared/components/ui/form'

interface FormFieldWrapperProps {
  label?: string
  description?: string
  error?: FieldError
  required?: boolean
  children: ReactNode
}

/**
 * Lightweight wrapper that composes shadcn/ui Form primitives.
 * Reduces boilerplate in every form field — just pass your control element.
 *
 * Usage:
 *   <FormFieldWrapper label="Email" error={errors.email}>
 *     <Input {...register('email')} />
 *   </FormFieldWrapper>
 */
export function FormFieldWrapper({
  label,
  description,
  error,
  required,
  children,
}: FormFieldWrapperProps) {
  return (
    <FormItem>
      {label && (
        <FormLabel>
          {label}
          {required && <span className="ml-0.5 text-destructive">*</span>}
        </FormLabel>
      )}
      <FormControl>{children}</FormControl>
      {description && !error && <FormDescription>{description}</FormDescription>}
      {error?.message && <FormMessage>{error.message}</FormMessage>}
    </FormItem>
  )
}
