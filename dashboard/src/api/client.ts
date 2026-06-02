import type { AuditTriggerResult, Summary, Violation } from '../types'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const BASE     = USE_MOCK ? '' : (import.meta.env.VITE_API_URL ?? '/api')

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  listViolations(params: { status?: string; severity?: string; team?: string } = {}) {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v)) as Record<string, string>
    ).toString()
    return req<{ violations: Violation[]; count: number }>(`/violations${qs ? `?${qs}` : ''}`)
  },

  acknowledge(violationId: string, by = 'dashboard-user') {
    return req<{ ok: boolean }>(`/violations/${violationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'acknowledge', by }),
    })
  },

  snooze(violationId: string, days = 7) {
    return req<{ ok: boolean }>(`/violations/${violationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'snooze', days }),
    })
  },

  exempt(violationId: string, reason: string) {
    return req<{ ok: boolean }>(`/violations/${violationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'exempt', reason }),
    })
  },

  getSummary() {
    return req<Summary>('/summary')
  },

  triggerAudit() {
    return req<AuditTriggerResult>('/audit/trigger', { method: 'POST' })
  },
}
