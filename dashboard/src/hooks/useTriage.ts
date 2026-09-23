import { useCallback, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { useToast } from '../components/Toast'
import { useAppData } from '../state/AppData'
import type { Status, TriageAction, Violation } from '../types'
import type { usePaginatedViolations } from './usePaginatedViolations'

type List = ReturnType<typeof usePaginatedViolations>

const LEAVE_MS = 300

const CLEARED = { acknowledged_by: null, acknowledged_at: null, snooze_until: null, exempt_reason: null }

/**
 * Triage actions for a list of violation cards.
 *
 * Each action: marks the card busy, calls the API, then animates the card out of
 * the list if it no longer matches the filter (or updates it in place), refreshes
 * the counts, and shows a toast. Actions taken on an OPEN finding offer Undo,
 * which reopens it and puts the card back where it was. Failures leave the card
 * untouched and explain what went wrong.
 */
export function useTriage(list: List) {
  const toast = useToast()
  const { countsChanged } = useAppData()
  const [busy, setBusy]       = useState<ReadonlySet<string>>(new Set())
  const [leaving, setLeaving] = useState<ReadonlySet<string>>(new Set())

  const setIn = (set: React.Dispatch<React.SetStateAction<ReadonlySet<string>>>, id: string, on: boolean) =>
    set((prev) => { const next = new Set(prev); if (on) next.add(id); else next.delete(id); return next })

  const settle = useCallback((id: string, patch: Partial<Violation> & { status: Status }) => {
    if (list.matches(patch.status)) {
      list.applyStatusChange(id, patch)
      return
    }
    setIn(setLeaving, id, true)
    window.setTimeout(() => {
      list.applyStatusChange(id, patch)
      setIn(setLeaving, id, false)
    }, LEAVE_MS)
  }, [list])

  const undo = useCallback(async (original: Violation, index: number) => {
    try {
      await api.reopen(original.violation_id)
      list.restore({ ...original, ...CLEARED, status: 'OPEN' }, index)
      countsChanged()
      toast({ tone: 'info', title: 'Reverted', detail: `${original.rule_name} is open again.` })
    } catch (e) {
      toast({ tone: 'error', title: 'Couldn\'t undo', detail: errorMessage(e) })
    }
  }, [list, countsChanged, toast])

  const run = useCallback(async (
    v: Violation,
    action: TriageAction,
    arg?: number | string,
  ) => {
    if (busy.has(v.violation_id)) return
    const index = list.violations.findIndex((x) => x.violation_id === v.violation_id)
    setIn(setBusy, v.violation_id, true)

    let patch: Partial<Violation> & { status: Status }
    let title: string
    try {
      switch (action) {
        case 'acknowledge':
          await api.acknowledge(v.violation_id)
          patch = { status: 'ACKNOWLEDGED', acknowledged_by: 'dashboard-user', acknowledged_at: new Date().toISOString() }
          title = 'Acknowledged'
          break
        case 'snooze': {
          const days = Number(arg ?? 7)
          await api.snooze(v.violation_id, days)
          patch = { status: 'SNOOZED', snooze_until: new Date(Date.now() + days * 86_400_000).toISOString() }
          title = `Snoozed for ${days === 1 ? '1 day' : `${days} days`}`
          break
        }
        case 'exempt':
          await api.exempt(v.violation_id, String(arg ?? ''))
          patch = { status: 'EXEMPTED', exempt_reason: String(arg ?? '') }
          title = 'Exempted'
          break
        case 'reopen':
          await api.reopen(v.violation_id)
          patch = { ...CLEARED, status: 'OPEN' }
          title = 'Reopened'
          break
      }
    } catch (e) {
      toast({ tone: 'error', title: `Couldn't ${action} this finding`, detail: errorMessage(e) })
      return
    } finally {
      setIn(setBusy, v.violation_id, false)
    }

    settle(v.violation_id, patch)
    countsChanged()
    toast({
      tone: 'success',
      title,
      detail: `${v.rule_name} · ${v.resource_id.length > 48 ? `…${v.resource_id.slice(-46)}` : v.resource_id}`,
      action: v.status === 'OPEN' && action !== 'reopen'
        ? { label: 'Undo', run: () => undo(v, index) }
        : undefined,
    })
  }, [busy, list, settle, countsChanged, toast, undo])

  return { run, busy, leaving }
}
