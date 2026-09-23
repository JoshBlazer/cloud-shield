import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'

interface Props {
  open:     boolean
  onClose:  () => void
  title:    string
  description?: string
  children: React.ReactNode
  footer?:  React.ReactNode
}

/**
 * Accessible modal: focus moves in on open and back to the trigger on close,
 * Tab stays inside, Escape and a backdrop click close it, page scroll is locked.
 */
export function Dialog({ open, onClose, title, description, children, footer }: Props) {
  const panelRef  = useRef<HTMLDivElement>(null)
  // Callers usually pass an inline onClose; keep the latest in a ref so the
  // focus/keyboard setup below runs once per open, not on every render (re-running
  // it bounced focus away mid-typing and dropped keystrokes).
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const titleId   = useId()
  const descId    = useId()

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel    = panelRef.current
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? [])
    // Prefer the first form field; fall back to the first control.
    const first = panel?.querySelector<HTMLElement>('textarea, input') ?? focusables()[0]
    window.setTimeout(() => first?.focus(), 30)

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onCloseRef.current() }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (!items.length) return
      const [head, tail] = [items[0], items[items.length - 1]]
      if (e.shiftKey && document.activeElement === head) { e.preventDefault(); tail.focus() }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus() }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div className="absolute inset-0 animate-fade-in bg-black/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        className="relative w-full max-w-md animate-scale-in rounded-t-2xl border border-white/10 bg-card shadow-2xl sm:rounded-2xl safe-bottom"
        style={{ boxShadow: '0 24px 80px rgba(0,0,0,0.7)' }}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-text">{title}</h2>
            {description && <p id={descId} className="mt-1 text-sm text-muted">{description}</p>}
          </div>
          <button className="btn btn-ghost btn-icon -mr-2 -mt-1" onClick={onClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-white/5 px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
