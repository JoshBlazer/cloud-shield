import { useState } from 'react'
import { fullDate, plural, relativeTime } from '../lib/format'
import { useAppData } from '../state/AppData'
import { Icon } from './Icon'

const SERVICE_LABEL: Record<string, string> = {
  s3: 'S3', iam: 'IAM', ec2: 'EC2', cloudtrail: 'CloudTrail', rds: 'RDS', kms: 'KMS', ebs: 'EBS',
}

/**
 * Shown when the latest audit couldn't read part of the estate — usually a
 * missing permission on a member account's CloudShieldAuditRole, or a failed
 * assume-role. Findings in those scopes are held open rather than resolved, so
 * the counts elsewhere are still trustworthy; this says why they didn't move.
 */
export function ScanHealthBanner() {
  const { summary } = useAppData()
  const [open, setOpen] = useState(false)
  const run = summary?.last_run
  const scopes = run?.incomplete_scopes ?? []
  if (!run || scopes.length === 0) return null

  const accessIssue = scopes.some((s) => s.errors.some((e) => /AccessDenied|UnauthorizedOperation|AuthorizationError|AssumeRole/i.test(e)))

  return (
    <div role="status" className="mb-5 animate-fade-up overflow-hidden rounded-xl border border-medium/25 bg-medium/[0.06]">
      <div className="flex items-start gap-3 px-4 py-3">
        <Icon name="alert" size={16} className="mt-0.5 flex-shrink-0 text-medium" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-text">
            The last audit couldn't read {plural(scopes.length, 'scan')}
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            {run.held_back > 0
              ? <>{plural(run.held_back, 'finding')} in those scans {run.held_back === 1 ? 'is' : 'are'} kept open instead of being marked resolved. </>
              : <>Nothing was resolved in those scans. </>}
            {accessIssue
              ? <>This is usually a missing permission: redeploy <code className="font-mono text-subtle">member-account-role.yaml</code> in the affected accounts (<code className="font-mono text-subtle">make member-role</code>).</>
              : <>It should clear on the next run; if it doesn't, check the auditor logs.</>}
          </p>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="btn btn-ghost flex-shrink-0 text-medium hover:text-medium"
        >
          {open ? 'Hide' : 'Details'}
        </button>
      </div>
      <div className="collapse-grid" data-open={open}>
        <div>
          <ul className="space-y-1.5 border-t border-medium/15 px-4 py-3">
            {scopes.map((s, i) => (
              <li key={i} className="text-xs text-muted">
                <span className="font-semibold text-subtle">{SERVICE_LABEL[s.service] ?? s.service}</span>
                <span className="font-mono text-faint"> · {s.account_id || 'default account'} · {s.region}</span>
                <span className="block break-words font-mono text-[11px] text-faint">{s.errors.slice(0, 3).join(' · ')}</span>
              </li>
            ))}
            <li className="pt-1 text-[11px] text-faint">
              Audit finished <time dateTime={run.finished_at} title={fullDate(run.finished_at)}>{relativeTime(run.finished_at)}</time>
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
