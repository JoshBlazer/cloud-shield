import { SEV_STYLE, STATUS_STYLE } from '../lib/catalog'
import type { Severity, Status } from '../types'

export function SeverityBadge({ severity }: { severity: Severity }) {
  const c = SEV_STYLE[severity]
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide"
      style={{ background: `rgba(${c.rgb},0.12)`, color: c.color, borderColor: `rgba(${c.rgb},0.35)` }}
    >
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: c.color, boxShadow: `0 0 6px ${c.color}` }} />
      {severity}
    </span>
  )
}

export function StatusBadge({ status }: { status: Status }) {
  const c = STATUS_STYLE[status]
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide"
      style={{ background: `rgba(${c.rgb},0.1)`, color: c.color, borderColor: `rgba(${c.rgb},0.3)` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c.color }} />
      {c.label}
    </span>
  )
}
