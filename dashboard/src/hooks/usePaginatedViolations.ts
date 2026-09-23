import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Status, Violation } from '../types'

export const VIOLATIONS_PAGE_SIZE = 50

interface Filters {
  status?:   string
  severity?: string
  team?:     string
}

/**
 * Cursor-paginated violations list. Changing any filter discards loaded pages and
 * starts again from the first page; `loadMore` appends the next page using the
 * server's `next_cursor`. Responses from superseded filter sets are ignored.
 */
export function usePaginatedViolations(filters: Filters, opts: { enabled?: boolean; pageSize?: number } = {}) {
  const { enabled = true, pageSize = VIOLATIONS_PAGE_SIZE } = opts
  const { status, severity, team } = filters

  const [violations, setViolations] = useState<Violation[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading]       = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError]           = useState<string | null>(null)

  // Bumped on every reset so in-flight responses for old filters are dropped.
  const generation = useRef(0)

  const reset = useCallback(async () => {
    const gen = ++generation.current
    setLoading(true)
    setLoadingMore(false)
    setError(null)
    setViolations([])
    setNextCursor(null)
    try {
      const data = await api.listViolations({ status, severity, team, limit: pageSize })
      if (gen !== generation.current) return
      setViolations(data.violations)
      setNextCursor(data.next_cursor)
    } catch (e) {
      if (gen === generation.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (gen === generation.current) setLoading(false)
    }
  }, [status, severity, team, pageSize])

  useEffect(() => {
    if (enabled) reset()
  }, [enabled, reset])

  const loadMore = useCallback(async () => {
    if (!nextCursor || loading || loadingMore) return
    const gen = generation.current
    setLoadingMore(true)
    setError(null)
    try {
      const data = await api.listViolations({ status, severity, team, limit: pageSize, cursor: nextCursor })
      if (gen !== generation.current) return
      setViolations((prev) => {
        const seen = new Set(prev.map((v) => v.pk))
        return [...prev, ...data.violations.filter((v) => !seen.has(v.pk))]
      })
      setNextCursor(data.next_cursor)
    } catch (e) {
      if (gen === generation.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (gen === generation.current) setLoadingMore(false)
    }
  }, [nextCursor, loading, loadingMore, status, severity, team, pageSize])

  /**
   * Reflect a triage action locally instead of refetching, so already-loaded pages
   * aren't thrown away. Items that no longer match the status filter (or were
   * exempted) are removed from the list.
   */
  const applyStatusChange = useCallback((violationId: string, patch: Partial<Violation> & { status: Status }) => {
    setViolations((prev) => prev.flatMap((v) => {
      if (v.violation_id !== violationId) return [v]
      const hidden = patch.status === 'RESOLVED' || patch.status === 'EXEMPTED' || (!!status && status !== patch.status)
      return hidden ? [] : [{ ...v, ...patch }]
    }))
  }, [status])

  return {
    violations,
    loading,
    loadingMore,
    error,
    hasMore: nextCursor !== null,
    loadMore,
    reload: reset,
    applyStatusChange,
  }
}
