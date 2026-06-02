import type { Severity } from '../types'

const STYLES: Record<Severity, string> = {
  CRITICAL: 'bg-critical/20 text-critical border border-critical/40',
  HIGH:     'bg-high/20 text-high border border-high/40',
  MEDIUM:   'bg-medium/20 text-[#d4b106] border border-medium/40',
  LOW:      'bg-low/20 text-low border border-low/40',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge ${STYLES[severity]}`}>
      {severity}
    </span>
  )
}
