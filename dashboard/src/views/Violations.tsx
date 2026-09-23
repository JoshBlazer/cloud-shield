import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { PageHeader, Segmented } from '../components/PageHeader'
import { ScanHealthBanner } from '../components/ScanHealth'
import { EmptyState } from '../components/States'
import { ViolationList } from '../components/ViolationList'
import { usePaginatedViolations } from '../hooks/usePaginatedViolations'
import { SEV_STYLE, STATUS_STYLE } from '../lib/catalog'
import { useAppData } from '../state/AppData'
import { SEVERITIES, type Severity } from '../types'

const STATUS_TABS = ['OPEN', 'ACKNOWLEDGED', 'SNOOZED', 'EXEMPTED', 'RESOLVED', 'ALL'] as const
type StatusTab = typeof STATUS_TABS[number]

const EMPTY_COPY: Record<StatusTab, { title: string; detail: string; tone: 'good' | 'neutral' }> = {
  OPEN:         { title: 'No open findings', detail: 'Everything the auditor found has been triaged or fixed.', tone: 'good' },
  ACKNOWLEDGED: { title: 'Nothing acknowledged', detail: 'Findings you acknowledge move here while they are being worked on.', tone: 'neutral' },
  SNOOZED:      { title: 'Nothing snoozed', detail: 'Snoozed findings reopen on their own when the snooze ends.', tone: 'neutral' },
  EXEMPTED:     { title: 'No exemptions', detail: 'Exempted findings are still checked every run but never alert.', tone: 'neutral' },
  RESOLVED:     { title: 'Nothing resolved yet', detail: 'Fixed findings show up here once the next audit confirms them.', tone: 'neutral' },
  ALL:          { title: 'No findings', detail: 'The auditor hasn\'t recorded anything yet. Run an audit to scan now.', tone: 'good' },
}

export function Violations() {
  const [params, setParams] = useSearchParams()
  const { summary } = useAppData()
  const searchRef = useRef<HTMLInputElement>(null)

  // Filters live in the URL so views are shareable and Back works.
  const rawStatus = (params.get('status') ?? 'OPEN').toUpperCase()
  const status    = (STATUS_TABS as readonly string[]).includes(rawStatus) ? rawStatus as StatusTab : 'OPEN'
  const rawSev    = (params.get('severity') ?? '').toUpperCase()
  const severity  = (SEVERITIES as string[]).includes(rawSev) ? rawSev as Severity : ''
  const query     = params.get('q') ?? ''

  const update = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    setParams(next, { replace: true })
  }

  const list = usePaginatedViolations({
    status:   status === 'ALL' ? undefined : status,
    severity: severity || undefined,
  })

  // "/" focuses search, like most dashboards.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) && !t.isContentEditable) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const tabCount = (s: StatusTab) =>
    !summary ? undefined : s === 'ALL' ? summary.total : (summary.by_status[s] ?? 0)

  const loaded   = list.violations.length
  const subtitle = list.loading
    ? 'Loading…'
    : `${loaded.toLocaleString()}${list.hasMore ? '+' : ''} ${STATUS_STYLE[status]?.label.toLowerCase() ?? ''} finding${loaded === 1 && !list.hasMore ? '' : 's'}${severity ? ` · ${SEV_STYLE[severity].label.toLowerCase()} severity` : ''}`

  const empty = EMPTY_COPY[status]

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader title="Findings" subtitle={subtitle}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <Segmented
            label="Status"
            value={status}
            onChange={(v) => update({ status: v === 'OPEN' ? '' : v.toLowerCase() })}
            options={STATUS_TABS.map((s) => ({
              value: s,
              label: s === 'ALL' ? 'All' : STATUS_STYLE[s].label,
              count: tabCount(s),
              color: s === 'ALL' ? '#60a5fa' : STATUS_STYLE[s].color,
            }))}
          />

          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
            <div role="group" aria-label="Severity" className="flex flex-wrap gap-1.5">
              {SEVERITIES.map((s) => {
                const on = severity === s
                const st = SEV_STYLE[s]
                return (
                  <button
                    key={s}
                    aria-pressed={on}
                    onClick={() => update({ severity: on ? '' : s.toLowerCase() })}
                    className="chip"
                    style={on
                      ? { color: st.color, borderColor: `rgba(${st.rgb},0.5)`, background: `rgba(${st.rgb},0.14)`, boxShadow: `0 0 12px rgba(${st.rgb},0.15)` }
                      : { color: '#9aa3b5', borderColor: 'rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.02)' }}
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: st.color }} />
                    {st.label}
                  </button>
                )
              })}
            </div>

            <label className="relative block w-full sm:w-64">
              <span className="sr-only">Search loaded findings</span>
              <Icon name="search" size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(e) => update({ q: e.target.value })}
                placeholder="Search rule, resource, team…"
                className="input h-9 py-0 pl-9 pr-9 text-xs"
              />
              {!query && (
                <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-white/10 px-1.5 text-[10px] text-faint sm:block">/</kbd>
              )}
            </label>
          </div>
        </div>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-4 pb-10 pt-4 sm:px-6">
        <div className="mx-auto max-w-5xl">
          <ScanHealthBanner />
          <ViolationList
            list={list}
            query={query}
            empty={
              severity
                ? <EmptyState tone="neutral" icon="search" title={`No ${SEV_STYLE[severity].label.toLowerCase()} ${status === 'ALL' ? '' : STATUS_STYLE[status].label.toLowerCase()} findings`}
                    detail="Try another severity or status."
                    action={<button className="btn btn-secondary" onClick={() => update({ severity: '' })}>Clear severity filter</button>} />
                : <EmptyState tone={empty.tone} icon={empty.tone === 'good' ? 'check' : 'info'} title={empty.title} detail={empty.detail} />
            }
          />
        </div>
      </div>
    </div>
  )
}
