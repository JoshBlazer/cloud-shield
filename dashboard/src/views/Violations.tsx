import { useCallback, useEffect, useState } from 'react'
import { mockApi } from '../api/mock'
import { ViolationCard } from '../components/ViolationCard'
import type { Severity, Status, Violation } from '../types'

const SEVERITIES: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const STATUSES: Status[]     = ['OPEN', 'ACKNOWLEDGED', 'SNOOZED']

const SEV_THEME: Record<string, { text: string; glow: string; gradient: string }> = {
  CRITICAL: { text: '#f87171', glow: 'rgba(248,113,113,0.35)', gradient: 'rgba(248,113,113,0.15), transparent 60%' },
  HIGH:     { text: '#fb923c', glow: 'rgba(251,146,60,0.3)',   gradient: 'rgba(251,146,60,0.12), transparent 60%'  },
  MEDIUM:   { text: '#fbbf24', glow: 'rgba(251,191,36,0.25)',  gradient: 'rgba(251,191,36,0.1), transparent 60%'   },
  LOW:      { text: '#4ade80', glow: 'rgba(74,222,128,0.25)',  gradient: 'rgba(74,222,128,0.1), transparent 60%'   },
}

const STATUS_THEME: Record<string, { active: { bg: string; color: string; shadow: string } }> = {
  '':             { active: { bg: 'rgba(96,165,250,0.18)',  color: '#60a5fa', shadow: 'rgba(96,165,250,0.12)'  } },
  OPEN:           { active: { bg: 'rgba(248,113,113,0.18)', color: '#f87171', shadow: 'rgba(248,113,113,0.12)' } },
  ACKNOWLEDGED:   { active: { bg: 'rgba(96,165,250,0.18)',  color: '#60a5fa', shadow: 'rgba(96,165,250,0.12)'  } },
  SNOOZED:        { active: { bg: 'rgba(251,146,60,0.18)',  color: '#fb923c', shadow: 'rgba(251,146,60,0.12)'  } },
}

export function Violations() {
  const [violations, setViolations] = useState<Violation[]>([])
  const [loading, setLoading]       = useState(true)
  const [statusFilter, setStatus]   = useState<Status | ''>('OPEN')
  const [sevFilter, setSev]         = useState<Severity | ''>('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await mockApi.listViolations({
        status:   statusFilter || undefined,
        severity: sevFilter    || undefined,
      })
      setViolations(data.violations)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, sevFilter])

  useEffect(() => { load() }, [load])

  const handleAcknowledge = async (id: string) => { await mockApi.acknowledge(id); load() }
  const handleSnooze      = async (id: string, days: number) => { await mockApi.snooze(id, days); load() }
  const handleExempt      = async (id: string) => { await mockApi.exempt(id, 'Manually exempted from dashboard'); load() }

  const grouped: Record<Severity, Violation[]> = { CRITICAL: [], HIGH: [], MEDIUM: [], LOW: [] }
  for (const v of violations) grouped[v.severity]?.push(v)

  const allLabels: Array<{ key: Status | ''; label: string }> = [
    { key: '', label: 'All' },
    { key: 'OPEN', label: 'Open' },
    { key: 'ACKNOWLEDGED', label: 'Acknowledged' },
    { key: 'SNOOZED', label: 'Snoozed' },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: 'transparent' }}>
      {/* Toolbar */}
      <div
        className="flex items-center gap-3 px-6 py-4 flex-shrink-0"
        style={{
          background: 'rgba(11,16,25,0.6)',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <h1 className="text-base font-bold text-text mr-2">Violations</h1>

        {/* Status filter — segmented control */}
        <div
          className="flex gap-0.5 p-0.5 rounded-lg"
          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          {allLabels.map(({ key, label }) => {
            const isActive = statusFilter === key
            const theme = STATUS_THEME[key]?.active
            return (
              <button
                key={key}
                onClick={() => setStatus(key as Status | '')}
                className="px-3 py-1 rounded-md text-xs font-semibold transition-all duration-150"
                style={isActive ? {
                  background: theme.bg,
                  color: theme.color,
                  boxShadow: `0 0 10px ${theme.shadow}`,
                } : {
                  color: '#4b5568',
                  background: 'transparent',
                }}
              >
                {label}
              </button>
            )
          })}
        </div>

        <div className="w-px h-5 mx-1" style={{ background: 'rgba(255,255,255,0.07)' }} />

        <select
          value={sevFilter}
          onChange={(e) => setSev(e.target.value as Severity | '')}
          className="text-xs rounded-lg px-2.5 py-1.5 focus:outline-none transition-colors"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: '#7a8499',
          }}
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <span className="ml-auto text-xs tabular-nums" style={{ color: '#4b5568' }}>
          {loading ? 'Loading…' : `${violations.length} violation${violations.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
        {loading ? (
          <div className="text-center py-16" style={{ color: '#4b5568' }}>Loading violations…</div>
        ) : violations.length === 0 ? (
          <div className="text-center py-20">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: 'rgba(74,222,128,0.08)', border: '1px solid rgba(74,222,128,0.15)' }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#4ade80" strokeWidth="1.5" strokeLinecap="round">
                <polyline points="20,6 9,17 4,12"/>
              </svg>
            </div>
            <p className="text-sm font-semibold" style={{ color: '#4ade80' }}>No violations match this filter</p>
            <p className="text-xs mt-1" style={{ color: '#4b5568' }}>Try a different status or severity</p>
          </div>
        ) : (
          SEVERITIES.map((sev) => {
            const items = grouped[sev]
            if (!items.length) return null
            const t = SEV_THEME[sev]
            return (
              <section key={sev} className="animate-fade-in">
                {/* Section header */}
                <div className="flex items-center gap-3 mb-3">
                  <div className="flex items-center gap-2">
                    <div
                      style={{ width: 7, height: 7, borderRadius: '50%', background: t.text, boxShadow: `0 0 8px ${t.text}` }}
                    />
                    <span
                      className="text-[11px] font-bold tracking-widest uppercase"
                      style={{ color: t.text }}
                    >
                      {sev}
                    </span>
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-bold"
                      style={{ background: `rgba(${sev === 'CRITICAL' ? '248,113,113' : sev === 'HIGH' ? '251,146,60' : sev === 'MEDIUM' ? '251,191,36' : '74,222,128'},0.12)`, color: t.text }}
                    >
                      {items.length}
                    </span>
                  </div>
                  <div
                    className="flex-1 h-px"
                    style={{ background: `linear-gradient(90deg, ${t.glow} 0%, transparent 70%)` }}
                  />
                </div>

                <div className="space-y-2.5">
                  {items.map((v) => (
                    <ViolationCard
                      key={v.pk}
                      violation={v}
                      onAcknowledge={handleAcknowledge}
                      onSnooze={handleSnooze}
                      onExempt={handleExempt}
                    />
                  ))}
                </div>
              </section>
            )
          })
        )}
      </div>
    </div>
  )
}
