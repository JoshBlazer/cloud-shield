import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { LoadMore } from '../components/LoadMore'
import { ViolationCard } from '../components/ViolationCard'
import { usePaginatedViolations } from '../hooks/usePaginatedViolations'

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
  CT_001: 'Go to CloudTrail → Trails → Create trail → apply to all regions and deliver logs to a dedicated S3 bucket.',
  CT_002: 'Go to CloudTrail → Trails → your-trail → General details → Edit → enable Log file validation.',
  RDS_001:'Go to RDS → Databases → your-db → Modify → Connectivity → Additional configuration → set Publicly accessible to No.',
  KMS_001:'Go to KMS → Customer managed keys → your-key → Key rotation → enable automatic key rotation.',
  EBS_001:'Volumes can\'t be encrypted in place: snapshot the volume, copy the snapshot with encryption enabled, and restore from it. Also turn on EC2 → Settings → EBS encryption by default.',
  EBS_003:'Go to EC2 → Snapshots → your-snapshot → Actions → Snapshot settings → Modify permissions → set to Private.',
}

export function MyResources() {
  const [teams, setTeams] = useState<string[]>([])
  const [team, setTeam]   = useState('')

  // Team list comes from /summary so it reflects real data, not the mock set.
  useEffect(() => {
    api.getSummary().then((s) => {
      const names = Object.keys(s.by_team).sort()
      setTeams(names)
      setTeam((current) => current || names[0] || '')
    }).catch(() => setTeams([]))
  }, [])

  // Switching team resets to the first page (handled inside the hook).
  const {
    violations, loading, loadingMore, error, hasMore, loadMore, applyStatusChange,
  } = usePaginatedViolations({ team }, { enabled: !!team })

  const handleAcknowledge = async (id: string) => {
    await api.acknowledge(id)
    applyStatusChange(id, { status: 'ACKNOWLEDGED', acknowledged_by: 'dashboard-user', acknowledged_at: new Date().toISOString() })
  }
  const handleSnooze = async (id: string, days: number) => {
    await api.snooze(id, days)
    applyStatusChange(id, { status: 'SNOOZED', snooze_until: new Date(Date.now() + days * 86_400_000).toISOString() })
  }
  const handleExempt = async (id: string) => {
    await api.exempt(id, '')
    applyStatusChange(id, { status: 'EXEMPTED' })
  }

  // Counts reflect loaded pages only; "+" signals more are available on the server.
  const openCount   = violations.filter((v) => v.status === 'OPEN').length
  const totalActive = violations.length
  const more        = hasMore ? '+' : ''

  const countLabel = loading ? 'Loading…'
    : totalActive === 0 ? '0 violations'
    : `${totalActive}${more} active · ${openCount}${more} open${hasMore ? ' · more available' : ''}`

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
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <span className="ml-auto text-xs tabular-nums" style={{ color: '#4b5568' }}>
          {countLabel}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {loading ? (
          <div className="text-center py-16" style={{ color: '#4b5568' }}>Loading…</div>
        ) : error && violations.length === 0 ? (
          <div className="text-center py-16 text-xs" style={{ color: '#f87171' }}>Failed to load violations: {error}</div>
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
          <>
            {violations.map((v) => (
              <ViolationCard
                key={v.pk}
                violation={v}
                onAcknowledge={handleAcknowledge}
                onSnooze={handleSnooze}
                onExempt={handleExempt}
                showRemediation={REMEDIATION[v.rule_id]}
              />
            ))}
            <LoadMore
              loaded={violations.length}
              hasMore={hasMore}
              loadingMore={loadingMore}
              error={error}
              onLoadMore={loadMore}
            />
          </>
        )}
      </div>
    </div>
  )
}
