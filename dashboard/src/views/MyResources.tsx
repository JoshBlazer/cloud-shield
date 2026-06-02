import { useCallback, useEffect, useState } from 'react'
import { mockApi, MOCK_VIOLATIONS } from '../api/mock'
import { ViolationCard } from '../components/ViolationCard'
import type { Violation } from '../types'

const TEAMS = [...new Set(MOCK_VIOLATIONS.map((v) => v.team))].sort()

const REMEDIATION: Record<string, string> = {
  S3_001: 'Go to S3 → your-bucket → Permissions → Block Public Access → enable all four settings.',
  S3_002: 'Go to S3 → your-bucket → Properties → Default encryption → enable SSE-S3 or SSE-KMS.',
  S3_003: 'Go to S3 → your-bucket → Properties → Bucket Versioning → Enable.',
  IAM_001:'Go to IAM → Users → your-user → Security credentials → Assigned MFA device → Manage.',
  IAM_002:'Rotate the access key: IAM → Users → your-user → Security credentials → Create access key, then delete the old one.',
  IAM_003:'Go to IAM → Account settings → Set password policy with min 14 chars, complexity, and 90-day rotation.',
  EC2_001:'Go to EC2 → Security Groups → your-sg → Inbound rules → Remove or restrict port 22 to a specific CIDR.',
  EC2_002:'Go to EC2 → Security Groups → your-sg → Inbound rules → Remove or restrict port 3389.',
  EC2_003:'Go to EC2 → Security Groups → your-sg → Inbound rules → Remove the 0.0.0.0/0 all-traffic rule.',
  EC2_004:'Go to EC2 → Security Groups → your-sg → Inbound rules → Restrict port 80 to a load balancer SG or known CIDR.',
}

export function MyResources() {
  const [team, setTeam]             = useState(TEAMS[0] ?? '')
  const [violations, setViolations] = useState<Violation[]>([])
  const [loading, setLoading]       = useState(true)

  const load = useCallback(async () => {
    if (!team) return
    setLoading(true)
    try {
      const data = await mockApi.listViolations({ team })
      setViolations(data.violations)
    } finally {
      setLoading(false)
    }
  }, [team])

  useEffect(() => { load() }, [load])

  const handleAcknowledge = async (id: string) => { await mockApi.acknowledge(id); load() }
  const handleSnooze      = async (id: string, days: number) => { await mockApi.snooze(id, days); load() }
  const handleExempt      = async (id: string) => { await mockApi.exempt(id, ''); load() }

  const openCount   = violations.filter((v) => v.status === 'OPEN').length
  const totalActive = violations.length

  const countLabel = loading ? 'Loading…'
    : totalActive === 0 ? '0 violations'
    : `${totalActive} active · ${openCount} open`

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div
        className="flex items-center gap-4 px-6 py-4 flex-shrink-0"
        style={{
          background: 'rgba(11,16,25,0.6)',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <h1 className="text-base font-bold text-text">My Resources</h1>

        <select
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          className="text-sm rounded-lg px-3 py-1.5 focus:outline-none transition-colors"
          style={{
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.09)',
            color: '#dde3ef',
          }}
        >
          {TEAMS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <span className="ml-auto text-xs tabular-nums" style={{ color: '#4b5568' }}>
          {countLabel}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {loading ? (
          <div className="text-center py-16" style={{ color: '#4b5568' }}>Loading…</div>
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
            <p className="text-sm font-semibold" style={{ color: '#4ade80' }}>
              Team <span style={{ color: '#dde3ef' }}>{team}</span> is clean
            </p>
            <p className="text-xs mt-1" style={{ color: '#4b5568' }}>No active violations</p>
          </div>
        ) : (
          violations.map((v) => (
            <ViolationCard
              key={v.pk}
              violation={v}
              onAcknowledge={handleAcknowledge}
              onSnooze={handleSnooze}
              onExempt={handleExempt}
              showRemediation={REMEDIATION[v.rule_id]}
            />
          ))
        )}
      </div>
    </div>
  )
}
