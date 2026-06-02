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

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-4 px-6 py-4 border-b border-border bg-surface flex-shrink-0">
        <h1 className="text-base font-semibold text-text">My Resources</h1>
        <select
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          className="bg-[#1a1a1a] border border-border text-text text-sm rounded px-3 py-1.5 focus:outline-none focus:border-[#434343]"
        >
          {TEAMS.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted">
          {loading ? 'Loading…' : `${violations.length} open violation${violations.length !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* Cards with inline remediation */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {loading ? (
          <div className="text-center text-muted py-12">Loading…</div>
        ) : violations.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-4xl mb-3">✅</div>
            <p className="text-subtle">Team <strong className="text-text">{team}</strong> has no open violations.</p>
          </div>
        ) : (
          violations.map((v) => (
            <div key={v.pk}>
              <ViolationCard
                violation={v}
                onAcknowledge={handleAcknowledge}
                onSnooze={handleSnooze}
                onExempt={handleExempt}
              />
              {REMEDIATION[v.rule_id] && (
                <div className="mt-1 mx-0.5 px-4 py-2.5 bg-[#111] border border-border border-t-0 rounded-b-lg">
                  <p className="text-[11px] text-muted uppercase tracking-widest mb-1 font-semibold">How to fix</p>
                  <p className="text-xs text-subtle">{REMEDIATION[v.rule_id]}</p>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
