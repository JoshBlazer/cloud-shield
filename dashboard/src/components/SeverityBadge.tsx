import type { Severity } from '../types'

const CONF: Record<Severity, { bg: string; text: string; border: string; dot: string }> = {
  CRITICAL: { bg: 'rgba(248,113,113,0.12)', text: '#f87171', border: 'rgba(248,113,113,0.35)', dot: '#f87171' },
  HIGH:     { bg: 'rgba(251,146,60,0.12)',  text: '#fb923c', border: 'rgba(251,146,60,0.35)',  dot: '#fb923c' },
  MEDIUM:   { bg: 'rgba(251,191,36,0.1)',   text: '#fbbf24', border: 'rgba(251,191,36,0.3)',   dot: '#fbbf24' },
  LOW:      { bg: 'rgba(74,222,128,0.1)',   text: '#4ade80', border: 'rgba(74,222,128,0.3)',   dot: '#4ade80' },
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const c = CONF[severity]
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-bold tracking-wide uppercase"
      style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}`, boxShadow: `0 0 6px ${c.dot}30` }}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c.dot, boxShadow: `0 0 4px ${c.dot}`, flexShrink: 0 }} />
      {severity}
    </span>
  )
}
