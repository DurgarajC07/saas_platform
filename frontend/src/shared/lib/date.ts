/**
 * Lightweight date helpers — no heavy dependency required.
 * Swap out for date-fns if needed.
 */

const LOCALE = 'en-US'

/** "Jan 15, 2025" */
export function formatDate(value: string | Date): string {
  return new Intl.DateTimeFormat(LOCALE, {
    year: 'numeric', month: 'short', day: 'numeric',
  }).format(new Date(value))
}

/** "Jan 15, 2025, 3:45 PM" */
export function formatDateTime(value: string | Date): string {
  return new Intl.DateTimeFormat(LOCALE, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  }).format(new Date(value))
}

/** "3:45 PM" */
export function formatTime(value: string | Date): string {
  return new Intl.DateTimeFormat(LOCALE, {
    hour: 'numeric', minute: '2-digit',
  }).format(new Date(value))
}

/** "2 hours ago", "in 3 days", etc. */
export function formatRelative(value: string | Date): string {
  const diff = new Date(value).getTime() - Date.now()
  const abs  = Math.abs(diff)
  const rtf  = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' })

  if (abs < 60_000)      return rtf.format(Math.round(diff / 1_000),   'second')
  if (abs < 3_600_000)   return rtf.format(Math.round(diff / 60_000),  'minute')
  if (abs < 86_400_000)  return rtf.format(Math.round(diff / 3_600_000), 'hour')
  if (abs < 2_592_000_000) return rtf.format(Math.round(diff / 86_400_000), 'day')
  return formatDate(value)
}

/** 90 → "1m 30s" */
export function formatDurationSecs(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  if (m === 0) return `${s}s`
  if (s === 0) return `${m}m`
  return `${m}m ${s}s`
}
