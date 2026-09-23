import { useEffect, useRef } from 'react'
import type { usePaginatedViolations } from '../hooks/usePaginatedViolations'
import { useTriage } from '../hooks/useTriage'
import { SEV_STYLE } from '../lib/catalog'
import { plural } from '../lib/format'
import { SEVERITIES, type Severity, type Violation } from '../types'
import { Icon, Spinner } from './Icon'
import { ErrorState, ListSkeleton } from './States'
import { ViolationCard } from './ViolationCard'

type List = ReturnType<typeof usePaginatedViolations>

interface Props {
  list: List
  /** Client-side text filter over the loaded items. */
  query?: string
  empty: React.ReactNode
  defaultFixOpen?: boolean
}

function matchesQuery(v: Violation, q: string): boolean {
  const hay = `${v.rule_id} ${v.rule_name} ${v.resource_id} ${v.reason} ${v.team} ${v.account_id}`.toLowerCase()
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((t) => hay.includes(t))
}

export function ViolationList({ list, query = '', empty, defaultFixOpen }: Props) {
  const triage   = useTriage(list)
  const sentinel = useRef<HTMLDivElement>(null)
  const { hasMore, loadMore, loadingMore, loadMoreError } = list

  // Infinite scroll: fetch the next page as the end of the list comes into view.
  useEffect(() => {
    const el = sentinel.current
    if (!el || !hasMore || loadMoreError) return
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) void loadMore()
    }, { rootMargin: '600px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [hasMore, loadMore, loadMoreError])

  if (list.loading) return <ListSkeleton />
  if (list.error)   return <ErrorState title="Couldn't load findings" detail={list.error} onRetry={list.reload} />

  const items = query.trim() ? list.violations.filter((v) => matchesQuery(v, query)) : list.violations
  if (list.violations.length === 0) return <>{empty}</>

  const grouped: Record<Severity, Violation[]> = { CRITICAL: [], HIGH: [], MEDIUM: [], LOW: [] }
  for (const v of items) grouped[v.severity]?.push(v)

  return (
    <div className="space-y-7">
      {query.trim() && items.length === 0 && (
        <p className="animate-fade-in py-10 text-center text-sm text-muted">
          Nothing in the {plural(list.violations.length, 'loaded finding')} matches “{query.trim()}”.
          {hasMore && ' More findings are available below — load them to widen the search.'}
        </p>
      )}

      {SEVERITIES.map((sev) => {
        const group = grouped[sev]
        if (!group.length) return null
        const s = SEV_STYLE[sev]
        return (
          <section key={sev} aria-labelledby={`sev-${sev}`}>
            <div className="sticky top-0 z-[5] -mx-1 mb-3 flex items-center gap-3 bg-bg/80 px-1 py-2 backdrop-blur-md">
              <span className="h-2 w-2 rounded-full" style={{ background: s.color, boxShadow: `0 0 10px ${s.color}` }} />
              <h2 id={`sev-${sev}`} className="text-[11px] font-bold uppercase tracking-[0.16em]" style={{ color: s.color }}>
                {s.label}
              </h2>
              <span className="rounded px-1.5 py-0.5 text-[10px] font-bold tabular" style={{ background: `rgba(${s.rgb},0.12)`, color: s.color }}>
                {group.length}
              </span>
              <span className="h-px flex-1" style={{ background: `linear-gradient(90deg, rgba(${s.rgb},0.35) 0%, transparent 80%)` }} />
            </div>
            <div className="stagger space-y-3">
              {group.map((v) => (
                <ViolationCard
                  key={v.pk}
                  violation={v}
                  busy={triage.busy.has(v.violation_id)}
                  leaving={triage.leaving.has(v.violation_id)}
                  onAction={triage.run}
                  defaultFixOpen={defaultFixOpen}
                />
              ))}
            </div>
          </section>
        )
      })}

      <div ref={sentinel} className="flex flex-col items-center gap-2 pb-6 pt-1">
        {loadMoreError && (
          <p role="alert" className="text-xs text-critical">Couldn't load more: {loadMoreError}</p>
        )}
        {hasMore ? (
          <button className="btn btn-secondary" onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? <><Spinner size={12} /> Loading…</> : loadMoreError ? <><Icon name="refresh" size={12} /> Retry</> : 'Load more'}
          </button>
        ) : (
          <p className="flex items-center gap-1.5 text-[11px] text-faint">
            <Icon name="check" size={11} /> That's everything · {plural(list.violations.length, 'finding')}
          </p>
        )}
      </div>
    </div>
  )
}
