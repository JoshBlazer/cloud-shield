/**
 * Lightweight PKCE auth flow for Cognito.
 * Tokens are stored in module scope (memory only — no localStorage, no XSS risk).
 * Auth is a no-op when VITE_COGNITO_DOMAIN is not set (local dev / mock mode).
 *
 * Access tokens are refreshed shortly before they expire using the refresh token,
 * so a long-open dashboard keeps working instead of failing after an hour.
 */

const COGNITO_DOMAIN = import.meta.env.VITE_COGNITO_DOMAIN ?? ''
const CLIENT_ID      = import.meta.env.VITE_COGNITO_CLIENT_ID ?? ''
const APP_URL        = import.meta.env.VITE_APP_URL ?? window.location.origin
const REDIRECT_URI   = `${APP_URL}/callback`
const REFRESH_MARGIN = 2 * 60_000  // refresh this long before expiry

export const AUTH_ENABLED = Boolean(COGNITO_DOMAIN && CLIENT_ID)

// In-memory token store
let _accessToken  = ''
let _refreshToken = ''
let _expiresAt    = 0
let _refreshing: Promise<boolean> | null = null

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

function storeTokens(data: { access_token?: string; refresh_token?: string; expires_in?: number }): boolean {
  _accessToken  = data.access_token  ?? ''
  if (data.refresh_token) _refreshToken = data.refresh_token
  _expiresAt    = Date.now() + (data.expires_in ?? 3600) * 1000
  return Boolean(_accessToken)
}

async function tokenRequest(body: URLSearchParams): Promise<boolean> {
  const resp = await fetch(`https://${COGNITO_DOMAIN}/oauth2/token`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    body.toString(),
  })
  if (!resp.ok) return false
  return storeTokens(await resp.json())
}

export async function login(): Promise<void> {
  const verifier  = randomString(64)
  const challenge = await sha256b64url(verifier)
  sessionStorage.setItem('pkce_verifier', verifier)
  // Remember where the user was so we can send them back after sign-in.
  sessionStorage.setItem('post_login_path', window.location.pathname + window.location.search)

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

  return tokenRequest(new URLSearchParams({
    grant_type:    'authorization_code',
    client_id:     CLIENT_ID,
    redirect_uri:  REDIRECT_URI,
    code,
    code_verifier: verifier,
  }))
}

/** Path to return to after a successful sign-in (defaults to the app root). */
export function consumePostLoginPath(): string {
  const path = sessionStorage.getItem('post_login_path')
  sessionStorage.removeItem('post_login_path')
  return path && path.startsWith('/') && !path.startsWith('/callback') ? path : '/'
}

async function refresh(): Promise<boolean> {
  if (!_refreshToken) return false
  _refreshing ??= tokenRequest(new URLSearchParams({
    grant_type:    'refresh_token',
    client_id:     CLIENT_ID,
    refresh_token: _refreshToken,
  })).catch(() => false).finally(() => { _refreshing = null })
  return _refreshing
}

/** A usable access token, refreshing it first if it is about to expire. */
export async function getValidAccessToken(): Promise<string> {
  if (!AUTH_ENABLED) return ''
  if (_accessToken && Date.now() < _expiresAt - REFRESH_MARGIN) return _accessToken
  if (await refresh()) return _accessToken
  return _accessToken && Date.now() < _expiresAt ? _accessToken : ''
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
