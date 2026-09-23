import { Icon } from './Icon'

/** Placeholder with the same silhouette as a ViolationCard. */
export function CardSkeleton() {
  return (
    <div className="panel overflow-hidden" aria-hidden="true">
      <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3">
        <div className="skeleton h-5 w-20" />
        <div className="skeleton h-4 w-2/5" />
        <div className="skeleton ml-auto h-5 w-16 rounded-full" />
      </div>
      <div className="space-y-2.5 px-4 py-3.5">
        <div className="flex gap-2"><div className="skeleton h-4 w-10" /><div className="skeleton h-4 w-48" /></div>
        <div className="skeleton h-3.5 w-3/4" />
        <div className="skeleton h-3 w-1/2" />
      </div>
    </div>
  )
}

export function ListSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => <CardSkeleton key={i} />)}
    </div>
  )
}

export function EmptyState({ icon = 'check', tone = 'good', title, detail, action }: {
  icon?: string; tone?: 'good' | 'neutral'; title: string; detail?: string; action?: React.ReactNode
}) {
  const color = tone === 'good' ? '#4ade80' : '#9aa3b5'
  const rgb   = tone === 'good' ? '74,222,128' : '154,163,181'
  return (
    <div className="flex animate-fade-up flex-col items-center px-6 py-16 text-center sm:py-20">
      <div
        className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border"
        style={{ background: `rgba(${rgb},0.08)`, borderColor: `rgba(${rgb},0.18)`, color, boxShadow: `0 0 32px rgba(${rgb},0.1)` }}
      >
        <Icon name={icon} size={24} />
      </div>
      <p className="text-sm font-semibold" style={{ color }}>{title}</p>
      {detail && <p className="mt-1 max-w-sm text-sm text-muted">{detail}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({ title = 'Something went wrong', detail, onRetry }: {
  title?: string; detail?: string; onRetry?: () => void
}) {
  return (
    <div role="alert" className="flex animate-fade-up flex-col items-center px-6 py-16 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-critical/25 bg-critical/10 text-critical">
        <Icon name="alert" size={24} />
      </div>
      <p className="text-sm font-semibold text-text">{title}</p>
      {detail && <p className="mt-1 max-w-sm break-words text-sm text-muted">{detail}</p>}
      {onRetry && (
        <button className="btn btn-secondary mt-5" onClick={onRetry}>
          <Icon name="refresh" size={13} /> Try again
        </button>
      )}
    </div>
  )
}
