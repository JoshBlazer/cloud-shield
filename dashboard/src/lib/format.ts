const RTF = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto', style: 'short' })

/** "3 min. ago", "yesterday", "in 6 days" — relative to now. */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const secs = Math.round((t - now) / 1000)
  const abs  = Math.abs(secs)
  if (abs < 45)          return 'just now'
  if (abs < 3600)        return RTF.format(Math.round(secs / 60), 'minute')
  if (abs < 86_400)      return RTF.format(Math.round(secs / 3600), 'hour')
  if (abs < 30 * 86_400) return RTF.format(Math.round(secs / 86_400), 'day')
  return RTF.format(Math.round(secs / (30 * 86_400)), 'month')
}

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
})
const SHORT_DATE = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })

/** Full, locale-aware timestamp for tooltips and <time> titles. */
export function fullDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : DATE_TIME.format(d)
}

export function shortDate(iso: string): string {
  // Date-only strings (YYYY-MM-DD) are UTC calendar days; don't let the local
  // timezone shift them to the previous day.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00Z`) : new Date(iso)
  return SHORT_DATE.format(d)
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}
