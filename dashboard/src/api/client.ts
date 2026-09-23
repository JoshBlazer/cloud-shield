import { AUTH_ENABLED, getValidAccessToken, login } from '../hooks/useAuth'
import type {
  AuditEvent, AuditTriggerResult, Summary, TrendPoint, ViolationPage, ViolationQuery,
} from '../types'
import { ApiError } from './errors'
import { mockApi } from './mock'

export { ApiError, errorMessage } from './errors'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const BASE            = USE_MOCK ? '' : (import.meta.env.VITE_API_URL ?? '/api')
const TIMEOUT_MS      = 15_000

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getValidAccessToken()
  const ctrl  = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      signal: ctrl.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    })
  } catch (e) {
    throw new ApiError(
      ctrl.signal.aborted ? 'The request timed out' : 'Network error — check your connection',
      0,
    )
  } finally {
    clearTimeout(timer)
  }

  if (res.status === 401 && AUTH_ENABLED) {
    // Session is gone (expired refresh token, revoked, …): send the user to sign in.
    void login()
    throw new ApiError('Your session expired — signing you in again', 401)
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json() as { error?: string }
      if (body?.error) msg = body.error
    } catch { /* non-JSON error body */ }
    throw new ApiError(msg, res.status)
  }
  return res.json() as Promise<T>
}

function patch(violationId: string, body: Record<string, unknown>) {
  return req<{ ok: boolean }>(`/violations/${encodeURIComponent(violationId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

const httpApi = {
  listViolations(params: ViolationQuery = {}) {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== null && v !== '')
          .map(([k, v]) => [k, String(v)])
      ) as Record<string, string>
    ).toString()
    return req<ViolationPage>(`/violations${qs ? `?${qs}` : ''}`)
  },

  getViolationHistory(violationId: string) {
    return req<{ violation_id: string; events: AuditEvent[] }>(
      `/violations/${encodeURIComponent(violationId)}/history`,
    )
  },

  acknowledge(violationId: string, by = 'dashboard-user') {
    return patch(violationId, { action: 'acknowledge', by })
  },

  snooze(violationId: string, days = 7) {
    return patch(violationId, { action: 'snooze', days })
  },

  exempt(violationId: string, reason: string) {
    return patch(violationId, { action: 'exempt', reason })
  },

  reopen(violationId: string, by = 'dashboard-user') {
    return patch(violationId, { action: 'reopen', by })
  },

  getSummary() {
    return req<Summary>('/summary')
  },

  getTrend(days = 14) {
    return req<{ days: TrendPoint[] }>(`/trend?days=${days}`)
  },

  triggerAudit() {
    return req<AuditTriggerResult>('/audit/trigger', { method: 'POST' })
  },
}

// Every view goes through `api`: the in-memory mock by default, the real
// API Gateway when the build sets VITE_USE_MOCK=false.
export const api: typeof httpApi = USE_MOCK ? mockApi : httpApi
