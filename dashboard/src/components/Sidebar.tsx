import { NavLink } from 'react-router-dom'
import type { Summary } from '../types'

const ShieldIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 1.5L2 4v4.5c0 3.3 2.3 5.7 6 6.8 3.7-1.1 6-3.5 6-6.8V4L8 1.5z"/>
    <path d="M5.5 8l1.5 1.5 3-3"/>
  </svg>
)

const GridIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <rect x="1.5" y="1.5" width="5" height="5" rx="1.2"/>
    <rect x="9.5" y="1.5" width="5" height="5" rx="1.2"/>
    <rect x="1.5" y="9.5" width="5" height="5" rx="1.2"/>
    <rect x="9.5" y="9.5" width="5" height="5" rx="1.2"/>
  </svg>
)

const ChartIcon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="2,12 5.5,8 8,10.5 12,4.5"/>
    <line x1="1" y1="14.5" x2="15" y2="14.5"/>
    <line x1="1" y1="1" x2="1" y2="14.5"/>
  </svg>
)

interface NavItemProps {
  to: string
  label: string
  icon: React.ReactNode
  count?: number
}

function NavItem({ to, label, icon, count }: NavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 ` +
        (isActive ? 'text-text font-medium' : 'text-muted hover:text-subtle')
      }
      style={({ isActive }) => isActive ? {
        background: 'linear-gradient(135deg, rgba(96,165,250,0.1) 0%, rgba(96,165,250,0.04) 100%)',
        border: '1px solid rgba(96,165,250,0.18)',
        boxShadow: '0 0 16px rgba(96,165,250,0.07)',
      } : {
        border: '1px solid transparent',
      }}
    >
      <span className="flex-shrink-0 opacity-70">{icon}</span>
      <span className="flex-1">{label}</span>
      {count !== undefined && count > 0 && (
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center"
          style={{
            background: 'rgba(248,113,113,0.18)',
            color: '#f87171',
            border: '1px solid rgba(248,113,113,0.3)',
            boxShadow: '0 0 8px rgba(248,113,113,0.18)',
          }}
        >
          {count}
        </span>
      )}
    </NavLink>
  )
}

interface Props {
  summary: Summary | null
  onTriggerAudit: () => void
  auditRunning: boolean
}

export function Sidebar({ summary, onTriggerAudit, auditRunning }: Props) {
  const openCount = summary?.by_status['OPEN'] ?? 0
  const sevCounts = [
    { key: 'CRITICAL', color: '#f87171' },
    { key: 'HIGH',     color: '#fb923c' },
    { key: 'MEDIUM',   color: '#fbbf24' },
  ]
  const maxSev = Math.max(...sevCounts.map(({ key }) => summary?.by_severity[key] ?? 0), 1)

  return (
    <aside
      className="w-60 flex-shrink-0 flex flex-col h-full"
      style={{
        background: 'linear-gradient(180deg, #0b1019 0%, #07090f 100%)',
        borderRight: '1px solid rgba(96,165,250,0.07)',
      }}
    >
      {/* Logo */}
      <div className="px-5 py-5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{
              background: 'linear-gradient(135deg, rgba(248,113,113,0.2) 0%, rgba(251,146,60,0.12) 100%)',
              border: '1px solid rgba(248,113,113,0.3)',
              boxShadow: '0 0 14px rgba(248,113,113,0.15)',
            }}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 1.5L2 4v4.5c0 3.3 2.3 5.7 6 6.8 3.7-1.1 6-3.5 6-6.8V4L8 1.5z"/>
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-bold leading-tight tracking-tight">
              Cloud<span style={{ color: '#f87171' }}>Shield</span>
            </div>
            <div
              className="text-[9px] font-semibold tracking-[0.2em] uppercase mt-0.5"
              style={{ color: 'rgba(96,165,250,0.45)' }}
            >
              Auditor
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        <p
          className="text-[9px] font-bold uppercase tracking-[0.18em] px-2 pb-2"
          style={{ color: 'rgba(122,132,153,0.45)' }}
        >
          Views
        </p>
        <NavItem to="/violations"   label="Violations"   icon={<ShieldIcon />} count={openCount > 0 ? openCount : undefined} />
        <NavItem to="/my-resources" label="My Resources" icon={<GridIcon />} />
        <NavItem to="/posture"      label="Posture"      icon={<ChartIcon />} />
      </nav>

      {/* Severity bars */}
      {summary && (
        <div className="px-4 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <p
            className="text-[9px] font-bold uppercase tracking-[0.18em] mb-3"
            style={{ color: 'rgba(122,132,153,0.45)' }}
          >
            Open by severity
          </p>
          <div className="space-y-2">
            {sevCounts.map(({ key, color }) => {
              const count = summary.by_severity[key] ?? 0
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-[10px] font-semibold w-[56px]" style={{ color }}>
                    {key}
                  </span>
                  <div
                    className="flex-1 h-1.5 rounded-full overflow-hidden"
                    style={{ background: 'rgba(255,255,255,0.05)' }}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{
                        width: `${(count / maxSev) * 100}%`,
                        background: `linear-gradient(90deg, ${color} 0%, ${color}90 100%)`,
                        boxShadow: `0 0 6px ${color}50`,
                      }}
                    />
                  </div>
                  <span
                    className="text-[11px] font-bold w-4 text-right tabular-nums"
                    style={{ color }}
                  >
                    {count}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Run Audit */}
      <div className="px-4 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
        <button
          onClick={onTriggerAudit}
          disabled={auditRunning}
          className="w-full py-2.5 px-3 rounded-lg text-xs font-semibold transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: 'linear-gradient(135deg, rgba(96,165,250,0.15) 0%, rgba(96,165,250,0.07) 100%)',
            color: '#60a5fa',
            border: '1px solid rgba(96,165,250,0.25)',
            boxShadow: '0 0 12px rgba(96,165,250,0.07)',
          }}
        >
          {auditRunning ? (
            <>
              <span className="animate-spin text-sm leading-none">⟳</span>
              Running…
            </>
          ) : (
            <>
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M10.5 6a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z"/>
                <path d="M6 2V1m0 10v-1M2 6H1m10 0h-1"/>
              </svg>
              Run Audit
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
