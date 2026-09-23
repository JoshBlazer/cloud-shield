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

export interface ViolationQuery {
  status?:   string
  severity?: string
  team?:     string
  /** Page size, 1–500. Server default is 200. */
  limit?:    number
  /** Opaque cursor from a previous page's `next_cursor`. Only valid with the same filters. */
  cursor?:   string
}

export interface ViolationPage {
  violations:  Violation[]
  /** Number of items in this page. */
  count:       number
  /** Pass back as `cursor` to fetch the next page; null when there are no more results. */
  next_cursor: string | null
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
