import type { Status } from '../types'

const CONF: Record<Status, { icon: string; bg: string; text: string; border: string }> = {
  OPEN:         { icon: '●', bg: 'rgba(248,113,113,0.1)',  text: '#f87171', border: 'rgba(248,113,113,0.3)' },
  ACKNOWLEDGED: { icon: '◎', bg: 'rgba(96,165,250,0.1)',   text: '#60a5fa', border: 'rgba(96,165,250,0.3)' },
  SNOOZED:      { icon: '◷', bg: 'rgba(251,146,60,0.1)',   text: '#fb923c', border: 'rgba(251,146,60,0.3)' },
  RESOLVED:     { icon: '✓', bg: 'rgba(74,222,128,0.1)',   text: '#4ade80', border: 'rgba(74,222,128,0.3)' },
  EXEMPTED:     { icon: '–', bg: 'rgba(122,132,153,0.08)', text: '#7a8499', border: 'rgba(122,132,153,0.2)' },
}

export function StatusBadge({ status }: { status: Status }) {
  const c = CONF[status]
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide"
      style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}` }}
    >
      <span className="text-[9px] leading-none">{c.icon}</span>
      {status}
    </span>
  )
}
