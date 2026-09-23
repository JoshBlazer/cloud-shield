/**
 * Everything the UI knows about rules, services and AWS resources, in one place:
 * display names, remediation steps, short resource tags and console deep links.
 * Mirrors policies.yaml on the backend.
 */
import type { Severity, Violation } from '../types'

export interface RuleInfo {
  name:        string
  severity:    Severity
  service:     ServiceKey
  remediation: string
}

export type ServiceKey = 'S3' | 'IAM' | 'EC2' | 'CT' | 'RDS' | 'KMS' | 'EBS'

export const SERVICES: Record<ServiceKey, { label: string; home: (region: string) => string }> = {
  S3:  { label: 'S3',         home: () => 'https://s3.console.aws.amazon.com/s3/home' },
  IAM: { label: 'IAM',        home: () => 'https://us-east-1.console.aws.amazon.com/iamv2/home' },
  EC2: { label: 'EC2',        home: (r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}` },
  CT:  { label: 'CloudTrail', home: (r) => `https://${r}.console.aws.amazon.com/cloudtrailv2/home?region=${r}#/trails` },
  RDS: { label: 'RDS',        home: (r) => `https://${r}.console.aws.amazon.com/rds/home?region=${r}#databases:` },
  KMS: { label: 'KMS',        home: (r) => `https://${r}.console.aws.amazon.com/kms/home?region=${r}#/kms/keys` },
  EBS: { label: 'EBS',        home: (r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#Volumes:` },
}

export const RULES: Record<string, RuleInfo> = {
  S3_001:  { name: 'No Public S3 Buckets', severity: 'CRITICAL', service: 'S3',
    remediation: 'S3 → bucket → Permissions → Block public access → enable all four settings.' },
  S3_002:  { name: 'S3 Server-Side Encryption Required', severity: 'HIGH', service: 'S3',
    remediation: 'S3 → bucket → Properties → Default encryption → enable SSE-S3 or SSE-KMS.' },
  S3_003:  { name: 'S3 Versioning Required', severity: 'MEDIUM', service: 'S3',
    remediation: 'S3 → bucket → Properties → Bucket Versioning → Enable.' },
  S3_004:  { name: 'Bucket Policy Grants Public Access', severity: 'CRITICAL', service: 'S3',
    remediation: 'S3 → bucket → Permissions → Bucket policy → remove statements that allow Principal "*", or scope them with a condition.' },
  IAM_001: { name: 'MFA Required for Console Users', severity: 'CRITICAL', service: 'IAM',
    remediation: 'IAM → Users → user → Security credentials → Assign MFA device.' },
  IAM_002: { name: 'Access Key Rotation Required', severity: 'HIGH', service: 'IAM',
    remediation: 'Create a new access key, move clients to it, then deactivate and delete the old key.' },
  IAM_003: { name: 'Weak Account Password Policy', severity: 'HIGH', service: 'IAM',
    remediation: 'IAM → Account settings → Password policy → 14+ characters, all character classes, 90-day rotation, reuse prevention of 5.' },
  IAM_004: { name: 'Root Account MFA Not Enabled', severity: 'CRITICAL', service: 'IAM',
    remediation: 'Sign in as root → Security credentials → Assign MFA device (a hardware key is recommended).' },
  EC2_001: { name: 'No Unrestricted SSH Access', severity: 'CRITICAL', service: 'EC2',
    remediation: 'EC2 → Security Groups → group → Inbound rules → remove 0.0.0.0/0 on port 22; use SSM Session Manager or a known CIDR.' },
  EC2_002: { name: 'No Unrestricted RDP Access', severity: 'CRITICAL', service: 'EC2',
    remediation: 'EC2 → Security Groups → group → Inbound rules → remove 0.0.0.0/0 on port 3389.' },
  EC2_003: { name: 'No Unrestricted All Traffic', severity: 'CRITICAL', service: 'EC2',
    remediation: 'EC2 → Security Groups → group → Inbound rules → delete the all-traffic rule from 0.0.0.0/0.' },
  EC2_004: { name: 'No Unrestricted HTTP Access', severity: 'MEDIUM', service: 'EC2',
    remediation: 'Restrict port 80 to your load balancer\'s security group instead of 0.0.0.0/0.' },
  CT_001:  { name: 'CloudTrail Not Enabled', severity: 'CRITICAL', service: 'CT',
    remediation: 'CloudTrail → Trails → Create trail → apply to all regions, deliver to a dedicated S3 bucket.' },
  CT_002:  { name: 'CloudTrail Log File Validation Disabled', severity: 'HIGH', service: 'CT',
    remediation: 'CloudTrail → Trails → trail → Edit → enable Log file validation.' },
  CT_003:  { name: 'CloudTrail Logs Not KMS Encrypted', severity: 'MEDIUM', service: 'CT',
    remediation: 'CloudTrail → Trails → trail → Edit → Log file SSE-KMS encryption → choose a customer-managed key.' },
  RDS_001: { name: 'RDS Instance Publicly Accessible', severity: 'CRITICAL', service: 'RDS',
    remediation: 'RDS → Databases → instance → Modify → Connectivity → Public access: No.' },
  RDS_002: { name: 'RDS Storage Encryption Required', severity: 'HIGH', service: 'RDS',
    remediation: 'Encryption can\'t be enabled in place: snapshot → copy with encryption → restore, then cut over.' },
  RDS_003: { name: 'RDS Backup Retention Too Short', severity: 'MEDIUM', service: 'RDS',
    remediation: 'RDS → Databases → instance → Modify → Backup retention period → 7 days or more.' },
  KMS_001: { name: 'KMS Key Rotation Disabled', severity: 'MEDIUM', service: 'KMS',
    remediation: 'KMS → Customer managed keys → key → Key rotation → enable automatic rotation.' },
  EBS_001: { name: 'EBS Volume Not Encrypted', severity: 'HIGH', service: 'EBS',
    remediation: 'Snapshot the volume, copy the snapshot with encryption on, create a new volume from it and swap it in.' },
  EBS_002: { name: 'EBS Encryption By Default Disabled', severity: 'MEDIUM', service: 'EBS',
    remediation: 'EC2 → Settings (Data protection) → EBS encryption → Always encrypt new EBS volumes.' },
  EBS_003: { name: 'EBS Snapshot Is Public', severity: 'CRITICAL', service: 'EBS',
    remediation: 'EC2 → Snapshots → snapshot → Actions → Modify permissions → Private.' },
}

export function ruleService(ruleId: string): ServiceKey | undefined {
  return RULES[ruleId]?.service ?? (ruleId.split('_')[0] as ServiceKey)
}

const RESOURCE_TAG: Record<string, string> = {
  'AWS::S3::Bucket':          'S3',
  'AWS::EC2::SecurityGroup':  'SG',
  'AWS::IAM::User':           'IAM',
  'AWS::IAM::AccessKey':      'KEY',
  'AWS::IAM::PasswordPolicy': 'PWD',
  'AWS::IAM::RootAccount':    'ROOT',
  'AWS::CloudTrail::Trail':   'CT',
  'AWS::RDS::DBInstance':     'RDS',
  'AWS::KMS::Key':            'KMS',
  'AWS::EC2::Volume':         'EBS',
  'AWS::EC2::Snapshot':       'SNAP',
  'AWS::::Account':           'ACCT',
}

/** Last path segment of an ARN (e.g. key/1234 → 1234), or the id unchanged. */
export function shortId(id: string): string {
  return id.startsWith('arn:') ? id.split(/[:/]/).pop() ?? id : id
}

const CONSOLE_LINK: Record<string, (id: string, region: string) => string> = {
  'AWS::S3::Bucket':         (id) => `https://s3.console.aws.amazon.com/s3/buckets/${id}`,
  'AWS::EC2::SecurityGroup': (id, r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#SecurityGroup:groupId=${id}`,
  'AWS::IAM::User':          (id) => `https://us-east-1.console.aws.amazon.com/iam/home#/users/details/${id}`,
  'AWS::IAM::PasswordPolicy':() => 'https://us-east-1.console.aws.amazon.com/iam/home#/account_settings',
  'AWS::IAM::RootAccount':   () => 'https://us-east-1.console.aws.amazon.com/iam/home#/security_credentials',
  'AWS::IAM::AccessKey':     (id) => `https://us-east-1.console.aws.amazon.com/iam/home#/users/details/${id.split('/')[0]}`,
  'AWS::CloudTrail::Trail':  (id, r) => `https://${r}.console.aws.amazon.com/cloudtrailv2/home?region=${r}#/trails/${encodeURIComponent(id)}`,
  'AWS::RDS::DBInstance':    (id, r) => `https://${r}.console.aws.amazon.com/rds/home?region=${r}#database:id=${shortId(id)};is-cluster=false`,
  'AWS::KMS::Key':           (id, r) => `https://${r}.console.aws.amazon.com/kms/home?region=${r}#/kms/keys/${shortId(id)}`,
  'AWS::EC2::Volume':        (id, r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#VolumeDetails:volumeId=${shortId(id)}`,
  'AWS::EC2::Snapshot':      (id, r) => `https://${r}.console.aws.amazon.com/ec2/home?region=${r}#SnapshotDetails:snapshotId=${shortId(id)}`,
}

export function resourceTag(v: Pick<Violation, 'resource_type' | 'rule_id'>): string {
  return RESOURCE_TAG[v.resource_type]
    ?? ruleService(v.rule_id)
    ?? (v.resource_type.split('::')[1] || 'AWS').slice(0, 4).toUpperCase()
}

export function consoleUrl(v: Pick<Violation, 'resource_type' | 'resource_id' | 'rule_id' | 'region'>): string {
  const direct = CONSOLE_LINK[v.resource_type]
  if (direct) return direct(v.resource_id, v.region)
  const svc = ruleService(v.rule_id)
  if (svc && SERVICES[svc]) return SERVICES[svc].home(v.region)
  return `https://${v.region}.console.aws.amazon.com/console/home?region=${v.region}`
}

export function remediation(ruleId: string): string | undefined {
  return RULES[ruleId]?.remediation
}

// ── Visual tokens per severity / status ─────────────────────────────────────

export const SEV_STYLE: Record<Severity, { color: string; rgb: string; label: string }> = {
  CRITICAL: { color: '#f87171', rgb: '248,113,113', label: 'Critical' },
  HIGH:     { color: '#fb923c', rgb: '251,146,60',  label: 'High' },
  MEDIUM:   { color: '#fbbf24', rgb: '251,191,36',  label: 'Medium' },
  LOW:      { color: '#4ade80', rgb: '74,222,128',  label: 'Low' },
}

export const STATUS_STYLE: Record<string, { color: string; rgb: string; label: string }> = {
  OPEN:         { color: '#f87171', rgb: '248,113,113', label: 'Open' },
  ACKNOWLEDGED: { color: '#60a5fa', rgb: '96,165,250',  label: 'Acknowledged' },
  SNOOZED:      { color: '#fb923c', rgb: '251,146,60',  label: 'Snoozed' },
  RESOLVED:     { color: '#4ade80', rgb: '74,222,128',  label: 'Resolved' },
  EXEMPTED:     { color: '#9aa3b5', rgb: '154,163,181', label: 'Exempted' },
}
