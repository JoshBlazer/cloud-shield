import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend,
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { mockApi, MOCK_TREND } from '../api/mock'
import type { Summary } from '../types'

const SEV_COLORS: Record<string, string> = {
  CRITICAL: '#ff4d4f',
  HIGH:     '#fa8c16',
  MEDIUM:   '#fadb14',
}

export function Posture() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    mockApi.getSummary().then((s) => { setSummary(s); setLoading(false) })
  }, [])

  if (loading || !summary) {
    return <div className="flex items-center justify-center h-full text-muted">Loading posture…</div>
  }

  const open      = summary.by_status['OPEN']         ?? 0
  const acked     = summary.by_status['ACKNOWLEDGED'] ?? 0
  const resolved  = summary.by_status['RESOLVED']     ?? 0
  const total     = summary.total
  const score     = total === 0 ? 100 : Math.min(100, Math.round((resolved / (total || 1)) * 100))

  const teamData = Object.entries(summary.by_team).map(([team, counts]) => ({
    team,
    Open:       counts['OPEN']         ?? 0,
    Acked:      counts['ACKNOWLEDGED'] ?? 0,
    Resolved:   counts['RESOLVED']     ?? 0,
  }))

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="px-6 py-4 border-b border-border bg-surface flex-shrink-0">
        <h1 className="text-base font-semibold text-text">Posture</h1>
        <p className="text-xs text-muted mt-0.5">Infrastructure compliance overview</p>
      </div>

      <div className="px-6 py-6 space-y-8">
        {/* Stat tiles */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Compliance Score', value: `${score}%`, color: score > 80 ? '#52c41a' : score > 50 ? '#fa8c16' : '#ff4d4f' },
            { label: 'Open Violations',  value: open,  color: '#ff4d4f' },
            { label: 'Acknowledged',     value: acked, color: '#69c0ff' },
            { label: 'Resolved',         value: resolved, color: '#52c41a' },
          ].map(({ label, value, color }) => (
            <div key={label} className="card px-5 py-4 text-center">
              <div className="text-3xl font-bold" style={{ color }}>{value}</div>
              <div className="text-[11px] text-muted uppercase tracking-widest mt-1">{label}</div>
            </div>
          ))}
        </div>

        {/* Trend chart */}
        <div className="card px-5 py-5">
          <h2 className="text-sm font-semibold text-text mb-4">Violations This Week</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={MOCK_TREND} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="day" tick={{ fill: '#595959', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#595959', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1a1a1a', border: '1px solid #262626', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#d9d9d9' }}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: '#595959' }} />
              {(['CRITICAL', 'HIGH', 'MEDIUM'] as const).map((sev) => (
                <Line
                  key={sev}
                  type="monotone"
                  dataKey={sev}
                  stroke={SEV_COLORS[sev]}
                  strokeWidth={2}
                  dot={{ r: 3, fill: SEV_COLORS[sev] }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Team breakdown bar chart */}
        <div className="card px-5 py-5">
          <h2 className="text-sm font-semibold text-text mb-4">Team Breakdown</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={teamData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="team" tick={{ fill: '#595959', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#595959', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#1a1a1a', border: '1px solid #262626', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#d9d9d9' }}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: '#595959' }} />
              <Bar dataKey="Open"     fill="#ff4d4f" radius={[3, 3, 0, 0]} maxBarSize={32} />
              <Bar dataKey="Acked"    fill="#69c0ff" radius={[3, 3, 0, 0]} maxBarSize={32} />
              <Bar dataKey="Resolved" fill="#52c41a" radius={[3, 3, 0, 0]} maxBarSize={32} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Team table */}
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[#1a1a1a] border-b border-border">
                {['Team', 'Open', 'Acknowledged', 'Resolved'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs text-muted font-semibold uppercase tracking-widest">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {teamData
                .sort((a, b) => b.Open - a.Open)
                .map(({ team, Open, Acked, Resolved }) => (
                  <tr key={team} className="border-b border-border last:border-0 hover:bg-[#1a1a1a]">
                    <td className="px-4 py-3 text-text">{team}</td>
                    <td className="px-4 py-3 font-bold" style={{ color: Open > 0 ? '#ff4d4f' : '#595959' }}>{Open}</td>
                    <td className="px-4 py-3 text-accent">{Acked}</td>
                    <td className="px-4 py-3 text-low">{Resolved}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
