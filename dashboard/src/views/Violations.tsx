import { useCallback, useEffect, useState } from 'react'
import { mockApi } from '../api/mock'
import { ViolationCard } from '../components/ViolationCard'
import type { Severity, Status, Violation } from '../types'

const SEVERITIES: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const STATUSES: Status[]     = ['OPEN', 'ACKNOWLEDGED', 'SNOOZED']

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

  const handleAcknowledge = async (id: string) => {
    await mockApi.acknowledge(id)
    load()
  }
  const handleSnooze = async (id: string, days: number) => {
    await mockApi.snooze(id, days)
    load()
  }
  const handleExempt = async (id: string) => {
    await mockApi.exempt(id, 'Manually exempted from dashboard')
    load()
  }

  const grouped: Record<Severity, Violation[]> = {
    CRITICAL: [],
    HIGH:     [],
    MEDIUM:   [],
    LOW:      [],
  }
  for (const v of violations) {
    grouped[v.severity]?.push(v)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border bg-surface flex-shrink-0">
        <h1 className="text-base font-semibold text-text mr-4">Violations</h1>

        <div className="flex gap-1">
          <button
            onClick={() => setStatus('')}
            className={`btn ${statusFilter === '' ? 'btn-primary' : 'btn-secondary'}`}
          >
            All
          </button>
          {STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => setStatus(s)}
              className={`btn ${statusFilter === s ? 'btn-primary' : 'btn-secondary'}`}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="w-px h-5 bg-border mx-1" />

        <select
          value={sevFilter}
          onChange={(e) => setSev(e.target.value as Severity | '')}
          className="bg-[#1a1a1a] border border-border text-subtle text-xs rounded px-2 py-1.5 focus:outline-none focus:border-[#434343]"
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <span className="ml-auto text-xs text-muted">
          {loading ? 'Loading…' : `${violations.length} finding${violations.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
        {loading ? (
          <div className="text-center text-muted py-12">Loading violations…</div>
        ) : violations.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-4xl mb-3">✅</div>
            <p className="text-subtle">No violations match the current filter.</p>
          </div>
        ) : (
          SEVERITIES.map((sev) =>
            grouped[sev].length > 0 ? (
              <section key={sev}>
                <h2 className="text-xs font-bold tracking-widest uppercase mb-3"
                    style={{ color: { CRITICAL: '#ff4d4f', HIGH: '#fa8c16', MEDIUM: '#d4b106', LOW: '#52c41a' }[sev] }}>
                  {sev} — {grouped[sev].length} finding{grouped[sev].length !== 1 ? 's' : ''}
                </h2>
                <div className="space-y-2">
                  {grouped[sev].map((v) => (
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
            ) : null
          )
        )}
      </div>
    </div>
  )
}
