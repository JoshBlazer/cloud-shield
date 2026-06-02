import type { Violation } from '../types'
import { SeverityBadge } from './SeverityBadge'
import { StatusBadge } from './StatusBadge'

const RESOURCE_ICON: Record<string, string> = {
  'AWS::S3::Bucket':          'S3',
  'AWS::EC2::SecurityGroup':  'SG',
  'AWS::IAM::User':           'IAM',
  'AWS::IAM::AccessKey':      'KEY',
  'AWS::IAM::PasswordPolicy': 'PWD',
}

const SEV_COLOR: Record<string, string> = {
  CRITICAL: '#f87171',
  HIGH:     '#fb923c',
  MEDIUM:   '#fbbf24',
  LOW:      '#4ade80',
}

const AWS_CONSOLE: Record<string, (id: string, region: string) => string> = {
  'AWS::S3::Bucket':         (id) => `https://s3.console.aws.amazon.com/s3/buckets/${id}`,
  'AWS::EC2::SecurityGroup': (id, r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#SecurityGroups:groupId=${id}`,
  'AWS::IAM::User':          (id) => `https://us-east-1.console.aws.amazon.com/iamv2/home#/users/details/${id}`,
  'AWS::IAM::PasswordPolicy':() => `https://us-east-1.console.aws.amazon.com/iamv2/home#/account_settings`,
  'AWS::IAM::AccessKey':     (id) => `https://us-east-1.console.aws.amazon.com/iamv2/home#/users/details/${id.split('/')[0]}`,
}

function timeAgo(iso: string): string {
  const diff  = Date.now() - new Date(iso).getTime()
  const mins  = Math.floor(diff / 60_000)
  const hours = Math.floor(diff / 3_600_000)
  const days  = Math.floor(diff / 86_400_000)
  if (days > 0)  return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  return `${mins}m ago`
}

interface Props {
  violation: Violation
  onAcknowledge:    (id: string) => void
  onSnooze:         (id: string, days: number) => void
  onExempt:         (id: string) => void
  showRemediation?: string
}

export function ViolationCard({ violation: v, onAcknowledge, onSnooze, onExempt, showRemediation }: Props) {
  const tag        = RESOURCE_ICON[v.resource_type] ?? '??'
  const consoleUrl = AWS_CONSOLE[v.resource_type]?.(v.resource_id, v.region) ?? '#'
  const isOpen     = v.status === 'OPEN'
  const borderClr  = SEV_COLOR[v.severity] ?? '#f87171'

  return (
    <div
      className={`animate-fade-in rounded-xl overflow-hidden transition-all duration-200 vcard-${v.severity}`}
      style={{
        border: `1px solid rgba(${v.severity === 'CRITICAL' ? '248,113,113' : v.severity === 'HIGH' ? '251,146,60' : v.severity === 'MEDIUM' ? '251,191,36' : '74,222,128'},0.15)`,
        borderLeft: `3px solid ${borderClr}`,
        boxShadow: `0 2px 16px rgba(0,0,0,0.35)`,
      }}
    >
      {/* Header row */}
      <div
        className="flex items-center gap-2.5 px-4 py-2.5"
        style={{ background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
      >
        <SeverityBadge severity={v.severity} />
        <span className="text-[10px] text-muted/50 font-mono tracking-wider">{v.rule_id}</span>
        <span className="text-sm text-text font-semibold flex-1 truncate">{v.rule_name}</span>
        <StatusBadge status={v.status} />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2.5">
        {/* Resource chip row */}
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[9px] font-bold px-1.5 py-0.5 rounded"
            style={{ background: 'rgba(255,255,255,0.06)', color: '#7a8499', letterSpacing: '0.05em' }}
          >
            {tag}
          </span>
          <span className="text-[11px] text-muted/60">{v.resource_type}</span>
          <code
            className="text-xs font-mono px-2 py-0.5 rounded-md"
            style={{ background: 'rgba(96,165,250,0.1)', color: '#60a5fa', border: '1px solid rgba(96,165,250,0.2)' }}
          >
            {v.resource_id}
          </code>
          {v.team !== 'untagged' && (
            <span className="ml-auto flex items-center gap-1 text-[11px]">
              <span className="text-muted/40">team</span>
              <span
                className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                style={{ background: 'rgba(167,139,250,0.1)', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.15)' }}
              >
                {v.team}
              </span>
            </span>
          )}
        </div>

        {/* Reason */}
        <p className="text-xs leading-relaxed" style={{ color: '#9aa3b5' }}>{v.reason}</p>

        {/* Timestamps */}
        <div className="flex items-center flex-wrap gap-y-0.5 text-[11px]" style={{ color: '#4b5568' }}>
          <span>First seen {timeAgo(v.first_detected)}</span>
          <span className="mx-2 opacity-30">·</span>
          <span>Last seen {timeAgo(v.last_seen)}</span>
          {v.occurrence_count > 1 && (
            <>
              <span className="mx-2 opacity-30">·</span>
              <span
                className="px-1.5 py-0.5 rounded text-[10px]"
                style={{ background: 'rgba(251,191,36,0.08)', color: '#fbbf24' }}
              >
                {v.occurrence_count}× recurrence
              </span>
            </>
          )}
          {v.acknowledged_by && (
            <>
              <span className="mx-2 opacity-30">·</span>
              <span>Ack'd by <span style={{ color: '#60a5fa80' }}>{v.acknowledged_by}</span></span>
            </>
          )}
        </div>
      </div>

      {/* Action buttons — only for OPEN */}
      {isOpen && (
        <div
          className="flex items-center gap-2 px-4 py-2.5 flex-wrap"
          style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
        >
          <button className="btn btn-primary" onClick={() => onAcknowledge(v.violation_id)}>
            Acknowledge
          </button>
          <button className="btn btn-secondary" onClick={() => onSnooze(v.violation_id, 7)}>
            Snooze 7d
          </button>
          <button className="btn btn-secondary" onClick={() => onSnooze(v.violation_id, 30)}>
            Snooze 30d
          </button>
          <button className="btn btn-ghost" onClick={() => onExempt(v.violation_id)}>
            Exempt
          </button>
          <a
            href={consoleUrl}
            target="_blank"
            rel="noreferrer"
            className="btn btn-ghost ml-auto"
            style={{ color: '#60a5fa' }}
          >
            Open in AWS →
          </a>
        </div>
      )}

      {/* Non-open: just the AWS link */}
      {!isOpen && (
        <div
          className="flex justify-end px-4 py-2"
          style={{ borderTop: '1px solid rgba(255,255,255,0.03)' }}
        >
          <a
            href={consoleUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] transition-colors"
            style={{ color: '#4b5568' }}
            onMouseOver={(e) => (e.currentTarget.style.color = '#60a5fa')}
            onMouseOut={(e) => (e.currentTarget.style.color = '#4b5568')}
          >
            Open in AWS →
          </a>
        </div>
      )}

      {/* Inline remediation (My Resources view) */}
      {showRemediation && (
        <div
          className="px-4 py-3"
          style={{ background: 'rgba(96,165,250,0.04)', borderTop: '1px solid rgba(96,165,250,0.1)' }}
        >
          <p className="text-[10px] font-bold uppercase tracking-widest mb-1.5" style={{ color: '#60a5fa' }}>
            How to fix
          </p>
          <p className="text-xs leading-relaxed" style={{ color: '#7a8499' }}>{showRemediation}</p>
        </div>
      )}
    </div>
  )
}
