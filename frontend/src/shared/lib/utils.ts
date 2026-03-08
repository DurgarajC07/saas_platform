import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge Tailwind class names safely */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Generate initials from a full name */
export function initials(name: string): string {
  return name
    .split(' ')
    .slice(0, 2)
    .map((n) => n[0])
    .join('')
    .toUpperCase()
}

/** Truncate a string to maxLen characters, appending "…" */
export function truncate(str: string, maxLen: number): string {
  return str.length > maxLen ? `${str.slice(0, maxLen - 1)}…` : str
}

/** Sleep for N milliseconds */
export function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Safely parse JSON; returns null on failure */
export function safeJson<T>(json: string): T | null {
  try { return JSON.parse(json) as T }
  catch { return null }
}
