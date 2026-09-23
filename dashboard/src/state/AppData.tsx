import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useToast } from '../components/Toast'
import type { Summary } from '../types'

const AUTO_REFRESH_MS = 60_000
// After an audit is queued, re-read the summary a few times while it runs.
const AUDIT_POLL_MS   = [4_000, 10_000, 25_000]

/**
 * What the connected backend supports. The dashboard can be deployed ahead of
 * (or without) the matching API; rather than erroring, it hides what the server
 * can't do. /summary's `by_severity_status` shipped together with `reopen` and
 * `/trend`, so it marks a backend that has all three.
 */
export interface Features {
  reopen:  boolean
  trend:   boolean
  lastRun: boolean
}

interface AppData {
  features:     Features
  summary:      Summary | null
  summaryError: string | null
  lastUpdated:  number | null
  refreshing:   boolean
  /** Bumped whenever data may have changed server-side; lists re-fetch on change. */
  dataVersion:  number
  refresh:      () => Promise<void>
  /** Call after a triage action: refreshes counts without reloading lists. */
  countsChanged: () => void
  triggerAudit: () => Promise<void>
  auditRunning: boolean
}

const Ctx = createContext<AppData | null>(null)

export function useAppData(): AppData {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAppData must be used inside <AppDataProvider>')
  return v
}

export function AppDataProvider({ children }: { children: React.ReactNode }) {
  const toast = useToast()
  const [summary, setSummary]           = useState<Summary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated]   = useState<number | null>(null)
  const [refreshing, setRefreshing]     = useState(false)
  const [dataVersion, setDataVersion]   = useState(0)
  const [auditRunning, setAuditRunning] = useState(false)
  const inflight = useRef<Promise<void> | null>(null)
  const again    = useRef(false)

  // One summary request at a time. A request made while one is in flight can't
  // just share it: that response may predate the change being reported (e.g. a
  // triage action), so it queues exactly one more fetch after the current one.
  const loadSummary = useCallback(async (): Promise<void> => {
    if (inflight.current) {
      again.current = true
      return inflight.current
    }
    inflight.current = (async () => {
      setRefreshing(true)
      try {
        do {
          again.current = false
          try {
            setSummary(await api.getSummary())
            setSummaryError(null)
            setLastUpdated(Date.now())
          } catch (e) {
            setSummaryError(errorMessage(e))
          }
        } while (again.current)
      } finally {
        setRefreshing(false)
        inflight.current = null
      }
    })()
    return inflight.current
  }, [])

  const refresh = useCallback(async () => {
    setDataVersion((v) => v + 1)
    await loadSummary()
  }, [loadSummary])

  // Initial load, then refresh the counts periodically while the tab is visible,
  // and immediately when the user comes back to it. Lists aren't reloaded on a
  // timer (that would yank the page from under the reader); they reload on an
  // explicit refresh or when an audit finishes.
  useEffect(() => {
    void loadSummary()
    const tick = () => { if (document.visibilityState === 'visible') void loadSummary() }
    const timer = window.setInterval(tick, AUTO_REFRESH_MS)
    const onVisible = () => { if (document.visibilityState === 'visible') tick() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [loadSummary])

  const countsChanged = useCallback(() => { void loadSummary() }, [loadSummary])

  const triggerAudit = useCallback(async () => {
    setAuditRunning(true)
    try {
      await api.triggerAudit()
      toast({ tone: 'info', title: 'Audit queued', detail: 'Results will appear here as the scan finishes.' })
      // The audit runs asynchronously: poll the counts while it works, then
      // reload the lists once at the end so they don't reset repeatedly.
      for (const wait of AUDIT_POLL_MS.slice(0, -1)) {
        await new Promise((r) => setTimeout(r, wait))
        await loadSummary()
      }
      await new Promise((r) => setTimeout(r, AUDIT_POLL_MS[AUDIT_POLL_MS.length - 1] - AUDIT_POLL_MS[AUDIT_POLL_MS.length - 2]))
      await refresh()
    } catch (e) {
      toast({ tone: 'error', title: 'Couldn\'t start the audit', detail: errorMessage(e) })
    } finally {
      setAuditRunning(false)
    }
  }, [refresh, toast])

  const features = useMemo<Features>(() => ({
    // Until the first summary arrives, assume the current API (no flicker).
    reopen:  !summary || summary.by_severity_status !== undefined,
    trend:   !summary || summary.by_severity_status !== undefined,
    lastRun: !summary || summary.last_run !== undefined,
  }), [summary])

  const value = useMemo<AppData>(() => ({
    features, summary, summaryError, lastUpdated, refreshing, dataVersion,
    refresh, countsChanged, triggerAudit, auditRunning,
  }), [features, summary, summaryError, lastUpdated, refreshing, dataVersion, refresh, countsChanged, triggerAudit, auditRunning])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Active (open + acknowledged + snoozed) count per severity, from the summary. */
export function activeBySeverity(summary: Summary | null): { counts: Record<string, number>; exact: boolean } {
  const counts: Record<string, number> = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
  if (!summary) return { counts, exact: true }
  if (summary.by_severity_status) {
    for (const [sev, row] of Object.entries(summary.by_severity_status)) {
      counts[sev] = (row.OPEN ?? 0) + (row.ACKNOWLEDGED ?? 0) + (row.SNOOZED ?? 0)
    }
    return { counts, exact: true }
  }
  // Older backend: only all-time counts per severity are available.
  return { counts: { ...counts, ...summary.by_severity }, exact: false }
}
