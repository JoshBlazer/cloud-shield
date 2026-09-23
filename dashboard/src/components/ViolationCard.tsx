import { memo, useEffect, useId, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { consoleUrl, remediation, resourceTag, SEV_STYLE } from '../lib/catalog'
import { fullDate, relativeTime } from '../lib/format'
import type { AuditEvent, TriageAction, Violation } from '../types'
import { SeverityBadge, StatusBadge } from './Badges'
import { Dialog } from './Dialog'
import { Icon, Spinner } from './Icon'
import { Menu } from './Menu'

interface Props {
  violation: Violation
  busy?:     boolean
  leaving?:  boolean
  onAction:  (v: Violation, action: TriageAction, arg?: number | string) => void
  /** Open the "how to fix" panel by default (the My Resources view does). */
  defaultFixOpen?: boolean
}

const SNOOZE_OPTIONS = [
  { days: 1,  label: '1 day' },
  { days: 7,  label: '7 days' },
  { days: 30, label: '30 days' },
]

const ACTION_LABEL: Record<string, string> = {
  detect: 'Detected', acknowledge: 'Acknowledged', snooze: 'Snoozed', exempt: 'Exempted',
  resolve: 'Resolved', wake: 'Snooze expired', reopen: 'Reopened',
}
const ACTION_ICON: Record<string, string> = {
  detect: 'sparkle', acknowledge: 'eye', snooze: 'clock', exempt: 'slash', resolve: 'check', wake: 'play', reopen: 'undo',
}

function Time({ iso, prefix }: { iso: string | null; prefix?: string }) {
  if (!iso) return null
  return <time dateTime={iso} title={fullDate(iso)}>{prefix}{relativeTime(iso)}</time>
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="btn btn-ghost btn-icon h-6 min-h-0 w-6 flex-shrink-0 rounded-md text-faint"
      aria-label={copied ? 'Copied' : 'Copy resource ID'}
      title={copied ? 'Copied' : 'Copy resource ID'}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1400)
        } catch { /* clipboard unavailable (insecure context) */ }
      }}
    >
      <Icon name={copied ? 'check' : 'copy'} size={12} className={copied ? 'text-low' : ''} />
    </button>
  )
}

