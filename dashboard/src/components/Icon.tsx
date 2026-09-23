/** Small inline icon set (stroke icons on a 16px grid), so there's no icon dependency. */
const PATHS: Record<string, React.ReactNode> = {
  shield:   <><path d="M8 1.5L2 4v4.5c0 3.3 2.3 5.7 6 6.8 3.7-1.1 6-3.5 6-6.8V4L8 1.5z"/><path d="M5.5 8l1.5 1.5 3-3"/></>,
  'shield-plain': <path d="M8 1.5L2 4v4.5c0 3.3 2.3 5.7 6 6.8 3.7-1.1 6-3.5 6-6.8V4L8 1.5z"/>,
  grid:     <><rect x="1.5" y="1.5" width="5" height="5" rx="1.2"/><rect x="9.5" y="1.5" width="5" height="5" rx="1.2"/><rect x="1.5" y="9.5" width="5" height="5" rx="1.2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1.2"/></>,
  chart:    <><polyline points="2,12 5.5,8 8,10.5 12,4.5"/><path d="M1 14.5h14M1 1v13.5"/></>,
  check:    <polyline points="3,8.5 6.5,12 13,4.5"/>,
  x:        <path d="M4 4l8 8M12 4l-8 8"/>,
  alert:    <><circle cx="8" cy="8" r="6.5"/><path d="M8 4.8v3.8M8 11.2v.01"/></>,
  info:     <><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.8v.01"/></>,
  menu:     <path d="M2 4h12M2 8h12M2 12h12"/>,
  refresh:  <><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9"/><polyline points="13.5,2 13.5,5 10.5,5"/></>,
  play:     <path d="M5 3.5l7 4.5-7 4.5z"/>,
  clock:    <><circle cx="8" cy="8" r="6.5"/><path d="M8 4.5V8l2.5 1.5"/></>,
  eye:      <><path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/><circle cx="8" cy="8" r="2"/></>,
  slash:    <><circle cx="8" cy="8" r="6.5"/><path d="M3.5 12.5l9-9"/></>,
  undo:     <><path d="M3 6h7a3.5 3.5 0 0 1 0 7H6"/><polyline points="5.5,3.5 3,6 5.5,8.5"/></>,
  external: <><path d="M9 2.5h4.5V7M13.5 2.5L7 9"/><path d="M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3"/></>,
  copy:     <><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"/></>,
  chevron:  <path d="M6 3.5L10.5 8 6 12.5"/>,
  'chevron-down': <path d="M3.5 6L8 10.5 12.5 6"/>,
  search:   <><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></>,
  wrench:   <path d="M10.5 2a3.5 3.5 0 0 0-3.3 4.6L2.5 11.3a1.4 1.4 0 0 0 2 2l4.7-4.7A3.5 3.5 0 0 0 14 5.5l-2 2-1.8-.3-.3-1.8 2-2A3.5 3.5 0 0 0 10.5 2z"/>,
  logout:   <><path d="M6 14H3.5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1H6"/><polyline points="10.5,11 13.5,8 10.5,5"/><path d="M13.5 8H6"/></>,
  users:    <><circle cx="6" cy="5.5" r="2.5"/><path d="M1.5 13.5c.6-2.3 2.3-3.5 4.5-3.5s3.9 1.2 4.5 3.5"/><path d="M11 3.2a2.5 2.5 0 0 1 0 4.6M12.2 10.2c1.1.5 1.9 1.6 2.3 3.3"/></>,
  sparkle:  <path d="M8 1.5l1.5 4.9 4.9 1.6-4.9 1.5L8 14.5l-1.6-5L1.5 8l4.9-1.6z"/>,
}

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 16, className, strokeWidth = 1.6 }: {
  name: IconName | string; size?: number; className?: string; strokeWidth?: number
}) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      className={className} aria-hidden="true" focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" className="animate-spin" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M14 8a6 6 0 0 0-6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}
