import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { USE_MOCK } from '../api/client'
import { AUTH_ENABLED, logout } from '../hooks/useAuth'
import { SEV_STYLE } from '../lib/catalog'
import { relativeTime } from '../lib/format'
import { activeBySeverity, useAppData } from '../state/AppData'
import { SEVERITIES } from '../types'
import { AnimatedNumber } from './AnimatedNumber'
import { Icon, Spinner } from './Icon'

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-critical/30 text-critical"
        style={{ background: 'linear-gradient(135deg, rgba(248,113,113,0.2), rgba(251,146,60,0.12))', boxShadow: '0 0 14px rgba(248,113,113,0.15)' }}
      >
        <Icon name="shield-plain" size={15} />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-tight text-text">Cloud<span className="text-critical">Shield</span></div>
        {!compact && <div className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-accent/70">Auditor</div>}
      </div>
    </div>
  )
}

function NavItem({ to, label, icon, count, onNavigate }: {
  to: string; label: string; icon: string; count?: number; onNavigate?: () => void
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-all duration-200
         ${isActive
           ? 'border-accent/20 bg-accent/[0.08] font-medium text-text shadow-[0_0_16px_rgba(96,165,250,0.07)]'
           : 'border-transparent text-muted hover:bg-white/[0.03] hover:text-text'}`
      }
    >
      {({ isActive }) => (
        <>
          <span className={`absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent transition-all duration-300 ${isActive ? 'opacity-100' : 'scale-y-0 opacity-0'}`} />
          <Icon name={icon} size={15} className={isActive ? 'text-accent' : 'opacity-80'} />
          <span className="flex-1">{label}</span>
          {count !== undefined && count > 0 && (
            <span className="min-w-[22px] rounded-full border border-critical/30 bg-critical/15 px-1.5 py-0.5 text-center text-[10px] font-bold text-critical tabular">
              <AnimatedNumber value={count} duration={400} />
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

/** Re-render every 30s so "updated 2 min ago" stays true. */
function useNow(interval = 30_000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), interval); return () => window.clearInterval(t) }, [interval])
  return now
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { summary, summaryError, lastUpdated, refreshing, refresh, triggerAudit, auditRunning } = useAppData()
  const now = useNow()
  const open = summary?.by_status.OPEN ?? 0
  const sev  = activeBySeverity(summary)
  const max  = Math.max(1, ...SEVERITIES.map((s) => sev.counts[s] ?? 0))
  const stale = !!summaryError

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-white/[0.04] px-5 py-5"><Logo /></div>

      <nav aria-label="Main" className="flex-1 space-y-1 px-3 py-4">
        <p className="eyebrow px-2 pb-2">Views</p>
        <NavItem to="/violations"   label="Findings"     icon="shield" count={open} onNavigate={onNavigate} />
        <NavItem to="/my-resources" label="My resources" icon="grid" onNavigate={onNavigate} />
        <NavItem to="/posture"      label="Posture"      icon="chart" onNavigate={onNavigate} />
      </nav>

      <div className="border-t border-white/[0.04] px-4 py-4">
        <p className="eyebrow mb-3">{sev.exact ? 'Active by severity' : 'By severity'}</p>
        <ul className="space-y-2.5">
          {SEVERITIES.map((s) => {
            const n = sev.counts[s] ?? 0
            const c = SEV_STYLE[s]
            return (
              <li key={s}>
                <NavLink to={`/violations?status=all&severity=${s.toLowerCase()}`} onClick={onNavigate}
                  className="group flex items-center gap-2.5 rounded" aria-label={`${n} ${c.label.toLowerCase()} findings`}>
                  <span className="w-[54px] text-[10px] font-semibold uppercase tracking-wide" style={{ color: c.color }}>{c.label}</span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
                    <span className="block h-full rounded-full transition-[width] duration-700 ease-out-expo"
                      style={{ width: summary ? `${(n / max) * 100}%` : '0%', background: c.color, boxShadow: `0 0 6px ${c.color}70` }} />
                  </span>
                  <span className="w-6 text-right text-[11px] font-bold tabular" style={{ color: c.color }}>{summary ? n : '–'}</span>
                </NavLink>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="space-y-3 border-t border-white/[0.04] px-4 py-4">
        <button onClick={() => void triggerAudit()} disabled={auditRunning} className="btn btn-accent w-full py-2.5">
          {auditRunning ? <><Spinner size={13} /> Auditing…</> : <><Icon name="play" size={12} /> Run audit now</>}
        </button>
        <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
          <span className="flex min-w-0 items-center gap-2" title={summaryError ?? undefined}>
            <span className={stale ? 'dot-stale' : 'dot-live'} />
            <span className="truncate">
              {stale ? 'Offline — showing last data' : lastUpdated ? `Updated ${relativeTime(new Date(lastUpdated).toISOString(), now)}` : 'Connecting…'}
            </span>
          </span>
          <button onClick={() => void refresh()} className="btn btn-ghost btn-icon h-7 min-h-0 w-7" aria-label="Refresh data" title="Refresh">
            <Icon name="refresh" size={13} className={refreshing ? 'animate-spin' : ''} />
          </button>
        </div>
        {USE_MOCK && (
          <p className="rounded-md border border-medium/20 bg-medium/[0.06] px-2.5 py-1.5 text-[10px] leading-relaxed text-medium/90">
            Demo data — not connected to AWS.
          </p>
        )}
        {AUTH_ENABLED && (
          <button onClick={() => void logout()} className="btn btn-ghost w-full justify-start">
            <Icon name="logout" size={13} /> Sign out
          </button>
        )}
      </div>
    </div>
  )
}

export function Sidebar() {
  return (
    <aside
      className="hidden w-64 flex-shrink-0 border-r border-accent/[0.07] lg:block"
      style={{ background: 'linear-gradient(180deg, #0b1019 0%, #07090f 100%)' }}
    >
      <SidebarContent />
    </aside>
  )
}

/** Phone/tablet: top bar with a menu button that opens the sidebar as a drawer. */
export function MobileNav() {
  const [open, setOpen] = useState(false)
  const { summary } = useAppData()
  const openCount = summary?.by_status.OPEN ?? 0

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <>
      <header className="flex flex-shrink-0 items-center justify-between border-b border-white/[0.05] bg-surface/90 px-4 py-2.5 backdrop-blur-md lg:hidden">
        <Logo compact />
        <button
          className="btn btn-ghost btn-icon relative"
          onClick={() => setOpen(true)}
          aria-label="Open navigation"
          aria-expanded={open}
          aria-controls="mobile-drawer"
        >
          <Icon name="menu" size={18} />
          {openCount > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-critical shadow-[0_0_8px_#f87171]" />}
        </button>
      </header>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 animate-fade-in bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <aside
            id="mobile-drawer"
            className="absolute inset-y-0 left-0 w-[82%] max-w-[300px] animate-slide-in-left border-r border-white/10 shadow-2xl safe-bottom"
            style={{ background: 'linear-gradient(180deg, #0b1019 0%, #07090f 100%)' }}
          >
            <button className="btn btn-ghost btn-icon absolute right-3 top-4 z-10" onClick={() => setOpen(false)} aria-label="Close navigation" autoFocus>
              <Icon name="x" size={16} />
            </button>
            <SidebarContent onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
    </>
  )
}
