/**
 * In-memory mock of the CloudShield API, used when VITE_USE_MOCK isn't "false".
 *
 * It follows the real API's contract (filters, cursor paging, lifecycle rules,
 * error codes) and derives every aggregate — /summary, /trend, history — from
 * one dataset, so the numbers on screen always agree with each other and move
 * when you triage something. Set VITE_USE_MOCK=false to hit API Gateway.
 */
import { RULES } from '../lib/catalog'
import type {
  AuditEvent, AuditTriggerResult, Severity, Status, Summary, TrendPoint, Violation,
  ViolationPage, ViolationQuery,
} from '../types'
import { ACTIVE_STATUSES } from '../types'
import { ApiError } from './errors'

const ACCOUNT = '123456789012'
const REGION  = 'us-east-1'
const HOUR    = 3_600_000
const DAY     = 24 * HOUR

// ── Deterministic dataset ────────────────────────────────────────────────────

/** Small seeded PRNG so the demo looks the same on every load. */
function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rand = rng(20260923)
const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(rand() * xs.length)]
const hex  = (n: number) => Array.from({ length: n }, () => Math.floor(rand() * 16).toString(16)).join('')

interface Seed {
  rule_id: string
  resource_type: string
  ids: string[]
  reason: (id: string) => string
  teams: string[]
}

