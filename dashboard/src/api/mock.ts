/**
 * Mock API — mirrors the real API shape so the dashboard runs without AWS.
 * Set VITE_USE_MOCK=false to hit the real API Gateway.
 */
import type { AuditEvent, AuditTriggerResult, Summary, Violation, ViolationPage, ViolationQuery } from '../types'

const NOW      = new Date().toISOString()
const HOUR_AGO = new Date(Date.now() - 3_600_000).toISOString()
const DAY_AGO  = new Date(Date.now() - 86_400_000).toISOString()

export const MOCK_VIOLATIONS: Violation[] = [
  {
    pk: 'S3_001#acme-raw-data-prod', violation_id: 'v-s3-001-raw',
    rule_id: 'S3_001', rule_name: 'No Public S3 Buckets',
    severity: 'CRITICAL', resource_type: 'AWS::S3::Bucket',
    resource_id: 'acme-raw-data-prod',
    reason: 'Public access block is not fully enabled',
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 24, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'data-platform', owner: 'data@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'S3_002#acme-raw-data-prod', violation_id: 'v-s3-002-raw',
    rule_id: 'S3_002', rule_name: 'S3 Server-Side Encryption Required',
    severity: 'HIGH', resource_type: 'AWS::S3::Bucket',
    resource_id: 'acme-raw-data-prod',
    reason: 'Default server-side encryption is not configured',
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 24, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'data-platform', owner: 'data@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'S3_001#acme-uploads-prod', violation_id: 'v-s3-001-up',
    rule_id: 'S3_001', rule_name: 'No Public S3 Buckets',
    severity: 'CRITICAL', resource_type: 'AWS::S3::Bucket',
    resource_id: 'acme-uploads-prod',
    reason: 'Public access block is not fully enabled',
    status: 'ACKNOWLEDGED', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 12, resolved_at: null, acknowledged_by: 'alice@acme.com',
    acknowledged_at: HOUR_AGO, snooze_until: null,
    team: 'backend', owner: 'backend@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'IAM_001#alice', violation_id: 'v-iam-001-alice',
    rule_id: 'IAM_001', rule_name: 'MFA Required for Console Users',
    severity: 'CRITICAL', resource_type: 'AWS::IAM::User',
    resource_id: 'alice',
    reason: "User 'alice' has console access but no MFA device",
    status: 'OPEN', first_detected: DAY_AGO, last_seen: NOW,
    occurrence_count: 3, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'backend', owner: 'alice@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'IAM_003#account-password-policy', violation_id: 'v-iam-003',
    rule_id: 'IAM_003', rule_name: 'Weak Account Password Policy',
    severity: 'HIGH', resource_type: 'AWS::IAM::PasswordPolicy',
    resource_id: 'account-password-policy',
    reason: 'No account password policy is configured',
    status: 'SNOOZED', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 2, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    team: 'platform', owner: 'platform@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'EC2_001#sg-web-tier', violation_id: 'v-ec2-001-web',
    rule_id: 'EC2_001', rule_name: 'No Unrestricted SSH Access',
    severity: 'CRITICAL', resource_type: 'AWS::EC2::SecurityGroup',
    resource_id: 'sg-16a5fffc931c0bac5',
    reason: "Security group 'web-tier-sg' allows port 22 from 0.0.0.0/0",
    status: 'OPEN', first_detected: HOUR_AGO, last_seen: NOW,
    occurrence_count: 1, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'infra', owner: 'infra@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'EC2_003#sg-dev-sandbox', violation_id: 'v-ec2-003-dev',
    rule_id: 'EC2_003', rule_name: 'No Unrestricted All Traffic',
    severity: 'CRITICAL', resource_type: 'AWS::EC2::SecurityGroup',
    resource_id: 'sg-bcd60875db0e5cb3d',
    reason: "Security group 'dev-sandbox-sg' allows all traffic from 0.0.0.0/0",
    status: 'OPEN', first_detected: HOUR_AGO, last_seen: NOW,
    occurrence_count: 1, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'infra', owner: 'infra@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'RDS_001#orders-db-prod', violation_id: 'v-rds-001-orders',
    rule_id: 'RDS_001', rule_name: 'RDS instance publicly accessible',
    severity: 'CRITICAL', resource_type: 'AWS::RDS::DBInstance',
    resource_id: 'orders-db-prod',
    reason: "DB instance 'orders-db-prod' has PubliclyAccessible=true and a public endpoint",
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 6, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'data-platform', owner: 'data@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'EBS_003#snap-0a1b2c3d4e5f67890', violation_id: 'v-ebs-003-snap',
    rule_id: 'EBS_003', rule_name: 'EBS snapshot is public',
    severity: 'CRITICAL', resource_type: 'AWS::EC2::Snapshot',
    resource_id: 'snap-0a1b2c3d4e5f67890',
    reason: "Snapshot 'snap-0a1b2c3d4e5f67890' grants createVolumePermission to group 'all'",
    status: 'OPEN', first_detected: HOUR_AGO, last_seen: NOW,
    occurrence_count: 1, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'infra', owner: 'infra@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'EBS_001#vol-0f9e8d7c6b5a43210', violation_id: 'v-ebs-001-vol',
    rule_id: 'EBS_001', rule_name: 'EBS volume not encrypted',
    severity: 'HIGH', resource_type: 'AWS::EC2::Volume',
    resource_id: 'vol-0f9e8d7c6b5a43210',
    reason: "Volume 'vol-0f9e8d7c6b5a43210' (attached to i-0123abcd4567ef890) is not encrypted at rest",
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 4, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'infra', owner: 'infra@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'CT_001#123456789012', violation_id: 'v-ct-001-acct',
    rule_id: 'CT_001', rule_name: 'CloudTrail not enabled',
    severity: 'CRITICAL', resource_type: 'AWS::::Account',
    resource_id: '123456789012',
    reason: 'No multi-region CloudTrail trail is logging in this account',
    status: 'OPEN', first_detected: DAY_AGO, last_seen: NOW,
    occurrence_count: 8, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'platform', owner: 'platform@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'CT_002#org-audit-trail', violation_id: 'v-ct-002-trail',
    rule_id: 'CT_002', rule_name: 'CloudTrail log file validation disabled',
    severity: 'MEDIUM', resource_type: 'AWS::CloudTrail::Trail',
    resource_id: 'org-audit-trail',
    reason: "Trail 'org-audit-trail' does not have log file integrity validation enabled",
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 3, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'platform', owner: 'platform@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
  {
    pk: 'KMS_001#1234abcd-12ab-34cd-56ef-1234567890ab', violation_id: 'v-kms-001-key',
    rule_id: 'KMS_001', rule_name: 'KMS key rotation disabled',
    severity: 'MEDIUM', resource_type: 'AWS::KMS::Key',
    resource_id: '1234abcd-12ab-34cd-56ef-1234567890ab',
    reason: 'Automatic annual rotation is disabled for this customer-managed key',
    status: 'OPEN', first_detected: DAY_AGO, last_seen: HOUR_AGO,
    occurrence_count: 2, resolved_at: null, acknowledged_by: null,
    acknowledged_at: null, snooze_until: null,
    team: 'platform', owner: 'platform@acme.com',
    region: 'us-east-1', account_id: '123456789012',
  },
]

export const MOCK_SUMMARY: Summary = {
  total: 20,
  by_status:   { OPEN: 10, ACKNOWLEDGED: 1, SNOOZED: 1, RESOLVED: 6, EXEMPTED: 2 },
  by_severity: { CRITICAL: 7, HIGH: 3, MEDIUM: 3, LOW: 0 },
  by_team: {
    'data-platform': { OPEN: 3, ACKNOWLEDGED: 0, SNOOZED: 0, RESOLVED: 3 },
    'backend':       { OPEN: 1, ACKNOWLEDGED: 1, SNOOZED: 0, RESOLVED: 2 },
    'infra':         { OPEN: 4, ACKNOWLEDGED: 0, SNOOZED: 0, RESOLVED: 2 },
    'platform':      { OPEN: 3, ACKNOWLEDGED: 0, SNOOZED: 1, RESOLVED: 0 },
  },
}

export const MOCK_TREND = Array.from({ length: 7 }, (_, i) => ({
  day:      ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
  CRITICAL: [6, 7, 5, 8, 6, 4, 4][i],
  HIGH:     [3, 2, 3, 2, 2, 2, 2][i],
  MEDIUM:   [2, 1, 2, 1, 1, 1, 1][i],
}))

const MOCK_HISTORY: Record<string, AuditEvent[]> = {
  'v-s3-001-raw': [
    { violation_id: 'v-s3-001-raw', timestamp: HOUR_AGO, action: 'detect',      actor: 'auditor',           from_status: '',     to_status: 'OPEN',   context: '' },
  ],
  'v-s3-001-up': [
    { violation_id: 'v-s3-001-up',  timestamp: HOUR_AGO, action: 'acknowledge', actor: 'alice@acme.com',    from_status: 'OPEN', to_status: 'ACKNOWLEDGED', context: '' },
    { violation_id: 'v-s3-001-up',  timestamp: DAY_AGO,  action: 'detect',      actor: 'auditor',           from_status: '',     to_status: 'OPEN',   context: '' },
  ],
}

function delay<T>(val: T, ms = 300): Promise<T> {
  return new Promise((res) => setTimeout(() => res(val), ms))
}

let violations = [...MOCK_VIOLATIONS]

// ── Pagination helpers ────────────────────────────────────────────────────────
const DEFAULT_LIMIT = 200
const MAX_LIMIT     = 500
const SEV_RANK: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }

