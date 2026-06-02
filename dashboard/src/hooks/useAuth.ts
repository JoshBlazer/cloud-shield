/**
 * Lightweight PKCE auth flow for Cognito.
 * Tokens are stored in module scope (memory only — no localStorage, no XSS risk).
 * Auth is a no-op when VITE_COGNITO_DOMAIN is not set (local dev / mock mode).
 */

const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN ?? ''
const CLIENT_ID      = import.meta.env.VITE_COGNITO_CLIENT_ID ?? ''
const APP_URL        = import.meta.env.VITE_APP_URL ?? window.location.origin
const REDIRECT_URI   = `${APP_URL}/callback`

export const AUTH_ENABLED = Boolean(COGNITO_DOMAIN && CLIENT_ID)

// In-memory token store
let _accessToken  = ''
let _refreshToken = ''
let _expiresAt    = 0

function randomString(n: number): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
  const buf   = new Uint8Array(n)
  crypto.getRandomValues(buf)
  return Array.from(buf, b => chars[b % chars.length]).join('')
}

async function sha256b64url(plain: string): Promise<string> {
  const data   = new TextEncoder().encode(plain)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

export async function login(): Promise<void> {
  const verifier  = randomString(64)
  const challenge = await sha256b64url(verifier)
  sessionStorage.setItem('pkce_verifier', verifier)

  const params = new URLSearchParams({
    response_type:         'code',
    client_id:             CLIENT_ID,
    redirect_uri:          REDIRECT_URI,
    scope:                 'openid email profile',
    code_challenge:        challenge,
    code_challenge_method: 'S256',
  })
  window.location.href = `https://${COGNITO_DOMAIN}/oauth2/authorize?${params}`
}

export async function handleCallback(code: string): Promise<boolean> {
  const verifier = sessionStorage.getItem('pkce_verifier')
  if (!verifier) return false
  sessionStorage.removeItem('pkce_verifier')

  const body = new URLSearchParams({
    grant_type:    'authorization_code',
    client_id:     CLIENT_ID,
    redirect_uri:  REDIRECT_URI,
    code,
    code_verifier: verifier,
  })

  const resp = await fetch(`https://${COGNITO_DOMAIN}/oauth2/token`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    body.toString(),
  })
  if (!resp.ok) return false

  const data  = await resp.json() as { access_token?: string; refresh_token?: string; expires_in?: number }
  _accessToken  = data.access_token  ?? ''
  _refreshToken = data.refresh_token ?? ''
  _expiresAt    = Date.now() + (data.expires_in ?? 3600) * 1000
  return Boolean(_accessToken)
}

export async function logout(): Promise<void> {
  _accessToken = ''; _refreshToken = ''; _expiresAt = 0
  const params = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: APP_URL })
  window.location.href = `https://${COGNITO_DOMAIN}/logout?${params}`
}

export function getAccessToken(): string {
  return _accessToken
}

export function isAuthenticated(): boolean {
  if (!AUTH_ENABLED) return true
  return Boolean(_accessToken) && Date.now() < _expiresAt
}
