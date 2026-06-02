export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type Status   = 'OPEN' | 'ACKNOWLEDGED' | 'SNOOZED' | 'RESOLVED' | 'EXEMPTED'

export interface Violation {
  pk:               string
  violation_id:     string
  rule_id:          string
  rule_name:        string
  severity:         Severity
  resource_type:    string
  resource_id:      string
  reason:           string
  status:           Status
  first_detected:   string
  last_seen:        string
  occurrence_count: number
  resolved_at:      string | null
  acknowledged_by:  string | null
  acknowledged_at:  string | null
  snooze_until:     string | null
  team:             string
  owner:            string | null
  region:           string
  account_id:       string
}

export interface AuditEvent {
  violation_id: string
  timestamp:    string
  action:       string
  actor:        string
  from_status:  string
  to_status:    string
  context:      string
}

export interface Summary {
  total:       number
  by_status:   Record<string, number>
  by_severity: Record<string, number>
  by_team:     Record<string, Record<string, number>>
}

export interface AuditTriggerResult {
  triggered: boolean
  message:   string
}
