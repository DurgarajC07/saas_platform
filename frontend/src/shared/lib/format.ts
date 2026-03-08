const LOCALE = 'en-US'

/** "$1,234.56" */
export function formatCurrency(
  amount: number,
  currency = 'USD',
  maximumFractionDigits = 2,
): string {
  return new Intl.NumberFormat(LOCALE, {
    style: 'currency',
    currency,
    maximumFractionDigits,
  }).format(amount / 100) // assumes amounts stored in cents
}

/** 90 → "1m 30s" */
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

/** 1536 → "1.5 KB" */
export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 B'
  const k     = 1024
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i     = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${units[i]}`
}

/** 0.8753 → "87.5%" */
export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

/** 12345 → "12,345" */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat(LOCALE).format(value)
}

/** 12345 → "12.3K" */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat(LOCALE, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}
