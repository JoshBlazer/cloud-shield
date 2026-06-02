import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { mockApi } from './api/mock'
import { Sidebar } from './components/Sidebar'
import type { Summary } from './types'
import { MyResources } from './views/MyResources'
import { Posture } from './views/Posture'
import { Violations } from './views/Violations'

export default function App() {
  const [summary, setSummary]         = useState<Summary | null>(null)
  const [auditRunning, setAuditRunning] = useState(false)
  const [auditMsg, setAuditMsg]       = useState<string | null>(null)

  const loadSummary = () => { mockApi.getSummary().then(setSummary) }

  useEffect(() => { loadSummary() }, [])

  const handleTriggerAudit = async () => {
    setAuditRunning(true)
    setAuditMsg(null)
    try {
      const r = await mockApi.triggerAudit()
      setAuditMsg(`${r.resources_audited} resources scanned · ${r.violations_found} violation${r.violations_found !== 1 ? 's' : ''} found`)
      loadSummary()
    } finally {
      setAuditRunning(false)
      setTimeout(() => setAuditMsg(null), 5000)
    }
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#06090f' }}>
      <Sidebar summary={summary} onTriggerAudit={handleTriggerAudit} auditRunning={auditRunning} />

      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Topbar */}
        <header
          className="flex items-center justify-between px-6 py-3 flex-shrink-0"
          style={{
            background: 'rgba(11,16,25,0.85)',
            borderBottom: '1px solid rgba(96,165,250,0.06)',
            backdropFilter: 'blur(10px)',
          }}
        >
          <div className="flex items-center gap-2.5">
            <div className="dot-live" />
            <span className="text-xs" style={{ color: 'rgba(122,132,153,0.7)' }}>
              Infrastructure Drift &amp; Compliance
            </span>
          </div>

          {auditMsg && (
            <div
              className="text-xs px-3 py-1.5 rounded-lg animate-fade-in flex items-center gap-1.5"
              style={{
                background: 'rgba(74,222,128,0.08)',
                color: '#4ade80',
                border: '1px solid rgba(74,222,128,0.2)',
                boxShadow: '0 0 12px rgba(74,222,128,0.1)',
              }}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <polyline points="2,6.5 4.5,9 10,3"/>
              </svg>
              {auditMsg}
            </div>
          )}

          <div className="text-[11px]" style={{ color: 'rgba(75,85,104,0.8)' }}>
            {summary ? `${summary.total} violations tracked` : ''}
          </div>
        </header>

        {/* Main content with grid bg */}
        <main
          className="flex-1 overflow-hidden bg-grid"
          style={{ background: 'radial-gradient(ellipse at 60% 0%, rgba(96,165,250,0.04) 0%, transparent 55%)' }}
        >
          <Routes>
            <Route path="/"             element={<Navigate to="/violations" replace />} />
            <Route path="/violations"   element={<Violations />} />
            <Route path="/my-resources" element={<MyResources />} />
            <Route path="/posture"      element={<Posture />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