type CursorKey = [number, string]  // [severity rank, pk]

function sortKey(v: Violation): CursorKey {
  return [SEV_RANK[v.severity] ?? 9, v.pk]
}

function compareKeys(a: CursorKey, b: CursorKey): number {
  if (a[0] !== b[0]) return a[0] - b[0]
  return a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0
}

function filterFingerprint(p: ViolationQuery): string {
  return [p.status ?? '', p.severity ?? '', p.team ?? ''].join('|')
}

function encodeCursor(c: { k: CursorKey; f: string }): string {
  const bytes = new TextEncoder().encode(JSON.stringify(c))
  return btoa(String.fromCharCode(...bytes))
}

function decodeCursor(token: string): { k: CursorKey; f: string } | null {
  try {
    const bytes = Uint8Array.from(atob(token), (ch) => ch.charCodeAt(0))
    const c = JSON.parse(new TextDecoder().decode(bytes))
    if (Array.isArray(c?.k) && typeof c.k[0] === 'number' && typeof c.k[1] === 'string' && typeof c.f === 'string') {
      return c
    }
  } catch { /* malformed token */ }
  return null
}

export const mockApi = {
  /**
   * Cursor-paginated list with the same contract as GET /violations:
   * `{ violations, count, next_cursor }`. Results are ordered by severity then pk. The
   * cursor is an opaque base64 token holding the last returned sort key plus a fingerprint
   * of the filters it was issued for. Keyset (rather than offset) cursors mean an item
   * changing status between page fetches doesn't cause later items to be skipped.
   */
  listViolations(params: ViolationQuery = {}): Promise<ViolationPage> {
    const limit = Math.min(MAX_LIMIT, Math.max(1, Math.floor(params.limit ?? DEFAULT_LIMIT)))
    const fp    = filterFingerprint(params)

    let after: CursorKey | null = null
    if (params.cursor) {
      const decoded = decodeCursor(params.cursor)
      if (!decoded || decoded.f !== fp) {
        return Promise.reject(new Error('400 Invalid cursor for these filters'))
      }
      after = decoded.k
    }

    let items = violations.filter((v) => v.status !== 'RESOLVED' && v.status !== 'EXEMPTED')
    if (params.status)   items = items.filter((v) => v.status === params.status)
    if (params.severity) items = items.filter((v) => v.severity === params.severity)
    if (params.team)     items = items.filter((v) => v.team === params.team)
    items.sort((a, b) => compareKeys(sortKey(a), sortKey(b)))
    if (after) {
      const start = after
      items = items.filter((v) => compareKeys(sortKey(v), start) > 0)
    }

    const page = items.slice(0, limit)
    const next = items.length > limit
      ? encodeCursor({ k: sortKey(page[page.length - 1]), f: fp })
      : null
    return delay({ violations: page, count: page.length, next_cursor: next })
  },

  getViolationHistory(violationId: string) {
    const events = MOCK_HISTORY[violationId] ?? []
    return delay({ violation_id: violationId, events })
  },

  acknowledge(violationId: string, by = 'dashboard-user') {
    violations = violations.map((v) =>
      v.violation_id === violationId
        ? { ...v, status: 'ACKNOWLEDGED' as const, acknowledged_by: by, acknowledged_at: new Date().toISOString() }
        : v
    )
    return delay({ ok: true })
  },

  snooze(violationId: string, days = 7) {
    const until = new Date(Date.now() + days * 86_400_000).toISOString()
    violations = violations.map((v) =>
      v.violation_id === violationId ? { ...v, status: 'SNOOZED' as const, snooze_until: until } : v
    )
    return delay({ ok: true })
  },

  exempt(violationId: string, _reason: string) {
    violations = violations.map((v) =>
      v.violation_id === violationId ? { ...v, status: 'EXEMPTED' as const } : v
    )
    return delay({ ok: true })
  },

  getSummary() {
    return delay(MOCK_SUMMARY)
  },

  triggerAudit(): Promise<AuditTriggerResult> {
    return delay({ triggered: true, message: 'Audit queued' })
  },
}
