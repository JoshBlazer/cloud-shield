export function PageHeader({ title, subtitle, children }: {
  title: string; subtitle?: React.ReactNode; children?: React.ReactNode
}) {
  return (
    <div className="flex-shrink-0 border-b border-white/[0.05] bg-surface/60 px-4 py-4 backdrop-blur-md sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight text-text">{title}</h1>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
      </div>
      {children && <div className="mt-3.5">{children}</div>}
    </div>
  )
}

interface SegOption<T extends string> { value: T; label: string; count?: number; color?: string }

/** Segmented control that scrolls sideways on narrow screens instead of wrapping. */
export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: SegOption<T>[]; label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="no-scrollbar -mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <div className="flex gap-0.5 rounded-xl border border-white/[0.06] bg-white/[0.03] p-1">
        {options.map((o) => {
          const active = o.value === value
          const color  = o.color ?? '#60a5fa'
          return (
            <button
              key={o.value}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(o.value)}
              className={`relative flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold
                          transition-[background-color,color,box-shadow] duration-200
                          ${active ? '' : 'text-muted hover:bg-white/[0.04] hover:text-text'}`}
              style={active ? {
                color,
                background: `color-mix(in srgb, ${color} 16%, transparent)`,
                boxShadow: `0 0 0 1px color-mix(in srgb, ${color} 30%, transparent), 0 0 14px color-mix(in srgb, ${color} 14%, transparent)`,
              } : undefined}
            >
              {o.label}
              {o.count !== undefined && (
                <span
                  className="min-w-[18px] rounded-full px-1.5 text-center text-[10px] font-bold tabular transition-colors"
                  style={active
                    ? { background: `color-mix(in srgb, ${color} 22%, transparent)`, color }
                    : { background: 'rgba(255,255,255,0.06)', color: '#9aa3b5' }}
                >
                  {o.count}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
