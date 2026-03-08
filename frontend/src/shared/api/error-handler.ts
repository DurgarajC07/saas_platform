import { type AxiosError } from 'axios'

// ─── Canonical API error shape (mirrors backend error envelope) ───────────────
export interface ApiError {
  code: string // e.g. "NOT_FOUND", "UNAUTHORIZED"
  message: string
  requestId: string | null
  status: number
}

// Map backend error codes to user-friendly messages
const CODE_MESSAGES: Record<string, string> = {
  UNAUTHORIZED: 'Your session has expired. Please log in again.',
  FORBIDDEN: "You don't have permission to perform this action.",
  NOT_FOUND: 'The requested resource was not found.',
  CONFLICT: 'A resource with this identifier already exists.',
  VALIDATION_ERROR: 'Please check the form for errors.',
  RATE_LIMITED: 'Too many requests. Please wait a moment and try again.',
  SERVICE_UNAVAILABLE: 'Service temporarily unavailable. Please try again soon.',
  INTERNAL_ERROR: 'Something went wrong on our end. Please try again.',
}

export function normalizeError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0
  const data = error.response?.data as {
    error?: { code?: string; message?: string; request_id?: string }
  }

  const code = data.error?.code ?? 'UNKNOWN_ERROR'
  const message =
    data.error?.message ?? (CODE_MESSAGES[code] as string | undefined) ?? error.message
  const requestId = data.error?.request_id ?? null

  return { code, message, requestId, status }
}

/** Type-guard: was this error thrown by the API (vs network/timeout)? */
export function isApiError(err: unknown): err is ApiError {
  return typeof err === 'object' && err !== null && 'code' in err && 'status' in err
}

/** Return the message from any error shape */
export function getErrorMessage(err: unknown): string {
  if (isApiError(err)) return err.message
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred.'
}
