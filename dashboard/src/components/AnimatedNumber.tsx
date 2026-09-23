import { useEffect, useRef, useState } from 'react'

const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Animates smoothly from the previous value to a new one (ease-out, ~600ms).
 * By default it first appears at its real value; pass `countUp` to count up
 * from zero on mount (for headline figures only — elsewhere that briefly shows
 * a wrong number).
 */
export function AnimatedNumber({ value, duration = 600, suffix = '', countUp = false }: {
  value: number; duration?: number; suffix?: string; countUp?: boolean
}) {
  const [shown, setShown] = useState(countUp && !reduceMotion() ? 0 : value)
  const fromRef = useRef(shown)

  useEffect(() => {
    const from = fromRef.current
    if (from === value || reduceMotion()) { setShown(value); fromRef.current = value; return }
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      const next = Math.round(from + (value - from) * eased)
      setShown(next)
      fromRef.current = next
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return <span className="tabular">{shown.toLocaleString()}{suffix}</span>
}
