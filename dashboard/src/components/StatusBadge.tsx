import type { Status } from '../types'

const STYLES: Record<Status, string> = {
  OPEN:         'bg-critical/10 text-critical',
  ACKNOWLEDGED: 'bg-accent/10 text-accent',
  SNOOZED:      'bg-high/10 text-high',
  RESOLVED:     'bg-low/10 text-low',
  EXEMPTED:     'bg-subtle/10 text-subtle',
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge ${STYLES[status]}`}>
      {status}
    </span>
  )
}
