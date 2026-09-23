import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Spinner } from '../components/Icon'
import { Logo } from '../components/Sidebar'
import { consumePostLoginPath, handleCallback, isAuthenticated, login } from '../hooks/useAuth'

export function Callback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const code = params.get('code')
    if (!code) { navigate('/', { replace: true }); return }
    handleCallback(code)
      .then((ok) => ok ? navigate(consumePostLoginPath(), { replace: true }) : setFailed(true))
      .catch(() => setFailed(true))
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) return <Login error="Sign-in didn't complete. Please try again." />
  return (
    <div className="flex h-[100dvh] items-center justify-center bg-bg">
      <div className="flex items-center gap-2.5 text-sm text-muted"><Spinner size={16} /> Signing in…</div>
    </div>
  )
}

export function Login({ error }: { error?: string }) {
  const navigate = useNavigate()
  const [redirecting, setRedirecting] = useState(false)
  useEffect(() => { if (isAuthenticated() && !error) navigate('/', { replace: true }) }, [navigate, error])

  return (
    <div className="flex h-[100dvh] items-center justify-center bg-bg bg-grid p-4">
      <div className="panel flex w-full max-w-sm animate-scale-in flex-col items-center gap-7 px-8 py-10 backdrop-blur-xl">
        <Logo />
        <div className="text-center">
          <h1 className="text-xl font-semibold text-text">Sign in to continue</h1>
          <p className="mt-1.5 text-sm text-muted">Cloud security posture for your AWS accounts</p>
        </div>
        {error && <p role="alert" className="w-full rounded-lg border border-critical/25 bg-critical/10 px-3 py-2 text-center text-xs text-critical">{error}</p>}
        <button
          onClick={() => { setRedirecting(true); void login() }}
          disabled={redirecting}
          className="btn btn-accent w-full py-2.5 text-sm"
        >
          {redirecting ? <><Spinner size={14} /> Redirecting…</> : 'Sign in with your organization'}
        </button>
        <p className="text-center text-[11px] text-muted">You'll be taken to your organization's sign-in page.</p>
      </div>
    </div>
  )
}
