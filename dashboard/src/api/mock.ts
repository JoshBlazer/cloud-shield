/**
 * Mock API — mirrors the real API shape so the dashboard can be
 * demoed locally without a deployed AWS backend.
 * Swap VITE_USE_MOCK=false to hit the real API Gateway.
 */
import type { AuditTriggerResult, Summary, Violation } from '../types'

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
]

// total = 4+1+1+6+2 = 14; RESOLVED (6) < total (14) → score = 43%
export const MOCK_SUMMARY: Summary = {
  total: 14,
  by_status:   { OPEN: 4, ACKNOWLEDGED: 1, SNOOZED: 1, RESOLVED: 6, EXEMPTED: 2 },
  by_severity: { CRITICAL: 4, HIGH: 2, MEDIUM: 1, LOW: 0 },
  by_team: {
    'data-platform': { OPEN: 2, ACKNOWLEDGED: 0, SNOOZED: 0, RESOLVED: 3 },
    'backend':       { OPEN: 1, ACKNOWLEDGED: 1, SNOOZED: 0, RESOLVED: 2 },
    'infra':         { OPEN: 2, ACKNOWLEDGED: 0, SNOOZED: 0, RESOLVED: 2 },
    'platform':      { OPEN: 0, ACKNOWLEDGED: 0, SNOOZED: 1, RESOLVED: 0 },
  },
}

export const MOCK_TREND = Array.from({ length: 7 }, (_, i) => ({
  day: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
  CRITICAL: [6, 7, 5, 8, 6, 4, 4][i],
  HIGH:     [3, 2, 3, 2, 2, 2, 2][i],
  MEDIUM:   [2, 1, 2, 1, 1, 1, 1][i],
}))

function delay<T>(val: T, ms = 300): Promise<T> {
  return new Promise((res) => setTimeout(() => res(val), ms))
}

let violations = [...MOCK_VIOLATIONS]

export const mockApi = {
  listViolations(params: { status?: string; severity?: string; team?: string } = {}) {
    let items = violations.filter((v) => v.status !== 'RESOLVED' && v.status !== 'EXEMPTED')
    if (params.status)   items = items.filter((v) => v.status === params.status)
    if (params.severity) items = items.filter((v) => v.severity === params.severity)
    if (params.team)     items = items.filter((v) => v.team === params.team)
    return delay({ violations: items, count: items.length })
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
    return delay({ resources_audited: 10, violations_found: violations.filter((v) => v.status === 'OPEN').length })
  },
}
