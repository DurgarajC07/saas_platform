import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/features/auth/store'

type SSEStatus = 'connecting' | 'connected' | 'error' | 'closed'

interface UseSSEOptions {
  /** Set to false to temporarily pause the connection without unmounting */
  enabled?: boolean
}

interface UseSSEReturn<T> {
  data: T | null
  status: SSEStatus
  close: () => void
}

/**
 * Opens a persistent EventSource connection to an SSE endpoint.
 * Auth token is appended as a query param because EventSource doesn't
 * support custom headers.
 *
 * @example
 *   const { data, status } = useSSE<LiveCallsSnapshot>('/dashboard/live-calls/stream')
 */

export function useSSE<T>(path: string, options?: UseSSEOptions): UseSSEReturn<T> {
  const enabled = options?.enabled ?? true
  const token = useAuthStore((s) => s.token)

  const [data, setData] = useState<T | null>(null)
  const [status, setStatus] = useState<SSEStatus>('connecting')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!enabled || !token) return

    const base = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1'
    const url = `${base}${path}?token=${encodeURIComponent(token)}`

    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => {
      setStatus('connected')
    }
    es.onerror = () => {
      setStatus('error')
    }
    es.onmessage = (e: MessageEvent<string>) => {
      try {
        setData(JSON.parse(e.data) as T)
        setStatus('connected')
      } catch {
        // ignore malformed frames
      }
    }

    return () => {
      es.close()
      esRef.current = null
      setStatus('closed')
    }
  }, [path, token, enabled])

  /** Manually close the connection */
  const close = () => {
    esRef.current?.close()
    setStatus('closed')
  }

  return { data, status, close }
}
