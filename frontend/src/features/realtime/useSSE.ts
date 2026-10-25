import { useEffect, useRef, useState } from 'react'
import { apiClient } from '@/shared/api/client'

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
 * Opens a persistent EventSource connection to an SSE endpoint via a
 * short-lived ticket exchange.
 *
 * Browsers' native EventSource API cannot attach an Authorization header or
 * a custom org-context header, which is how every other request in this app
 * authenticates. Passing the long-lived access token as a `?token=` query
 * param instead would work mechanically, but leaks it into proxy logs,
 * browser history, and Referer headers for as long as that token is valid.
 *
 * Instead: `ticketPath` is a normal authenticated POST endpoint (sent
 * through the shared `apiClient`, so it carries the real auth/org headers)
 * that returns `{ ticket }` — a random, single-use value valid for ~30s.
 * That ticket, not the access token, is what goes in the EventSource URL.
 *
 * @example
 *   const { data, status } = useSSE<LiveCallEvent>({
 *     ticketPath: '/dashboard/live-calls/ticket',
 *     streamPath: '/calls/live',
 *   })
 */
export function useSSE<T>(
  { ticketPath, streamPath }: { ticketPath: string; streamPath: string },
  options?: UseSSEOptions,
): UseSSEReturn<T> {
  const enabled = options?.enabled ?? true

  const [data, setData] = useState<T | null>(null)
  const [status, setStatus] = useState<SSEStatus>('connecting')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    const base = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1'

    async function connect() {
      try {
        const { data: ticketData } = await apiClient.post<{ ticket: string }>(ticketPath)
        if (cancelled) return

        const url = `${base}${streamPath}?ticket=${encodeURIComponent(ticketData.ticket)}`
        const es = new EventSource(url)
        esRef.current = es

        es.onopen = () => {
          setStatus('connected')
        }
        es.onerror = () => {
          // The ticket is single-use, so the browser's built-in EventSource
          // auto-reconnect (same URL, now-dead ticket) would fail forever.
          // Close it ourselves and reconnect with a freshly-issued ticket.
          setStatus('error')
          es.close()
          if (esRef.current === es) esRef.current = null
          if (!cancelled) {
            retryTimer = setTimeout(() => {
              void connect()
            }, 3000)
          }
        }
        es.onmessage = (e: MessageEvent<string>) => {
          try {
            setData(JSON.parse(e.data) as T)
            setStatus('connected')
          } catch {
            // ignore malformed frames
          }
        }
      } catch {
        if (!cancelled) {
          setStatus('error')
          retryTimer = setTimeout(() => {
            void connect()
          }, 3000)
        }
      }
    }

    void connect()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      esRef.current?.close()
      esRef.current = null
      setStatus('closed')
    }
  }, [ticketPath, streamPath, enabled])

  /** Manually close the connection */
  const close = () => {
    esRef.current?.close()
    setStatus('closed')
  }

  return { data, status, close }
}
