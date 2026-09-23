import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, errorMessage } from '../api/client'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { Icon } from '../components/Icon'
import { PageHeader } from '../components/PageHeader'
import { ScanHealthBanner } from '../components/ScanHealth'
import { ErrorState } from '../components/States'
import { SEV_STYLE, STATUS_STYLE } from '../lib/catalog'
import { shortDate } from '../lib/format'
import { activeBySeverity, useAppData } from '../state/AppData'
import { SEVERITIES, type TrendPoint } from '../types'

const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Share of every finding ever tracked that is no longer active (resolved or exempted). */
function ScoreRing({ score }: { score: number }) {
  const [shown, setShown] = useState(reduceMotion() ? score : 0)
  useEffect(() => { const t = requestAnimationFrame(() => setShown(score)); return () => cancelAnimationFrame(t) }, [score])
  const r = 54, circ = 2 * Math.PI * r
  const color = score >= 75 ? '#4ade80' : score >= 45 ? '#fbbf24' : '#f87171'
  return (
    <div className="relative h-[140px] w-[140px] flex-shrink-0">
      <svg viewBox="0 0 140 140" className="-rotate-90" aria-hidden="true">
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
        <circle
          cx="70" cy="70" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={circ - (circ * shown) / 100}
          style={{ transition: 'stroke-dashoffset 1.1s cubic-bezier(0.16, 1, 0.3, 1), stroke 0.4s', filter: `drop-shadow(0 0 8px ${color}80)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-semibold" style={{ color }}><AnimatedNumber value={score} suffix="%" duration={1100} countUp /></span>
      </div>
    </div>
  )
}

function Bar({ value, max, color, delay = 0 }: { value: number; max: number; color: string; delay?: number }) {
  const [w, setW] = useState(reduceMotion() ? (value / max) * 100 : 0)
  useEffect(() => {
    const t = window.setTimeout(() => setW(max ? (value / max) * 100 : 0), 60 + delay)
    return () => window.clearTimeout(t)
  }, [value, max, delay])
  return (
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
      <div
        className="h-full rounded-full"
        style={{ width: `${w}%`, background: `linear-gradient(90deg, ${color}, ${color}b0)`, boxShadow: `0 0 8px ${color}60`,
                 transition: 'width 0.9s cubic-bezier(0.16, 1, 0.3, 1)' }}
      />
    </div>
  )
}

function TrendTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ dataKey: string; value: number }>; label?: string }) {
  if (!active || !payload?.length || !label) return null
  const total = payload.reduce((n, p) => n + (p.value ?? 0), 0)
  return (
    <div className="rounded-lg border border-white/10 bg-raised px-3 py-2 text-xs shadow-2xl">
      <p className="mb-1.5 font-semibold text-text">{shortDate(label)} · {total} active</p>
      {[...payload].reverse().map((p) => (
        <p key={p.dataKey} className="flex items-center gap-2 text-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: SEV_STYLE[p.dataKey as keyof typeof SEV_STYLE]?.color }} />
          <span className="flex-1">{SEV_STYLE[p.dataKey as keyof typeof SEV_STYLE]?.label}</span>
          <span className="font-semibold text-text tabular">{p.value}</span>
        </p>
      ))}
    </div>
  )
}

function TrendPanel() {
  const { dataVersion, features } = useAppData()
  const [days, setDays]   = useState(14)
  const [data, setData]   = useState<TrendPoint[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!features.trend) return
    let live = true
    setError(null)
    api.getTrend(days)
      .then((r) => { if (live) setData(r.days) })
      .catch((e) => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [days, dataVersion, attempt, features.trend])

  const first = data?.[0]?.total_active ?? 0
  const last  = data?.[data.length - 1]?.total_active ?? 0
  const delta = last - first

  return (
    <section className="panel p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="panel-title">Active findings over time</h2>
          {data && data.length > 1 && (
            <p className="mt-0.5 flex items-center gap-1 text-xs text-muted">
              <span className={delta <= 0 ? 'text-low' : 'text-critical'}>
                {delta === 0 ? 'No change' : `${delta < 0 ? '▼' : '▲'} ${Math.abs(delta)}`}
              </span>
              over the last {data.length} days
            </p>
          )}
        </div>
        <div role="group" aria-label="Range" className="flex gap-0.5 rounded-lg border border-white/[0.06] bg-white/[0.03] p-0.5">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              aria-pressed={days === d}
              onClick={() => setDays(d)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors ${days === d ? 'bg-accent/15 text-accent' : 'text-muted hover:text-text'}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {!features.trend ? (
        <div className="flex h-[240px] flex-col items-center justify-center text-center">
          <Icon name="chart" size={22} className="mb-3 text-faint" />
          <p className="text-sm font-medium text-subtle">Trend history needs the latest API</p>
          <p className="mt-1 max-w-xs text-xs text-muted">Deploy the current backend (<code className="font-mono">make release</code>); daily snapshots start with its first audit.</p>
        </div>
      ) : error ? (
        <ErrorState title="Couldn't load the trend" detail={error} onRetry={() => { setData(null); setAttempt((n) => n + 1) }} />
      ) : !data ? (
        <div className="skeleton h-[240px] w-full" />
      ) : data.length < 2 ? (
        <div className="flex h-[240px] flex-col items-center justify-center text-center">
          <Icon name="chart" size={22} className="mb-3 text-faint" />
          <p className="text-sm font-medium text-subtle">Not enough history yet</p>
          <p className="mt-1 max-w-xs text-xs text-muted">The auditor records one snapshot per day. The chart fills in after a couple of runs.</p>
        </div>
      ) : (
        <div className="h-[240px] animate-fade-in">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 5, right: 4, bottom: 0, left: -18 }}>
              <defs>
                {SEVERITIES.map((s) => (
                  <linearGradient key={s} id={`g-${s}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={SEV_STYLE[s].color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={SEV_STYLE[s].color} stopOpacity={0.02} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: '#8a94a8', fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis allowDecimals={false} tick={{ fill: '#8a94a8', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<TrendTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.15)', strokeDasharray: '3 3' }} />
              {[...SEVERITIES].reverse().map((s) => (
                <Area
                  key={s} type="monotone" dataKey={s} stackId="1"
                  stroke={SEV_STYLE[s].color} strokeWidth={1.75} fill={`url(#g-${s})`}
                  animationDuration={reduceMotion() ? 0 : 900}
                  activeDot={{ r: 4, strokeWidth: 0, fill: SEV_STYLE[s].color }}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {SEVERITIES.map((s) => (
          <span key={s} className="flex items-center gap-1.5 text-[11px] text-muted">
            <span className="h-2 w-2 rounded-sm" style={{ background: SEV_STYLE[s].color }} />{SEV_STYLE[s].label}
          </span>
        ))}
      </div>
    </section>
  )
}

export function Posture() {
  const { summary, summaryError, refresh } = useAppData()

  if (summaryError && !summary) {
    return <div className="h-full overflow-y-auto"><ErrorState title="Couldn't load posture" detail={summaryError} onRetry={refresh} /></div>
  }
  if (!summary) {
    return (
      <div className="h-full space-y-5 overflow-hidden p-4 sm:p-6" role="status" aria-label="Loading">
        <div className="skeleton h-8 w-40" />
        <div className="skeleton h-44 w-full rounded-xl" />
        <div className="skeleton h-72 w-full rounded-xl" />
      </div>
    )
  }

  const by = summary.by_status
  const active   = (by.OPEN ?? 0) + (by.ACKNOWLEDGED ?? 0) + (by.SNOOZED ?? 0)
  const closed   = (by.RESOLVED ?? 0) + (by.EXEMPTED ?? 0)
  const score    = summary.total ? Math.round((closed / summary.total) * 100) : 100
  const sev      = activeBySeverity(summary)
  const maxSev   = Math.max(1, ...Object.values(sev.counts))

  const teams = Object.entries(summary.by_team)
    .map(([team, c]) => ({ team, open: c.OPEN ?? 0, acked: c.ACKNOWLEDGED ?? 0, resolved: c.RESOLVED ?? 0 }))
    .sort((a, b) => b.open - a.open || b.acked - a.acked)
  const maxTeam = Math.max(1, ...teams.map((t) => t.open + t.acked + t.resolved))

  const tiles = (['OPEN', 'ACKNOWLEDGED', 'SNOOZED', 'EXEMPTED', 'RESOLVED'] as const).map((s) => ({
    key: s, ...STATUS_STYLE[s], value: by[s] ?? 0,
  }))

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PageHeader title="Posture" subtitle="How your accounts are doing, and whether it's getting better." />
      <div className="flex-1 overflow-y-auto px-4 pb-10 pt-5 sm:px-6">
        <div className="mx-auto max-w-6xl"><ScanHealthBanner /></div>
        <div className="stagger mx-auto max-w-6xl space-y-5">
          {/* Hero: resolution rate + lifecycle tiles */}
          <section className="panel flex flex-col gap-6 p-5 md:flex-row md:items-center">
            <div className="flex items-center gap-5">
              <ScoreRing score={score} />
              <div className="max-w-[220px]">
                <p className="eyebrow">Resolution rate</p>
                <p className="mt-1 text-sm text-subtle">
                  <span className="font-semibold text-text">{closed.toLocaleString()}</span> of {summary.total.toLocaleString()} findings
                  ever tracked are resolved or exempted.
                </p>
                <p className="mt-2 text-xs text-muted">{active.toLocaleString()} still need attention.</p>
              </div>
            </div>
            <div className="hidden h-24 w-px bg-white/[0.06] md:block" />
            <dl className="grid flex-1 grid-cols-2 gap-2.5 sm:grid-cols-5">
              {tiles.map((t) => (
                <Link
                  key={t.key}
                  to={`/violations?status=${t.key.toLowerCase()}`}
                  className="group rounded-xl border px-3 py-3 transition-all duration-200 hover:-translate-y-0.5"
                  style={{ background: `rgba(${t.rgb},0.06)`, borderColor: `rgba(${t.rgb},0.18)` }}
                >
                  <dd className="text-2xl font-semibold" style={{ color: t.color }}><AnimatedNumber value={t.value} countUp /></dd>
                  <dt className="mt-1 flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.12em] text-muted group-hover:text-subtle">
                    {t.label}<Icon name="chevron" size={10} className="opacity-0 transition-opacity group-hover:opacity-100" />
                  </dt>
                </Link>
              ))}
            </dl>
          </section>

          <div className="grid gap-5 lg:grid-cols-[1fr_minmax(0,380px)]">
            <TrendPanel />

            {/* Active by severity */}
            <section className="panel p-4 sm:p-5">
              <h2 className="panel-title">Active by severity</h2>
              <p className="mt-0.5 text-xs text-muted">
                {sev.exact ? 'Open, acknowledged and snoozed findings.' : 'All findings (this backend doesn\'t report status per severity).'}
              </p>
              <ul className="mt-5 space-y-4">
                {SEVERITIES.map((s, i) => (
                  <li key={s}>
                    <Link to={`/violations?status=all&severity=${s.toLowerCase()}`} className="group block rounded-md">
                      <div className="mb-1.5 flex items-center justify-between text-xs">
                        <span className="font-semibold" style={{ color: SEV_STYLE[s].color }}>{SEV_STYLE[s].label}</span>
                        <span className="font-semibold text-text tabular group-hover:text-accent"><AnimatedNumber value={sev.counts[s] ?? 0} /></span>
                      </div>
                      <Bar value={sev.counts[s] ?? 0} max={maxSev} color={SEV_STYLE[s].color} delay={i * 80} />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          {/* Teams */}
          <section className="panel p-4 sm:p-5">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="panel-title">By team</h2>
                <p className="mt-0.5 text-xs text-muted">Open, acknowledged and resolved findings per owning team.</p>
              </div>
              <div className="flex gap-3 text-[11px] text-muted">
                {(['OPEN', 'ACKNOWLEDGED', 'RESOLVED'] as const).map((s) => (
                  <span key={s} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: STATUS_STYLE[s].color }} />{STATUS_STYLE[s].label}</span>
                ))}
              </div>
            </div>
            {teams.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted">No team-tagged findings yet.</p>
            ) : (
              <ul className="space-y-3.5">
                {teams.map((t, i) => (
                  <li key={t.team}>
                    <Link to={`/my-resources?team=${encodeURIComponent(t.team)}`} className="group grid grid-cols-[minmax(90px,140px)_1fr_auto] items-center gap-3 rounded-md">
                      <span className="truncate text-sm font-medium text-text group-hover:text-accent">{t.team}</span>
                      <StackedBar parts={[
                        { value: t.open, color: STATUS_STYLE.OPEN.color },
                        { value: t.acked, color: STATUS_STYLE.ACKNOWLEDGED.color },
                        { value: t.resolved, color: STATUS_STYLE.RESOLVED.color },
                      ]} max={maxTeam} delay={i * 60} />
                      <span className="w-20 text-right text-xs tabular text-muted">
                        <span className={t.open ? 'font-semibold text-critical' : 'text-low'}>{t.open}</span> open
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function StackedBar({ parts, max, delay }: { parts: Array<{ value: number; color: string }>; max: number; delay: number }) {
  const [grown, setGrown] = useState(reduceMotion())
  useEffect(() => { const t = window.setTimeout(() => setGrown(true), 80 + delay); return () => window.clearTimeout(t) }, [delay])
  return (
    <div className="flex h-2.5 overflow-hidden rounded-full bg-white/[0.05]">
      {parts.map((p, i) => (
        <div
          key={i}
          className="h-full first:rounded-l-full last:rounded-r-full"
          style={{ width: grown ? `${(p.value / max) * 100}%` : '0%', background: p.color,
                   transition: `width 0.9s cubic-bezier(0.16, 1, 0.3, 1) ${i * 70}ms` }}
        />
      ))}
    </div>
  )
}

export default Posture
