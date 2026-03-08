import { useState } from 'react'

interface PaginationState {
  page:     number
  pageSize: number
}

interface PaginationActions {
  setPage:     (page: number) => void
  setPageSize: (size: number) => void
  nextPage:    () => void
  prevPage:    () => void
  reset:       () => void
}

export function usePagination(
  initialPage     = 1,
  initialPageSize = 20,
): PaginationState & PaginationActions {
  const [page, setPage]         = useState(initialPage)
  const [pageSize, setPageSize] = useState(initialPageSize)

  return {
    page,
    pageSize,
    setPage,
    setPageSize: (size) => { setPageSize(size); setPage(1) },
    nextPage:    () => setPage((p) => p + 1),
    prevPage:    () => setPage((p) => Math.max(1, p - 1)),
    reset:       () => setPage(1),
  }
}
