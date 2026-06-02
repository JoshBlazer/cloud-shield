import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { handleCallback, isAuthenticated, login } from '../hooks/useAuth'

export function Callback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()

  useEffect(() => {
    const code = params.get('code')
    if (!code) { navigate('/'); return }
    handleCallback(code).then((ok) => navigate(ok ? '/' : '/login'))
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex items-center justify-center h-screen bg-bg">
      <div className="flex items-center gap-2 text-muted text-sm">
        <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"/>
        </svg>
        Signing in…
      </div>
    </div>
  )
}

export function Login() {
  const navigate = useNavigate()
  useEffect(() => { if (isAuthenticated()) navigate('/') }, [navigate])

  return (
    <div className="flex items-center justify-center h-screen bg-bg bg-grid">
      <div
        className="flex flex-col items-center gap-8 px-10 py-10 rounded-2xl"
        style={{
          background: 'rgba(15,23,36,0.85)',
          border: '1px solid rgba(255,255,255,0.07)',
          boxShadow: '0 8px 48px rgba(0,0,0,0.6)',
          backdropFilter: 'blur(12px)',
        }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg,rgba(248,113,113,0.2) 0%,rgba(251,146,60,0.12) 100%)',
              border: '1px solid rgba(248,113,113,0.35)',
              boxShadow: '0 0 18px rgba(248,113,113,0.15)',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 1.5L2 4v4.5c0 3.3 2.3 5.7 6 6.8 3.7-1.1 6-3.5 6-6.8V4L8 1.5z"/>
            </svg>
          </div>
          <div>
            <div className="text-lg font-bold">Cloud<span style={{ color: '#f87171' }}>Shield</span></div>
            <div className="text-[10px] tracking-[0.2em] uppercase font-semibold" style={{ color: 'rgba(96,165,250,0.5)' }}>
              Auditor
            </div>
          </div>
        </div>

        <div className="text-center">
          <h1 className="text-xl font-semibold text-text">Sign in to continue</h1>
          <p className="text-sm text-muted mt-1.5">Infrastructure drift and compliance dashboard</p>
        </div>

        <button
          onClick={login}
          className="w-full py-2.5 px-6 rounded-lg text-sm font-semibold transition-all duration-200"
          style={{
            background: 'linear-gradient(135deg, rgba(96,165,250,0.18) 0%, rgba(96,165,250,0.08) 100%)',
            color: '#60a5fa',
            border: '1px solid rgba(96,165,250,0.3)',
            boxShadow: '0 0 16px rgba(96,165,250,0.1)',
          }}
        >
          Sign in with Cognito
        </button>

        <p className="text-[11px] text-center" style={{ color: '#4b5568' }}>
          You'll be redirected to your organization's sign-in page
        </p>
      </div>
    </div>
  )
}
