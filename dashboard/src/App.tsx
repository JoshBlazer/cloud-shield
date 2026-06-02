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

  const loadSummary = () => {
    mockApi.getSummary().then(setSummary)
  }

  useEffect(() => { loadSummary() }, [])

  const handleTriggerAudit = async () => {
    setAuditRunning(true)
    setAuditMsg(null)
    try {
      const r = await mockApi.triggerAudit()
      setAuditMsg(`Audit complete: ${r.resources_audited} resources, ${r.violations_found} violation(s)`)
      loadSummary()
    } finally {
      setAuditRunning(false)
      setTimeout(() => setAuditMsg(null), 4000)
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <Sidebar summary={summary} onTriggerAudit={handleTriggerAudit} auditRunning={auditRunning} />

      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Topbar */}
        <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface flex-shrink-0">
          <div className="text-xs text-muted">Infrastructure Drift &amp; Compliance</div>
          {auditMsg && (
            <div className="text-xs text-low bg-low/10 border border-low/30 px-3 py-1 rounded">
              {auditMsg}
            </div>
          )}
          <div className="text-[11px] text-muted">
            {summary ? `${summary.total} total records` : ''}
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-hidden">
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