const SEEDS: Seed[] = [
  { rule_id: 'S3_001', resource_type: 'AWS::S3::Bucket', teams: ['data-platform', 'backend'],
    ids: ['acme-raw-data-prod', 'acme-uploads-prod', 'acme-ml-features', 'acme-exports-legacy'],
    reason: () => 'Public access block is not fully enabled' },
  { rule_id: 'S3_002', resource_type: 'AWS::S3::Bucket', teams: ['data-platform', 'backend'],
    ids: ['acme-raw-data-prod', 'acme-ml-features', 'acme-clickstream', 'acme-exports-legacy', 'acme-tmp-scratch'],
    reason: () => 'Default server-side encryption is not configured' },
  { rule_id: 'S3_003', resource_type: 'AWS::S3::Bucket', teams: ['data-platform', 'platform'],
    ids: ['acme-raw-data-prod', 'acme-clickstream', 'acme-tmp-scratch', 'acme-terraform-state'],
    reason: () => 'Versioning is not enabled' },
  { rule_id: 'S3_004', resource_type: 'AWS::S3::Bucket', teams: ['backend'],
    ids: ['acme-public-assets'],
    reason: () => "Bucket policy grants s3:GetObject to Principal '*'" },
  { rule_id: 'IAM_001', resource_type: 'AWS::IAM::User', teams: ['backend', 'infra', 'data-platform'],
    ids: ['alice', 'deploy-bot-legacy', 'mkumar', 'ops-breakglass'],
    reason: (id) => `User '${id}' has console access but no MFA device` },
  { rule_id: 'IAM_002', resource_type: 'AWS::IAM::AccessKey', teams: ['infra', 'backend'],
    ids: ['ci-runner/AKIA4EXAMPLE7Q2M', 'etl-service/AKIA4EXAMPLE9Z1K', 'metrics-push/AKIA4EXAMPLE3X8P'],
    reason: (id) => `Access key ${id.split('/')[1]} for '${id.split('/')[0]}' is ${Math.floor(95 + rand() * 200)} days old` },
  { rule_id: 'IAM_003', resource_type: 'AWS::IAM::PasswordPolicy', teams: ['platform'],
    ids: ['account-password-policy'],
    reason: () => 'No account password policy is configured' },
  { rule_id: 'IAM_004', resource_type: 'AWS::IAM::RootAccount', teams: ['platform'],
    ids: ['root'],
    reason: () => 'Root account does not have MFA enabled' },
  { rule_id: 'EC2_001', resource_type: 'AWS::EC2::SecurityGroup', teams: ['infra'],
    ids: ['web-tier-sg', 'bastion-old-sg', 'jenkins-agents-sg', 'k8s-nodes-debug-sg'],
    reason: (name) => `Security group '${name}' allows port 22 from 0.0.0.0/0` },
  { rule_id: 'EC2_002', resource_type: 'AWS::EC2::SecurityGroup', teams: ['infra'],
    ids: ['win-build-sg'],
    reason: (name) => `Security group '${name}' allows port 3389 from 0.0.0.0/0` },
  { rule_id: 'EC2_003', resource_type: 'AWS::EC2::SecurityGroup', teams: ['infra', 'backend'],
    ids: ['dev-sandbox-sg', 'poc-demo-sg'],
    reason: (name) => `Security group '${name}' allows all traffic from 0.0.0.0/0` },
  { rule_id: 'EC2_004', resource_type: 'AWS::EC2::SecurityGroup', teams: ['backend', 'infra'],
    ids: ['web-tier-sg', 'status-page-sg', 'poc-demo-sg'],
    reason: (name) => `Security group '${name}' allows port 80 from 0.0.0.0/0` },
  { rule_id: 'CT_001', resource_type: 'AWS::::Account', teams: ['platform'],
    ids: [`${ACCOUNT}:eu-west-1:cloudtrail`],
    reason: () => 'No logging CloudTrail trail covers eu-west-1' },
  { rule_id: 'CT_002', resource_type: 'AWS::CloudTrail::Trail', teams: ['platform'],
    ids: [`arn:aws:cloudtrail:${REGION}:${ACCOUNT}:trail/org-audit-trail`],
    reason: () => "Trail 'org-audit-trail' does not have log file validation enabled" },
  { rule_id: 'CT_003', resource_type: 'AWS::CloudTrail::Trail', teams: ['platform'],
    ids: [`arn:aws:cloudtrail:${REGION}:${ACCOUNT}:trail/org-audit-trail`],
    reason: () => "Trail 'org-audit-trail' logs are not encrypted with a KMS key" },
  { rule_id: 'RDS_001', resource_type: 'AWS::RDS::DBInstance', teams: ['data-platform'],
    ids: ['orders-db-prod', 'legacy-reporting-db'].map((d) => `arn:aws:rds:${REGION}:${ACCOUNT}:db:${d}`),
    reason: (arn) => `RDS instance '${arn.split(':').pop()}' is publicly accessible` },
  { rule_id: 'RDS_002', resource_type: 'AWS::RDS::DBInstance', teams: ['data-platform'],
    ids: ['legacy-reporting-db', 'analytics-replica'].map((d) => `arn:aws:rds:${REGION}:${ACCOUNT}:db:${d}`),
    reason: (arn) => `RDS instance '${arn.split(':').pop()}' does not have storage encryption enabled` },
  { rule_id: 'RDS_003', resource_type: 'AWS::RDS::DBInstance', teams: ['data-platform', 'backend'],
    ids: ['legacy-reporting-db', 'feature-flags-db', 'sessions-db'].map((d) => `arn:aws:rds:${REGION}:${ACCOUNT}:db:${d}`),
    reason: (arn) => `RDS instance '${arn.split(':').pop()}' retains backups for 1 day(s); minimum is 7` },
  { rule_id: 'KMS_001', resource_type: 'AWS::KMS::Key', teams: ['platform', 'data-platform'],
    ids: Array.from({ length: 3 }, () => `arn:aws:kms:${REGION}:${ACCOUNT}:key/${hex(8)}-${hex(4)}-${hex(4)}-${hex(4)}-${hex(12)}`),
    reason: (arn) => `KMS key '${arn.split('/').pop()}' does not have automatic rotation enabled` },
  { rule_id: 'EBS_001', resource_type: 'AWS::EC2::Volume', teams: ['infra', 'backend'],
    ids: Array.from({ length: 5 }, () => `vol-0${hex(16)}`),
    reason: (id) => `EBS volume '${id}' is not encrypted` },
  { rule_id: 'EBS_002', resource_type: 'AWS::::Account', teams: ['platform'],
    ids: [`${ACCOUNT}:${REGION}:ebs-encryption-by-default`],
    reason: () => `EBS encryption by default is disabled in ${REGION}` },
  { rule_id: 'EBS_003', resource_type: 'AWS::EC2::Snapshot', teams: ['infra'],
    ids: [`snap-0${hex(16)}`],
    reason: (id) => `EBS snapshot '${id}' is shared publicly` },
]

