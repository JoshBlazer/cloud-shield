import { useEffect, useId, useRef, useState } from 'react'

interface MenuItem {
  label:    string
  hint?:    string
  onSelect: () => void
}

interface Props {
  trigger: (props: {
    ref: React.Ref<HTMLButtonElement>
    onClick: () => void
    'aria-haspopup': 'menu'
    'aria-expanded': boolean
    'aria-controls': string
  }) => React.ReactNode
  items: MenuItem[]
  align?: 'start' | 'end'
}

/** Keyboard-accessible dropdown menu (arrow keys, Home/End, Escape, click-away). */
export function Menu({ trigger, items, align = 'start' }: Props) {
  const [open, setOpen]     = useState(false)
  const [active, setActive] = useState(0)
  const menuId     = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef    = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !triggerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  useEffect(() => {
    if (open) menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]')[active]?.focus()
  }, [open, active])

  const close = (refocus = true) => { setOpen(false); if (refocus) triggerRef.current?.focus() }

  const onKeyDown = (e: React.KeyboardEvent) => {
    const last = items.length - 1
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i >= last ? 0 : i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i <= 0 ? last : i - 1)) }
    else if (e.key === 'Home') { e.preventDefault(); setActive(0) }
    else if (e.key === 'End') { e.preventDefault(); setActive(last) }
    else if (e.key === 'Escape' || e.key === 'Tab') { close(e.key === 'Escape') }
  }

  return (
    <div className="relative inline-flex">
      {trigger({
        ref: triggerRef,
        onClick: () => { setActive(0); setOpen((o) => !o) },
        'aria-haspopup': 'menu',
        'aria-expanded': open,
        'aria-controls': menuId,
      })}
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          onKeyDown={onKeyDown}
          className={`absolute bottom-full z-30 mb-2 min-w-[180px] animate-scale-in overflow-hidden rounded-xl border border-white/10 bg-raised p-1 shadow-2xl
                      ${align === 'end' ? 'right-0 origin-bottom-right' : 'left-0 origin-bottom-left'}`}
          style={{ boxShadow: '0 16px 48px rgba(0,0,0,0.6)' }}
        >
          {items.map((item, i) => (
            <button
              key={item.label}
              role="menuitem"
              tabIndex={i === active ? 0 : -1}
              onMouseEnter={() => setActive(i)}
              onClick={() => { close(); item.onSelect() }}
              className="flex w-full items-center justify-between gap-4 rounded-lg px-3 py-2 text-left text-xs font-medium text-subtle
                         transition-colors hover:bg-white/[0.06] hover:text-text focus-visible:bg-white/[0.06] focus-visible:text-text focus-visible:outline-none"
            >
              {item.label}
              {item.hint && <span className="text-[11px] text-faint">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
