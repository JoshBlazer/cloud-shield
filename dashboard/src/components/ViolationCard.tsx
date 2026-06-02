import type { Violation } from '../types'
import { SeverityBadge } from './SeverityBadge'
import { StatusBadge } from './StatusBadge'

const RESOURCE_ICON: Record<string, string> = {
  'AWS::S3::Bucket':          '💿',
  'AWS::EC2::SecurityGroup':  '🛡',
  'AWS::IAM::User':           '👤',
  'AWS::IAM::AccessKey':      '🔑',
  'AWS::IAM::PasswordPolicy': '🔒',
}

const AWS_CONSOLE: Record<string, (id: string, region: string) => string> = {
  'AWS::S3::Bucket':         (id) => `https://s3.console.aws.amazon.com/s3/buckets/${id}`,
  'AWS::EC2::SecurityGroup': (id, r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#SecurityGroups:groupId=${id}`,
  'AWS::IAM::User':          (id) => `https://us-east-1.console.aws.amazon.com/iamv2/home#/users/details/${id}`,
  'AWS::IAM::PasswordPolicy':() => `https://us-east-1.console.aws.amazon.com/iamv2/home#/account_settings`,
  'AWS::IAM::AccessKey':     (id) => `https://us-east-1.console.aws.amazon.com/iamv2/home#/users/details/${id.split('/')[0]}`,
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins  = Math.floor(diff / 60_000)
  const hours = Math.floor(diff / 3_600_000)
  const days  = Math.floor(diff / 86_400_000)
  if (days > 0)  return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  return `${mins}m ago`
}

interface Props {
  violation: Violation
  onAcknowledge: (id: string) => void
  onSnooze:      (id: string, days: number) => void
  onExempt:      (id: string) => void
}

export function ViolationCard({ violation: v, onAcknowledge, onSnooze, onExempt }: Props) {
  const icon       = RESOURCE_ICON[v.resource_type] ?? '●'
  const consoleUrl = AWS_CONSOLE[v.resource_type]?.(v.resource_id, v.region) ?? '#'
  const isActive   = v.status === 'OPEN'

  return (
    <div className="card" style={{ borderLeft: `3px solid var(--tw-color-${v.severity.toLowerCase()}, #ff4d4f)` }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 bg-[#1a1a1a] border-b border-border">
        <SeverityBadge severity={v.severity} />
        <span className="text-xs text-muted font-mono">{v.rule_id}</span>
        <span className="text-sm text-text font-medium flex-1">{v.rule_name}</span>
        <StatusBadge status={v.status} />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-base">{icon}</span>
          <span className="text-xs text-muted">{v.resource_type}</span>
          <code className="text-xs text-accent bg-[#111d2c] px-1.5 py-0.5 rounded">
            {v.resource_id}
          </code>
          {v.team !== 'untagged' && (
            <span className="ml-auto text-xs text-muted">
              team: <span className="text-subtle">{v.team}</span>
            </span>
          )}
        </div>
        <p className="text-xs text-subtle">{v.reason}</p>

        <div className="flex items-center gap-3 text-[11px] text-muted pt-1">
          <span>First seen: {timeAgo(v.first_detected)}</span>
          <span>·</span>
          <span>Last seen: {timeAgo(v.last_seen)}</span>
          {v.occurrence_count > 1 && (
            <>
              <span>·</span>
              <span>{v.occurrence_count}× recurrence</span>
            </>
          )}
          {v.acknowledged_by && (
            <>
              <span>·</span>
              <span>Ack'd by {v.acknowledged_by}</span>
            </>
          )}
        </div>
      </div>

      {/* Actions */}
      {isActive && (
        <div className="flex items-center gap-2 px-4 py-2 border-t border-border">
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
          >
            Open in AWS →
          </a>
        </div>
      )}
    </div>
  )
}
