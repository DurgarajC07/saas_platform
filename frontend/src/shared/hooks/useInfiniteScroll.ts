import { useCallback, useEffect, useRef } from 'react'

/**
 * Attaches an IntersectionObserver to a sentinel element.
 * Calls `onIntersect` when the sentinel enters the viewport.
 *
 * Usage:
 *   const ref = useInfiniteScroll({ onIntersect: fetchNextPage, enabled: hasNextPage })
 *   <div ref={ref} />
 */
export function useInfiniteScroll({
  onIntersect,
  enabled = true,
  threshold = 0.1,
}: {
  onIntersect: () => void
  enabled?: boolean
  threshold?: number
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const cb = useCallback(onIntersect, [onIntersect])

  useEffect(() => {
    if (!enabled || !sentinelRef.current) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) cb()
      },
      { threshold },
    )
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [enabled, threshold, cb])

  return sentinelRef
}
