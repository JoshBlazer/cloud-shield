import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from './Icon'

type Tone = 'success' | 'error' | 'info'

interface ToastInput {
  tone?:    Tone
  title:    string
  detail?:  string
  /** Optional action button, e.g. Undo. The toast closes when it runs. */
  action?:  { label: string; run: () => void | Promise<void> }
  duration?: number
}

interface ToastItem extends ToastInput { id: number; leaving: boolean }

const ToastContext = createContext<(t: ToastInput) => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

const TONE: Record<Tone, { color: string; rgb: string; icon: 'check' | 'alert' | 'info' }> = {
  success: { color: '#4ade80', rgb: '74,222,128',  icon: 'check' },
  error:   { color: '#f87171', rgb: '248,113,113', icon: 'alert' },
  info:    { color: '#60a5fa', rgb: '96,165,250',  icon: 'info' },
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.map((t) => t.id === id ? { ...t, leaving: true } : t))
    window.setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), 220)
  }, [])

  const push = useCallback((t: ToastInput) => {
    const id = nextId.current++
    // Keep the stack short: the oldest toast makes way for the newest.
    setToasts((ts) => [...ts.slice(-3), { ...t, id, leaving: false }])
  }, [])

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 safe-bottom sm:items-end sm:p-6"
      >
        {toasts.map((t) => <Toast key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />)}
      </div>
    </ToastContext.Provider>
  )
}

function Toast({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const tone     = TONE[toast.tone ?? 'success']
  const duration = toast.duration ?? (toast.action ? 6000 : 4000)
  const [paused, setPaused] = useState(false)
  const remaining = useRef(duration)
  // The parent passes a fresh closure each render; keep the timer effect keyed
  // on state only so adding another toast doesn't restart this one's countdown.
  const dismissRef = useRef(onDismiss)
  dismissRef.current = onDismiss
  const startedAt = useRef(Date.now())

  // Auto-dismiss, pausing while hovered or focused so people can reach Undo.
  useEffect(() => {
    if (paused || toast.leaving) return
    startedAt.current = Date.now()
    const timer = window.setTimeout(() => dismissRef.current(), remaining.current)
    return () => {
      window.clearTimeout(timer)
      remaining.current -= Date.now() - startedAt.current
    }
  }, [paused, toast.leaving])

  return (
    <div
      role={toast.tone === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className={`pointer-events-auto relative w-full max-w-sm overflow-hidden rounded-xl border backdrop-blur-xl
                  transition-all duration-200 ease-out ${toast.leaving ? 'translate-y-2 opacity-0' : 'animate-slide-in-right'}`}
      style={{
        background: 'rgba(15, 23, 36, 0.92)',
        borderColor: `rgba(${tone.rgb}, 0.28)`,
        boxShadow: `0 12px 40px rgba(0,0,0,0.55), 0 0 0 1px rgba(${tone.rgb}, 0.06), 0 0 24px rgba(${tone.rgb}, 0.08)`,
      }}
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <span className="mt-0.5 flex-shrink-0" style={{ color: tone.color }}><Icon name={tone.icon} size={16} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text">{toast.title}</p>
          {toast.detail && <p className="mt-0.5 break-words text-xs text-muted">{toast.detail}</p>}
        </div>
        {toast.action && (
          <button
            className="btn btn-ghost -my-1 flex-shrink-0 text-accent hover:text-accent"
            onClick={async () => { onDismiss(); await toast.action!.run() }}
          >
            {toast.action.label}
          </button>
        )}
        <button className="btn btn-ghost btn-icon -my-1 -mr-2 flex-shrink-0" onClick={onDismiss} aria-label="Dismiss notification">
          <Icon name="x" size={14} />
        </button>
      </div>
      {/* Time-remaining bar */}
      <div
        className="absolute bottom-0 left-0 h-0.5 w-full origin-left"
        style={{
          background: tone.color,
          opacity: 0.5,
          animation: `toast-progress ${duration}ms linear forwards`,
          animationPlayState: paused ? 'paused' : 'running',
        }}
      />
    </div>
  )
}
