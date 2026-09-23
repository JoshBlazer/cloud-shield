import { lazy, Suspense, useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Spinner } from './components/Icon'
import { MobileNav, Sidebar } from './components/Sidebar'
import { EmptyState } from './components/States'
import { ToastProvider } from './components/Toast'
import { AUTH_ENABLED, isAuthenticated, login } from './hooks/useAuth'
import { AppDataProvider } from './state/AppData'
import { Callback, Login } from './views/Login'
import { MyResources } from './views/MyResources'
import { Violations } from './views/Violations'

// Posture pulls in the charting library; load it only when someone opens it.
const Posture = lazy(() => import('./views/Posture'))

const TITLES: Record<string, string> = {
  '/violations':   'Findings',
  '/my-resources': 'My resources',
  '/posture':      'Posture',
}

function FullScreenMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen items-center justify-center bg-bg">
      <div className="flex items-center gap-2.5 text-sm text-muted"><Spinner size={16} />{children}</div>
    </div>
  )
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(AUTH_ENABLED && !isAuthenticated())

  useEffect(() => {
    if (!AUTH_ENABLED) return
    if (!isAuthenticated()) void login()  // redirect to the Cognito hosted UI
    else setChecking(false)
  }, [])

  return checking ? <FullScreenMessage>Signing you in…</FullScreenMessage> : <>{children}</>
}

function NotFound() {
  return (
    <div className="h-full overflow-y-auto">
      <EmptyState
        tone="neutral" icon="search" title="Page not found"
        detail="That address doesn't match anything in CloudShield."
        action={<Link to="/violations" className="btn btn-accent">Go to findings</Link>}
      />
    </div>
  )
}

function Shell() {
  const { pathname } = useLocation()

  useEffect(() => {
    document.title = `${TITLES[pathname] ?? 'CloudShield'} · CloudShield Auditor`
  }, [pathname])

  return (
    <div className="flex h-[100dvh] overflow-hidden bg-bg">
      <a href="#main" className="sr-only z-50 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-bg focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <MobileNav />
        <main id="main" className="relative min-h-0 flex-1 overflow-hidden bg-grid">
          <ErrorBoundary resetKey={pathname}>
            {/* key on the path so each page fades in on navigation */}
            <div key={pathname} className="h-full animate-fade-in">
              <Suspense fallback={<FullScreenMessage>Loading…</FullScreenMessage>}>
                <Routes>
                  <Route path="/"             element={<Navigate to="/violations" replace />} />
                  <Route path="/violations"   element={<Violations />} />
                  <Route path="/my-resources" element={<MyResources />} />
                  <Route path="/posture"      element={<Posture />} />
                  <Route path="*"             element={<NotFound />} />
                </Routes>
              </Suspense>
            </div>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login"    element={<Login />} />
        <Route path="/callback" element={<Callback />} />
        <Route path="/*" element={
          <AuthGuard>
            <AppDataProvider>
              <Shell />
            </AppDataProvider>
          </AuthGuard>
        } />
      </Routes>
    </ToastProvider>
  )
}