const OWNER: Record<string, string> = {
  'data-platform': 'data@acme.com', backend: 'backend@acme.com', infra: 'infra@acme.com', platform: 'platform@acme.com',
}
const PEOPLE = ['alice@acme.com', 'mkumar@acme.com', 'jchen@acme.com', 'sre-oncall']

function buildDataset(now: number): { items: Violation[]; history: Record<string, AuditEvent[]> } {
  const items: Violation[] = []
  const history: Record<string, AuditEvent[]> = {}
  const ev = (v: Violation, t: number, action: string, actor: string, from: string, to: string, context = '') =>
    (history[v.violation_id] ??= []).unshift({
      violation_id: v.violation_id, timestamp: new Date(t).toISOString(),
      action, actor, from_status: from, to_status: to, context,
    })

  for (const seed of SEEDS) {
    const rule = RULES[seed.rule_id]
    for (const rawId of seed.ids) {
      // Security groups are keyed by id; the seed gives a readable name for the reason.
      const resourceId = seed.resource_type === 'AWS::EC2::SecurityGroup' ? `sg-0${hex(16)}` : rawId
      const firstSeen  = now - Math.floor(1 + rand() * 20) * DAY - Math.floor(rand() * 12) * HOUR
      const hoursAgo   = Math.floor(rand() * 3)
      const v: Violation = {
        pk: `${seed.rule_id}#${resourceId}`,
        violation_id: `v-${seed.rule_id.toLowerCase()}-${hex(10)}`,
        rule_id: seed.rule_id, rule_name: rule.name, severity: rule.severity,
        resource_type: seed.resource_type, resource_id: resourceId,
        reason: seed.reason(rawId),
        status: 'OPEN', first_detected: new Date(firstSeen).toISOString(),
        last_seen: new Date(now - hoursAgo * HOUR).toISOString(),
        occurrence_count: Math.max(1, Math.floor((now - firstSeen) / HOUR)),
        resolved_at: null, acknowledged_by: null, acknowledged_at: null, snooze_until: null,
        exempt_reason: null, team: pick(seed.teams), owner: null, region: REGION, account_id: ACCOUNT,
      }
      v.owner = OWNER[v.team] ?? null
      ev(v, firstSeen, 'detect', 'auditor', '', 'OPEN')

      // Spread the dataset across the lifecycle.
      const roll = rand()
      if (roll < 0.12) {
        const t = firstSeen + Math.floor(rand() * 3 + 1) * DAY
        v.status = 'RESOLVED'; v.resolved_at = new Date(Math.min(t, now - HOUR)).toISOString()
        ev(v, Date.parse(v.resolved_at), 'resolve', 'auditor', 'OPEN', 'RESOLVED')
      } else if (roll < 0.2) {
        v.status = 'ACKNOWLEDGED'; v.acknowledged_by = pick(PEOPLE)
        v.acknowledged_at = new Date(firstSeen + 6 * HOUR).toISOString()
        ev(v, Date.parse(v.acknowledged_at), 'acknowledge', v.acknowledged_by, 'OPEN', 'ACKNOWLEDGED')
      } else if (roll < 0.26) {
        v.status = 'SNOOZED'; v.snooze_until = new Date(now + Math.floor(2 + rand() * 20) * DAY).toISOString()
        ev(v, now - 2 * DAY, 'snooze', 'dashboard-user', 'OPEN', 'SNOOZED', '30d')
      } else if (roll < 0.3) {
        v.status = 'EXEMPTED'; v.exempt_reason = 'Accepted risk: internal-only resource behind VPN'
        ev(v, now - 3 * DAY, 'exempt', 'dashboard-user', 'OPEN', 'EXEMPTED', v.exempt_reason)
      }
      items.push(v)
    }
  }
  return { items, history }
}

const NOW_AT_LOAD = Date.now()
const dataset     = buildDataset(NOW_AT_LOAD)
let violations    = dataset.items
const history     = dataset.history

