import { useQuery }     from '@tanstack/react-query'
import { apiClient }    from '@/shared/api/client'
import { queryKeys }    from '@/shared/api/query-keys'

interface FeatureCheckResult {
  featureKey: string
  enabled:    boolean
  limit:      number | null
}

export function useFeatureFlag(key: string) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.features.check(key),
    queryFn: async (): Promise<FeatureCheckResult> => {
      const { data } = await apiClient.get('/features/check', { params: { key } })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })

  return {
    enabled:   data?.enabled ?? false,
    limit:     data?.limit   ?? null,
    isLoading,
  }
}
