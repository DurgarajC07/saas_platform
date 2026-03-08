import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/features/auth/store'
import { normalizeError } from './error-handler'

// ─────────────────────────────────────────────────────────────────────────────
// Singleton Axios instance — the ONLY place HTTP config lives
// ─────────────────────────────────────────────────────────────────────────────
export const apiClient = axios.create({
  baseURL: (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1',
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── Request interceptor: inject Authorization + X-Org-ID ────────────────────
apiClient.interceptors.request.use((config) => {
  const { token, orgId } = useAuthStore.getState()
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (orgId) config.headers['X-Org-ID'] = orgId
  return config
})

// ── Response interceptor: handle 401 → refresh → retry once ─────────────────
let _refreshPromise: Promise<string> | null = null

apiClient.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true

      try {
        // Deduplicate concurrent refresh calls
        if (!_refreshPromise) {
          _refreshPromise = doRefresh().finally(() => {
            _refreshPromise = null
          })
        }
        const newToken = await _refreshPromise
        original.headers.Authorization = `Bearer ${newToken}`
        return await apiClient(original)
      } catch {
        // Refresh failed → force logout
        useAuthStore.getState().logout()
        window.location.href = '/auth/login'
        const apiErr = normalizeError(error)
        return Promise.reject(Object.assign(new Error(apiErr.message), apiErr))
      }
    }

    const apiErr = normalizeError(error)
    return Promise.reject(Object.assign(new Error(apiErr.message), apiErr))
  },
)

async function doRefresh(): Promise<string> {
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) return Promise.reject(new Error('No refresh token'))

  const { data } = await axios.post<{ accessToken: string; refreshToken: string }>(
    `${(import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1'}/auth/refresh`,
    { refreshToken },
  )
  useAuthStore.getState().setTokens(data.accessToken, data.refreshToken)
  return data.accessToken
}

export default apiClient
