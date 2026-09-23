import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useAppData } from '../state/AppData'
import type { Status, Violation } from '../types'

export const VIOLATIONS_PAGE_SIZE = 50

interface Filters {
  status?:   string
  severity?: string
  team?:     string
}

/**
 * Cursor-paginated violations list.
 *
 * - Changing a filter discards loaded pages and starts again from the first page.
 * - `loadMore` appends the next page using the server's `next_cursor`.
 * - When app data is refreshed (refresh button, finished audit) the first page is
 *   re-fetched in the background: the current list stays on screen until the new
 *   one arrives, so there's no flash of skeletons.
 * - Responses from superseded requests are ignored.
 */
export function usePaginatedViolations(filters: Filters, opts: { enabled?: boolean; pageSize?: number } = {}) {
  const { enabled = true, pageSize = VIOLATIONS_PAGE_SIZE } = opts
  const { status, severity, team } = filters
  const { dataVersion } = useAppData()

  const [violations, setViolations]   = useState<Violation[]>([])
  const [nextCursor, setNextCursor]   = useState<string | null>(null)
  const [loading, setLoading]         = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)

  const generation = useRef(0)
  const hasData    = useRef(false)

  const load = useCallback(async (background: boolean) => {
    const gen = ++generation.current
    if (!background) {
      setLoading(true)
      setViolations([])
      setNextCursor(null)
      hasData.current = false
    }
    setLoadingMore(false)
    setError(null)
    setLoadMoreError(null)
    try {
      const data = await api.listViolations({ status, severity, team, limit: pageSize })
      if (gen !== generation.current) return
      setViolations(data.violations)
      setNextCursor(data.next_cursor)
      hasData.current = true
    } catch (e) {
      if (gen === generation.current && !(background && hasData.current)) setError(errorMessage(e))
    } finally {
      if (gen === generation.current) setLoading(false)
    }
  }, [status, severity, team, pageSize])

  // Filters changed (or first mount): full reload.
  useEffect(() => { if (enabled) void load(false) }, [enabled, load])

  // Data refreshed elsewhere: quiet background reload.
  const firstVersion = useRef(dataVersion)
  useEffect(() => {
    if (dataVersion === firstVersion.current) return
    if (enabled) void load(hasData.current)
  }, [dataVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(async () => {
    if (!nextCursor || loading || loadingMore) return
    const gen = generation.current
    setLoadingMore(true)
    setLoadMoreError(null)
    try {
      const data = await api.listViolations({ status, severity, team, limit: pageSize, cursor: nextCursor })
      if (gen !== generation.current) return
      setViolations((prev) => {
        const seen = new Set(prev.map((v) => v.pk))
        return [...prev, ...data.violations.filter((v) => !seen.has(v.pk))]
      })
      setNextCursor(data.next_cursor)
    } catch (e) {
      if (gen === generation.current) setLoadMoreError(errorMessage(e))
    } finally {
      if (gen === generation.current) setLoadingMore(false)
    }
  }, [nextCursor, loading, loadingMore, status, severity, team, pageSize])

  /** Does an item with this status still belong in the current list? */
  const matches = useCallback((s: Status) => !status || status === s, [status])
  // Undo can fire seconds later, after the user switched filters; always judge
  // against the filter that's current *then*, not when the toast was created.
  const matchesRef = useRef(matches)
  matchesRef.current = matches

  /**
   * Reflect a triage action locally instead of refetching, so already-loaded pages
   * aren't thrown away. Items that no longer match the status filter are removed.
   */
  const applyStatusChange = useCallback((violationId: string, patch: Partial<Violation> & { status: Status }) => {
    setViolations((prev) => prev.flatMap((v) => {
      if (v.violation_id !== violationId) return [v]
      return matches(patch.status) ? [{ ...v, ...patch }] : []
    }))
  }, [matches])

  /**
   * Put an item back (e.g. after Undo) at its previous position, or update it in
   * place if it's still listed. Dropped if it no longer matches the filter.
   */
  const restore = useCallback((item: Violation, index: number) => {
    setViolations((prev) => {
      if (!matchesRef.current(item.status)) return prev.filter((v) => v.violation_id !== item.violation_id)
      const without = prev.filter((v) => v.violation_id !== item.violation_id)
      const at = Math.max(0, Math.min(index, without.length))
      return [...without.slice(0, at), item, ...without.slice(at)]
    })
  }, [])

  return {
    violations,
    loading,
    loadingMore,
    error,
    loadMoreError,
    hasMore: nextCursor !== null,
    loadMore,
    reload: () => load(false),
    applyStatusChange,
    restore,
    matches,
  }
}