function ViolationCardImpl({ violation: v, busy = false, leaving = false, onAction, defaultFixOpen = false }: Props) {
  const [detailsOpen, setDetailsOpen] = useState(defaultFixOpen)
  const [history, setHistory]         = useState<AuditEvent[] | null>(null)
  const [historyError, setHistoryErr] = useState<string | null>(null)
  const [exemptOpen, setExemptOpen]   = useState(false)
  const [reason, setReason]           = useState('')
  const detailsId = useId()

  const sev   = SEV_STYLE[v.severity]
  const fix   = remediation(v.rule_id)
  const link  = consoleUrl(v)
  const tag   = resourceTag(v)
  const count = Number(v.occurrence_count) || 1

  // Load the lifecycle history the first time details are shown — whether the
  // user opened them or the card started open.
  useEffect(() => {
    if (!detailsOpen || history !== null) return
    let live = true
    setHistoryErr(null)
    api.getViolationHistory(v.violation_id)
      .then((r) => { if (live) setHistory(r.events) })
      .catch((e) => { if (live) setHistoryErr(errorMessage(e)) })
    return () => { live = false }
  }, [detailsOpen, history, v.violation_id])

  // A status change means new history; drop the cached copy.
  useEffect(() => { setHistory(null) }, [v.status])

  const toggleDetails = () => setDetailsOpen((o) => !o)

  const submitExempt = () => {
    const r = reason.trim()
    if (!r) return
    setExemptOpen(false)
    setReason('')
    onAction(v, 'exempt', r)
  }

  const snoozeMenu = (
    <Menu
      items={SNOOZE_OPTIONS.map((o) => ({ label: `Snooze ${o.label}`, onSelect: () => onAction(v, 'snooze', o.days) }))}
      trigger={(p) => (
        <button {...p} className="btn btn-secondary" disabled={busy}>
          <Icon name="clock" size={13} /> Snooze <Icon name="chevron-down" size={11} />
        </button>
      )}
    />
  )
  const exemptBtn = (
    <button className="btn btn-ghost" disabled={busy} onClick={() => setExemptOpen(true)}>
      <Icon name="slash" size={13} /> Exempt…
    </button>
  )
  const reopenBtn = (
    <button className="btn btn-secondary" disabled={busy} onClick={() => onAction(v, 'reopen')}>
      <Icon name="undo" size={13} /> Reopen
    </button>
  )

  return (
    <div className={`card-wrap ${leaving ? 'card-leave' : ''}`} aria-hidden={leaving || undefined}>
      <article
        aria-busy={busy || undefined}
        aria-label={`${v.severity} ${v.rule_name}: ${v.resource_id}`}
        className="group relative overflow-hidden rounded-xl border transition-[border-color,box-shadow,transform] duration-200
                   hover:-translate-y-px"
        style={{
          borderColor: `rgba(${sev.rgb},0.16)`,
          background: `linear-gradient(135deg, rgba(${sev.rgb},0.05) 0%, rgba(15,23,36,0.9) 40%, rgba(11,16,25,0.9) 100%)`,
          boxShadow: '0 2px 16px rgba(0,0,0,0.35)',
        }}
      >
        {/* Severity rail */}
        <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: sev.color, boxShadow: `0 0 12px ${sev.color}` }} aria-hidden="true" />

        {/* Busy veil */}
        {busy && (
          <div className="absolute inset-0 z-10 flex animate-fade-in items-center justify-center bg-bg/40 backdrop-blur-[1px]">
            <span className="flex items-center gap-2 rounded-full border border-white/10 bg-card px-3 py-1.5 text-xs text-subtle">
              <Spinner size={12} /> Saving…
            </span>
          </div>
        )}

        {/* Header */}
        <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 border-b border-white/[0.04] bg-white/[0.02] py-2.5 pl-5 pr-4">
          <SeverityBadge severity={v.severity} />
          <h3 className="min-w-0 flex-1 basis-40 text-sm font-semibold leading-snug text-text">{v.rule_name}</h3>
          <span className="hidden font-mono text-[10px] tracking-wider text-faint sm:inline">{v.rule_id}</span>
          <StatusBadge status={v.status} />
        </header>

        {/* Body */}
        <div className="space-y-2.5 py-3 pl-5 pr-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] font-bold tracking-wider text-subtle">{tag}</span>
            <span className="flex min-w-0 max-w-full items-center gap-0.5 rounded-md border border-accent/20 bg-accent/10 pl-2 pr-0.5">
              <code className="truncate py-0.5 font-mono text-xs text-accent" title={v.resource_id}>{v.resource_id}</code>
              <CopyButton text={v.resource_id} />
            </span>
            {v.team && v.team !== 'untagged' && (
              <span className="ml-auto rounded border border-violet/20 bg-violet/10 px-1.5 py-0.5 text-[10px] font-semibold text-violet">
                {v.team}
              </span>
            )}
          </div>

          <p className="text-[13px] leading-relaxed text-subtle">{v.reason}</p>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
            <Time iso={v.first_detected} prefix="First seen " />
            <Time iso={v.last_seen} prefix="Last seen " />
            {count > 1 && (
              <span className="rounded bg-medium/10 px-1.5 py-0.5 font-medium text-medium" title="Times this finding was re-detected by the auditor">
                Seen {count.toLocaleString()}×
              </span>
            )}
            {v.status === 'ACKNOWLEDGED' && v.acknowledged_by && (
              <span>Acknowledged by <span className="text-accent">{v.acknowledged_by}</span></span>
            )}
            {v.status === 'SNOOZED' && v.snooze_until && (
              <span className="text-high">Snoozed until <time dateTime={v.snooze_until} title={fullDate(v.snooze_until)}>{fullDate(v.snooze_until)}</time></span>
            )}
            {v.status === 'RESOLVED' && v.resolved_at && <Time iso={v.resolved_at} prefix="Resolved " />}
            {v.account_id && v.account_id !== 'unknown' && (
              <span className="font-mono text-faint">{v.account_id} · {v.region}</span>
            )}
          </div>

          {v.status === 'EXEMPTED' && v.exempt_reason && (
            <p className="rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-2 text-xs text-muted">
              <span className="font-semibold text-subtle">Exemption:</span> {v.exempt_reason}
            </p>
          )}

          <button
            onClick={toggleDetails}
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            className="-ml-1 flex items-center gap-1 rounded px-1 py-0.5 text-[11px] font-medium text-muted transition-colors hover:text-text"
          >
            <Icon name="chevron" size={11} className={`transition-transform duration-200 ${detailsOpen ? 'rotate-90' : ''}`} />
            {detailsOpen ? 'Hide details' : 'How to fix & history'}
          </button>
        </div>

        {/* Details: remediation + lifecycle timeline */}
        <div id={detailsId} className="collapse-grid" data-open={detailsOpen}>
          <div>
            <div className="grid gap-4 border-t border-white/[0.04] py-3.5 pl-5 pr-4 md:grid-cols-2">
              {fix && (
                <section>
                  <p className="eyebrow mb-1.5 flex items-center gap-1.5 text-accent"><Icon name="wrench" size={11} /> How to fix</p>
                  <p className="text-xs leading-relaxed text-subtle">{fix}</p>
                </section>
              )}
              <section>
                <p className="eyebrow mb-2">History</p>
                {historyError ? (
                  <p className="text-xs text-critical">Couldn't load history: {historyError}</p>
                ) : history === null ? (
                  <div className="space-y-2"><div className="skeleton h-3 w-2/3" /><div className="skeleton h-3 w-1/2" /></div>
                ) : history.length === 0 ? (
                  <p className="text-xs text-muted">No lifecycle events recorded yet.</p>
                ) : (
                  <ol className="relative space-y-2.5 border-l border-white/10 pl-4">
                    {history.map((e, i) => (
                      <li key={`${e.timestamp}-${i}`} className="relative text-xs">
                        <span className="absolute -left-[23px] top-0 flex h-[14px] w-[14px] items-center justify-center rounded-full border border-white/10 bg-card text-muted">
                          <Icon name={ACTION_ICON[e.action] ?? 'info'} size={8} strokeWidth={2} />
                        </span>
                        <span className="font-medium text-text">{ACTION_LABEL[e.action] ?? e.action}</span>
                        {e.actor && <span className="text-muted"> by <span className="text-violet">{e.actor}</span></span>}
                        {e.context && <span className="text-muted"> · {e.context}</span>}
                        <Time iso={e.timestamp} prefix=" · " />
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </div>
          </div>
        </div>

        {/* Actions */}
        <footer className="flex flex-wrap items-center gap-2 border-t border-white/[0.04] py-2.5 pl-5 pr-4">
          {v.status === 'OPEN' && (
            <>
              <button className="btn btn-primary" disabled={busy} onClick={() => onAction(v, 'acknowledge')}>
                <Icon name="eye" size={13} /> Acknowledge
              </button>
              {snoozeMenu}
              {exemptBtn}
            </>
          )}
          {v.status === 'ACKNOWLEDGED' && <>{snoozeMenu}{exemptBtn}{reopenBtn}</>}
          {v.status === 'SNOOZED' && <>{reopenBtn}{exemptBtn}</>}
          {v.status === 'EXEMPTED' && reopenBtn}
          <a href={link} target="_blank" rel="noreferrer" className="btn btn-ghost ml-auto text-accent hover:text-accent">
            Open in AWS <Icon name="external" size={12} />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </footer>
      </article>

      <Dialog
        open={exemptOpen}
        onClose={() => setExemptOpen(false)}
        title="Exempt this finding?"
        description="It stays tracked and is re-checked every audit, but never alerts again until reopened."
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setExemptOpen(false)}>Cancel</button>
            <button className="btn btn-accent" onClick={submitExempt} disabled={!reason.trim()}>Exempt finding</button>
          </>
        }
      >
        <p className="mb-3 text-xs text-muted">
          <span className="font-semibold text-subtle">{v.rule_name}</span> on <code className="break-all font-mono text-accent">{v.resource_id}</code>
        </p>
        <label className="mb-1.5 block text-xs font-semibold text-subtle" htmlFor={`${detailsId}-reason`}>
          Reason <span className="font-normal text-muted">(recorded in the audit trail)</span>
        </label>
        <textarea
          id={`${detailsId}-reason`}
          className="input min-h-[88px] resize-y"
          placeholder="e.g. Accepted risk — internal-only bucket behind VPC endpoint; reviewed by security on 2026-09-20"
          value={reason}
          maxLength={500}
          onChange={(e) => setReason(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitExempt() }}
        />
        <p className="mt-1 text-right text-[11px] text-faint tabular">{reason.length}/500</p>
      </Dialog>
    </div>
  )
}

export const ViolationCard = memo(ViolationCardImpl)
