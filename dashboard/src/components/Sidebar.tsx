import { NavLink } from 'react-router-dom'
import type { Summary } from '../types'

interface Props {
  summary: Summary | null
  onTriggerAudit: () => void
  auditRunning: boolean
}

function NavItem({ to, label, count }: { to: string; label: string; count?: number }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center justify-between px-4 py-2.5 rounded-lg text-sm transition-colors duration-100 ` +
        (isActive
          ? 'bg-[#1f1f1f] text-text font-medium'
          : 'text-subtle hover:text-text hover:bg-[#1a1a1a]')
      }
    >
      <span>{label}</span>
      {count !== undefined && (
        <span className="text-xs bg-critical/20 text-critical px-1.5 py-0.5 rounded font-bold min-w-[22px] text-center">
          {count}
        </span>
      )}
    </NavLink>
  )
}

export function Sidebar({ summary, onTriggerAudit, auditRunning }: Props) {
  const openCount = summary?.by_status['OPEN'] ?? 0

  return (
    <aside className="w-56 flex-shrink-0 bg-surface border-r border-border flex flex-col h-full">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="text-lg font-bold text-white leading-tight">
          Cloud<span className="text-critical">Shield</span>
        </div>
        <div className="text-[11px] text-muted mt-0.5 tracking-wide">Auditor</div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        <p className="text-[10px] uppercase tracking-widest text-muted px-2 pb-1">Views</p>
        <NavItem to="/violations"   label="Violations"    count={openCount > 0 ? openCount : undefined} />
        <NavItem to="/my-resources" label="My Resources" />
        <NavItem to="/posture"      label="Posture" />
      </nav>

      {/* Stats strip */}
      {summary && (
        <div className="px-4 py-3 border-t border-border space-y-1">
          {(['CRITICAL', 'HIGH', 'MEDIUM'] as const).map((sev) => {
            const colors: Record<string, string> = {
              CRITICAL: 'text-critical',
              HIGH:     'text-high',
              MEDIUM:   'text-[#d4b106]',
            }
            return (
              <div key={sev} className="flex justify-between text-[11px]">
                <span className={`${colors[sev]} font-medium`}>{sev}</span>
                <span className="text-subtle">{summary.by_severity[sev] ?? 0}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* Run audit button */}
      <div className="px-4 py-4 border-t border-border">
        <button
          onClick={onTriggerAudit}
          disabled={auditRunning}
          className="w-full btn bg-[#1a1a1a] border border-border text-subtle hover:text-text hover:border-[#434343] disabled:opacity-40 disabled:cursor-not-allowed justify-center flex items-center gap-2"
        >
          {auditRunning ? (
            <>
              <span className="animate-spin">⟳</span> Running…
            </>
          ) : (
            '▶ Run Audit'
          )}
        </button>
      </div>
    </aside>
  )
}
