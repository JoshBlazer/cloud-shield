import { useState } from 'react'
import { mockApi } from '../api/mock'
import type { AuditEvent, Violation } from '../types'
import { SeverityBadge } from './SeverityBadge'
import { StatusBadge } from './StatusBadge'

const RESOURCE_ICON: Record<string, string> = {
  'AWS::S3::Bucket':          'S3',
  'AWS::EC2::SecurityGroup':  'SG',
  'AWS::IAM::User':           'IAM',
  'AWS::IAM::AccessKey':      'KEY',
  'AWS::IAM::PasswordPolicy': 'PWD',
  'AWS::IAM::RootAccount':    'ROOT',
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

const ACTION_ICON: Record<string, string> = {
  detect:      '◉',
  acknowledge: '◎',
  snooze:      '◷',
  exempt:      '–',
  resolve:     '✓',
  wake:        '▶',
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
  violation:        Violation
  onAcknowledge:    (id: string) => void
  onSnooze:         (id: string, days: number) => void
  onExempt:         (id: string) => void
  showRemediation?: string
}

export function ViolationCard({ violation: v, onAcknowledge, onSnooze, onExempt, showRemediation }: Props) {
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory]         = useState<AuditEvent[]>([])
  const [loadingHistory, setLoading]  = useState(false)

  const tag        = RESOURCE_ICON[v.resource_type] ?? '??'
  const consoleUrl = AWS_CONSOLE[v.resource_type]?.(v.resource_id, v.region) ?? '#'
  const isOpen     = v.status === 'OPEN'
  const borderClr  = SEV_COLOR[v.severity] ?? '#f87171'

  const toggleHistory = async () => {
    if (!showHistory && history.length === 0) {
      setLoading(true)
      try {
        const data = await mockApi.getViolationHistory(v.violation_id)
        setHistory(data.events)
      } finally {
        setLoading(false)
      }
    }
    setShowHistory((s) => !s)
  }

  return (
    <div
      className={`animate-fade-in rounded-xl overflow-hidden transition-all duration-200 vcard-${v.severity}`}
      style={{
        border: `1px solid rgba(${v.severity === 'CRITICAL' ? '248,113,113' : v.severity === 'HIGH' ? '251,146,60' : v.severity === 'MEDIUM' ? '251,191,36' : '74,222,128'},0.15)`,
        borderLeft: `3px solid ${borderClr}`,
        boxShadow: '0 2px 16px rgba(0,0,0,0.35)',
      }}
    >
      {/* Header */}
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
        {/* Resource row */}
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

        <p className="text-xs leading-relaxed" style={{ color: '#9aa3b5' }}>{v.reason}</p>

        {/* Meta + account context */}
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
          {v.account_id && v.account_id !== 'unknown' && (
            <>
              <span className="mx-2 opacity-30">·</span>
              <span className="font-mono">{v.account_id} / {v.region}</span>
            </>
          )}
        </div>

        {/* History toggle */}
        <button
          onClick={toggleHistory}
          className="text-[11px] transition-colors flex items-center gap-1"
          style={{ color: showHistory ? '#60a5fa' : '#4b5568' }}
        >
          <svg
            width="10" height="10" viewBox="0 0 10 10" fill="none"
            stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
            style={{ transform: showHistory ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
          >
            <path d="M3 1.5l3 3.5-3 3.5"/>
          </svg>
          {showHistory ? 'Hide' : 'Show'} history
        </button>
      </div>

      {/* History timeline */}
      {showHistory && (
        <div className="px-4 pb-3" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          {loadingHistory ? (
            <p className="text-[11px] text-muted py-2">Loading…</p>
          ) : history.length === 0 ? (
            <p className="text-[11px] text-muted py-2">No history recorded yet.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {history.map((e, i) => (
                <div key={i} className="flex items-start gap-2.5 text-[11px]">
                  <span
                    className="mt-0.5 flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center text-[9px]"
                    style={{ background: 'rgba(255,255,255,0.06)', color: '#7a8499' }}
                  >
                    {ACTION_ICON[e.action] ?? '·'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <span className="font-semibold" style={{ color: '#dde3ef' }}>{e.action}</span>
                    {e.actor && <span className="text-muted/60"> by <span style={{ color: '#a78bfa80' }}>{e.actor}</span></span>}
                    {e.context && <span className="text-muted/50"> · {e.context}</span>}
                  </div>
                  <span className="flex-shrink-0 text-muted/40">{timeAgo(e.timestamp)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      {isOpen && (
        <div
          className="flex items-center gap-2 px-4 py-2.5 flex-wrap"
          style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
        >
          <button className="btn btn-primary" onClick={() => onAcknowledge(v.violation_id)}>Acknowledge</button>
          <button className="btn btn-secondary" onClick={() => onSnooze(v.violation_id, 7)}>Snooze 7d</button>
          <button className="btn btn-secondary" onClick={() => onSnooze(v.violation_id, 30)}>Snooze 30d</button>
          <button className="btn btn-ghost" onClick={() => onExempt(v.violation_id)}>Exempt</button>
          <a href={consoleUrl} target="_blank" rel="noreferrer" className="btn btn-ghost ml-auto" style={{ color: '#60a5fa' }}>
            Open in AWS →
          </a>
        </div>
      )}

      {!isOpen && (
        <div className="flex justify-end px-4 py-2" style={{ borderTop: '1px solid rgba(255,255,255,0.03)' }}>
          <a
            href={consoleUrl} target="_blank" rel="noreferrer"
            className="text-[11px] transition-colors" style={{ color: '#4b5568' }}
            onMouseOver={(e) => (e.currentTarget.style.color = '#60a5fa')}
            onMouseOut={(e) => (e.currentTarget.style.color = '#4b5568')}
          >
            Open in AWS →
          </a>
        </div>
      )}

      {showRemediation && (
        <div className="px-4 py-3" style={{ background: 'rgba(96,165,250,0.04)', borderTop: '1px solid rgba(96,165,250,0.1)' }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-1.5" style={{ color: '#60a5fa' }}>How to fix</p>
          <p className="text-xs leading-relaxed" style={{ color: '#7a8499' }}>{showRemediation}</p>
        </div>
      )}
    </div>
  )
}
