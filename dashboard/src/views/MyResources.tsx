import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/States'
import { ViolationList } from '../components/ViolationList'
import { usePaginatedViolations } from '../hooks/usePaginatedViolations'
import { useAppData } from '../state/AppData'

/** A team's to-do list: its active findings, with remediation steps open by default. */
export function MyResources() {
  const { summary } = useAppData()
  const [params, setParams] = useSearchParams()

  const teams = useMemo(
    () => Object.entries(summary?.by_team ?? {})
      .map(([name, c]) => ({ name, open: c.OPEN ?? 0, acked: c.ACKNOWLEDGED ?? 0, resolved: c.RESOLVED ?? 0 }))
      .sort((a, b) => b.open - a.open || a.name.localeCompare(b.name)),
    [summary],
  )
  const team    = params.get('team') ?? teams[0]?.name ?? ''
  const current = teams.find((t) => t.name === team)

  const list = usePaginatedViolations({ team, status: 'OPEN' }, { enabled: !!team })

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader title="My resources" subtitle="Open findings for one team, with the steps to fix each one.">
        {teams.length === 0 && !summary ? (
          <div className="flex gap-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-9 w-28 rounded-lg" />)}</div>
        ) : (
          <div role="tablist" aria-label="Team" className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-0.5 sm:mx-0 sm:flex-wrap sm:px-0">
            {teams.map((t) => {
              const active = t.name === team
              return (
                <button
                  key={t.name}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setParams({ team: t.name }, { replace: true })}
                  className={`flex flex-shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-all duration-200
                              ${active
                                ? 'border-violet/40 bg-violet/15 text-violet shadow-[0_0_16px_rgba(167,139,250,0.15)]'
                                : 'border-white/[0.07] bg-white/[0.02] text-muted hover:border-white/15 hover:text-text'}`}
                >
                  {t.name}
                  <span className={`rounded-full px-1.5 text-[10px] font-bold tabular ${t.open ? 'bg-critical/15 text-critical' : 'bg-low/10 text-low'}`}>
                    {t.open}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-4 pb-10 pt-4 sm:px-6">
        <div className="mx-auto max-w-5xl">
          {current && (
            <dl className="mb-5 grid animate-fade-up grid-cols-3 gap-3">
              {[
                { label: 'Open', value: current.open, color: '#f87171' },
                { label: 'Acknowledged', value: current.acked, color: '#60a5fa' },
                { label: 'Resolved', value: current.resolved, color: '#4ade80' },
              ].map((s) => (
                <div key={s.label} className="panel min-w-0 px-3 py-3 sm:px-4">
                  <dt className="eyebrow truncate tracking-[0.08em] sm:tracking-[0.16em]" title={s.label}>{s.label}</dt>
                  <dd className="mt-1 text-2xl font-semibold" style={{ color: s.color }}><AnimatedNumber value={s.value} /></dd>
                </div>
              ))}
            </dl>
          )}
          {team ? (
            <ViolationList
              list={list}
              defaultFixOpen
              empty={<EmptyState title={`${team} is all clear`} detail="No open findings for this team. Nice work." />}
            />
          ) : summary ? (
            <EmptyState tone="neutral" icon="users" title="No teams yet" detail="Findings are grouped by each resource's team tag once the auditor records some." />
          ) : null}
        </div>
      </div>
    </div>
  )
}