/** Seven-to-fourteen day history of active findings, ending at today's real counts. */
function buildTrend(days: number): TrendPoint[] {
  const today = activeBySeverity()
  const r = rng(7)
  const out: TrendPoint[] = []
  for (let i = days - 1; i >= 0; i--) {
    const date  = new Date(NOW_AT_LOAD - i * DAY).toISOString().slice(0, 10)
    // Walk backwards from today's numbers: a bit worse in the past, trending down.
    const drift = (sev: Severity, weight: number) =>
      i === 0 ? today[sev] : Math.max(0, Math.round(today[sev] + i * weight * (0.6 + r() * 0.8) + (r() - 0.5) * 2))
    const p = { date, CRITICAL: drift('CRITICAL', 0.45), HIGH: drift('HIGH', 0.3), MEDIUM: drift('MEDIUM', 0.25), LOW: drift('LOW', 0) }
    out.push({ ...p, total_active: p.CRITICAL + p.HIGH + p.MEDIUM + p.LOW })
  }
  return out
}

function activeBySeverity(): Record<Severity, number> {
  const out = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
  for (const v of violations) if (ACTIVE_STATUSES.includes(v.status)) out[v.severity]++
  return out
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function delay<T>(val: T, ms = 220 + Math.random() * 260): Promise<T> {
  return new Promise((res) => setTimeout(() => res(structuredClone(val)), ms))
}

function find(id: string): Violation {
  const v = violations.find((x) => x.violation_id === id)
  if (!v) throw new ApiError('violation not found', 404)
  return v
}

function transition(id: string, to: Status, action: string, actor: string, patch: Partial<Violation>, context = '') {
  const v = find(id)
  const from = v.status
  violations = violations.map((x) => x.violation_id === id ? { ...x, ...patch, status: to } : x)
  ;(history[id] ??= []).unshift({
    violation_id: id, timestamp: new Date().toISOString(), action, actor,
    from_status: from, to_status: to, context,
  })
}

// ── Pagination (keyset: severity rank, then most recently seen) ──────────────

const DEFAULT_LIMIT = 200
const MAX_LIMIT     = 500
const SEV_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

type CursorKey = [number, string]
const sortKey = (v: Violation): CursorKey => [SEV_RANK[v.severity] ?? 9, `${9e15 - Date.parse(v.last_seen)}|${v.pk}`]
function compareKeys(a: CursorKey, b: CursorKey): number {
  if (a[0] !== b[0]) return a[0] - b[0]
  return a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0
}
const fingerprint = (p: ViolationQuery) => [p.status ?? '', p.severity ?? '', p.team ?? ''].join('|')
const encodeCursor = (c: { k: CursorKey; f: string }) => btoa(unescape(encodeURIComponent(JSON.stringify(c))))
function decodeCursor(token: string): { k: CursorKey; f: string } | null {
  try {
    const c = JSON.parse(decodeURIComponent(escape(atob(token))))
    return Array.isArray(c?.k) && typeof c.f === 'string' ? c : null
  } catch { return null }
}

// ── Public mock API (same shape as the HTTP client) ─────────────────────────

let auditRuns = 0

export const mockApi = {
  listViolations(params: ViolationQuery = {}): Promise<ViolationPage> {
    const limit = Math.min(MAX_LIMIT, Math.max(1, Math.floor(params.limit ?? DEFAULT_LIMIT)))
    const fp    = fingerprint(params)
    let after: CursorKey | null = null
    if (params.cursor) {
      const decoded = decodeCursor(params.cursor)
      if (!decoded || decoded.f !== fp) return Promise.reject(new ApiError('invalid cursor', 400))
      after = decoded.k
    }

    // Like the real API: no status filter means every status, resolved included.
    let items = violations
    if (params.status)   items = items.filter((v) => v.status === params.status)
    if (params.severity) items = items.filter((v) => v.severity === params.severity)
    if (params.team)     items = items.filter((v) => v.team === params.team)
    items = [...items].sort((a, b) => compareKeys(sortKey(a), sortKey(b)))
    if (after) { const start = after; items = items.filter((v) => compareKeys(sortKey(v), start) > 0) }

    const page = items.slice(0, limit)
    const next = items.length > limit ? encodeCursor({ k: sortKey(page[page.length - 1]), f: fp }) : null
    return delay({ violations: page, count: page.length, next_cursor: next })
  },

  getViolationHistory(violationId: string) {
    return delay({ violation_id: violationId, events: history[violationId] ?? [] })
  },

  async acknowledge(violationId: string, by = 'dashboard-user') {
    transition(violationId, 'ACKNOWLEDGED', 'acknowledge', by, {
      acknowledged_by: by, acknowledged_at: new Date().toISOString(),
    })
    return delay({ ok: true })
  },

  async snooze(violationId: string, days = 7) {
    transition(violationId, 'SNOOZED', 'snooze', 'dashboard-user', {
      snooze_until: new Date(Date.now() + days * DAY).toISOString(),
    }, `${days}d`)
    return delay({ ok: true })
  },

  async exempt(violationId: string, reason: string) {
    transition(violationId, 'EXEMPTED', 'exempt', 'dashboard-user', { exempt_reason: reason }, reason)
    return delay({ ok: true })
  },

  async reopen(violationId: string, by = 'dashboard-user') {
    const v = find(violationId)
    if (!['ACKNOWLEDGED', 'SNOOZED', 'EXEMPTED'].includes(v.status)) {
      await delay(null)
      throw new ApiError('violation cannot be reopened', 409)
    }
    transition(violationId, 'OPEN', 'reopen', by, {
      acknowledged_by: null, acknowledged_at: null, snooze_until: null, exempt_reason: null,
    })
    return delay({ ok: true })
  },

  getSummary(): Promise<Summary> {
    const s: Summary = { total: 0, by_status: {}, by_severity: {}, by_team: {}, by_severity_status: {} }
    for (const v of violations) {
      s.total++
      s.by_status[v.status]     = (s.by_status[v.status] ?? 0) + 1
      s.by_severity[v.severity] = (s.by_severity[v.severity] ?? 0) + 1
      const team = (s.by_team[v.team] ??= { OPEN: 0, ACKNOWLEDGED: 0, RESOLVED: 0 })
      team[v.status] = (team[v.status] ?? 0) + 1
      const row = (s.by_severity_status![v.severity] ??= {})
      row[v.status] = (row[v.status] ?? 0) + 1
    }
    return delay(s)
  },

  getTrend(days = 14) {
    return delay({ days: buildTrend(Math.min(90, Math.max(1, days))) })
  },

  triggerAudit(): Promise<AuditTriggerResult> {
    auditRuns++
    // Simulate the async auditor: a few seconds later it re-sees everything,
    // and the first run also catches a brand-new misconfiguration.
    setTimeout(() => {
      const now = new Date().toISOString()
      violations = violations.map((v) => ACTIVE_STATUSES.includes(v.status)
        ? { ...v, last_seen: now, occurrence_count: v.occurrence_count + 1 } : v)
      if (auditRuns === 1) {
        const id = `sg-0${hex(16)}`
        const v: Violation = {
          pk: `EC2_001#${id}`, violation_id: `v-ec2_001-${hex(10)}`, rule_id: 'EC2_001',
          rule_name: RULES.EC2_001.name, severity: 'CRITICAL', resource_type: 'AWS::EC2::SecurityGroup',
          resource_id: id, reason: "Security group 'hotfix-debug-sg' allows port 22 from 0.0.0.0/0",
          status: 'OPEN', first_detected: now, last_seen: now, occurrence_count: 1,
          resolved_at: null, acknowledged_by: null, acknowledged_at: null, snooze_until: null,
          exempt_reason: null, team: 'infra', owner: OWNER.infra, region: REGION, account_id: ACCOUNT,
        }
        violations = [v, ...violations]
        history[v.violation_id] = [{ violation_id: v.violation_id, timestamp: now, action: 'detect',
          actor: 'auditor', from_status: '', to_status: 'OPEN', context: '' }]
      }
    }, 3500)
    return delay({ triggered: true, message: 'Audit queued' })
  },
}

