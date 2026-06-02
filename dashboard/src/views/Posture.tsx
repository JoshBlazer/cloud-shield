import { useEffect, useState } from 'react'
import {
  Area, AreaChart,
  Bar, BarChart,
  CartesianGrid, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { mockApi, MOCK_TREND } from '../api/mock'
import type { Summary } from '../types'

function ComplianceRing({ score }: { score: number }) {
  const r      = 52
  const circ   = 2 * Math.PI * r
  const offset = circ - (circ * score / 100)
  const color  = score >= 75 ? '#4ade80' : score >= 45 ? '#fbbf24' : '#f87171'

  return (
    <div className="relative flex items-center justify-center" style={{ width: 148, height: 148 }}>
      <svg width="148" height="148" style={{ transform: 'rotate(-90deg)', overflow: 'visible' }}>
        <circle cx="74" cy="74" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="9" />
        <circle
          cx="74" cy="74" r={r}
          fill="none"
          stroke={color}
          strokeWidth="9"
          strokeDasharray={`${circ}`}
          strokeDashoffset={`${offset}`}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 10px ${color})` }}
        />
      </svg>
      <div className="absolute text-center">
        <div className="text-3xl font-bold tabular-nums" style={{ color }}>{score}%</div>
        <div
          className="text-[9px] tracking-[0.15em] uppercase font-semibold mt-0.5"
          style={{ color: 'rgba(122,132,153,0.6)' }}
        >
          score
        </div>
      </div>
    </div>
  )
}

const CHART_TOOLTIP = {
  contentStyle: {
    background: '#0f1724',
    border: '1px solid #192130',
    borderRadius: 8,
    fontSize: 12,
    boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
  },
  labelStyle: { color: '#dde3ef', fontWeight: 600 },
}

const AXIS_PROPS = {
  tick: { fill: '#4b5568', fontSize: 11 },
  axisLine: false as const,
  tickLine: false as const,
}

export function Posture() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    mockApi.getSummary().then((s) => { setSummary(s); setLoading(false) })
  }, [])

  if (loading || !summary) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: '#4b5568' }}>
        Loading posture…
      </div>
    )
  }

  const open     = summary.by_status['OPEN']         ?? 0
  const acked    = summary.by_status['ACKNOWLEDGED'] ?? 0
  const snoozed  = summary.by_status['SNOOZED']      ?? 0
  const resolved = summary.by_status['RESOLVED']     ?? 0
  const total    = summary.total
  // score = resolved / all-time total; cannot exceed 100 or go below 0
  const score    = total === 0 ? 100 : Math.min(100, Math.max(0, Math.round((resolved / total) * 100)))

  const teamData = Object.entries(summary.by_team).map(([team, counts]) => ({
    team,
    Open:     counts['OPEN']         ?? 0,
    Acked:    counts['ACKNOWLEDGED'] ?? 0,
    Snoozed:  counts['SNOOZED']      ?? 0,
    Resolved: counts['RESOLVED']     ?? 0,
  }))

  const statTiles = [
    { label: 'Open',         value: open,     color: '#f87171', bg: 'rgba(248,113,113,0.08)', border: 'rgba(248,113,113,0.18)' },
    { label: 'Acknowledged', value: acked,    color: '#60a5fa', bg: 'rgba(96,165,250,0.08)',  border: 'rgba(96,165,250,0.18)'  },
    { label: 'Snoozed',      value: snoozed,  color: '#fb923c', bg: 'rgba(251,146,60,0.08)',  border: 'rgba(251,146,60,0.18)'  },
    { label: 'Resolved',     value: resolved, color: '#4ade80', bg: 'rgba(74,222,128,0.08)',  border: 'rgba(74,222,128,0.18)'  },
  ]

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Page header */}
      <div
        className="px-6 py-4 flex-shrink-0"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(11,16,25,0.5)' }}
      >
        <h1 className="text-base font-bold text-text">Posture</h1>
        <p className="text-xs mt-0.5" style={{ color: '#4b5568' }}>Infrastructure compliance overview</p>
      </div>

      <div className="px-6 py-6 space-y-6">
        {/* Hero card: compliance ring + stat tiles */}
        <div
          className="rounded-xl p-6"
          style={{
            background: 'linear-gradient(135deg, rgba(15,23,36,0.9) 0%, rgba(11,16,25,0.6) 100%)',
            border: '1px solid rgba(255,255,255,0.06)',
            boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
          }}
        >
          <div className="flex items-center gap-8 flex-wrap">
            {/* Ring */}
            <div className="flex flex-col items-center gap-2">
              <ComplianceRing score={score} />
              <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: '#4b5568' }}>
                Compliance Score
              </p>
            </div>

            {/* Divider */}
            <div className="w-px h-28 hidden md:block" style={{ background: 'rgba(255,255,255,0.05)' }} />

            {/* Stat tiles */}
            <div className="flex flex-1 gap-3 flex-wrap min-w-0">
              {statTiles.map(({ label, value, color, bg, border }) => (
                <div
                  key={label}
                  className="flex-1 min-w-[90px] rounded-xl px-4 py-4 text-center"
                  style={{ background: bg, border: `1px solid ${border}` }}
                >
                  <div
                    className="text-4xl font-bold tabular-nums leading-none"
                    style={{ color }}
                  >
                    {value}
                  </div>
                  <div
                    className="text-[10px] uppercase tracking-widest font-semibold mt-2"
                    style={{ color: 'rgba(122,132,153,0.6)' }}
                  >
                    {label}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Trend chart */}
        <div
          className="rounded-xl px-5 py-5"
          style={{ background: 'rgba(11,16,25,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}
        >
          <h2 className="text-sm font-bold text-text mb-5">Violations This Week</h2>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={MOCK_TREND} margin={{ top: 5, right: 10, bottom: 5, left: -10 }}>
              <defs>
                <linearGradient id="gradCrit" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#f87171" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradHigh" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#fb923c" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#fb923c" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradMed" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#fbbf24" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#fbbf24" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="day" {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} allowDecimals={false} />
              <Tooltip {...CHART_TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#4b5568', paddingTop: 8 }} />
              <Area type="monotone" dataKey="CRITICAL" stroke="#f87171" fill="url(#gradCrit)" strokeWidth={2} dot={{ r: 3, fill: '#f87171', strokeWidth: 0 }} activeDot={{ r: 5, fill: '#f87171' }} />
              <Area type="monotone" dataKey="HIGH"     stroke="#fb923c" fill="url(#gradHigh)" strokeWidth={2} dot={{ r: 3, fill: '#fb923c', strokeWidth: 0 }} activeDot={{ r: 5, fill: '#fb923c' }} />
              <Area type="monotone" dataKey="MEDIUM"   stroke="#fbbf24" fill="url(#gradMed)"  strokeWidth={2} dot={{ r: 3, fill: '#fbbf24', strokeWidth: 0 }} activeDot={{ r: 5, fill: '#fbbf24' }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Team breakdown */}
        <div
          className="rounded-xl px-5 py-5"
          style={{ background: 'rgba(11,16,25,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}
        >
          <h2 className="text-sm font-bold text-text mb-5">Team Breakdown</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={teamData} margin={{ top: 5, right: 10, bottom: 5, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="team" {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} allowDecimals={false} />
              <Tooltip {...CHART_TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#4b5568', paddingTop: 8 }} />
              <Bar dataKey="Open"     fill="#f87171" radius={[4, 4, 0, 0]} maxBarSize={28} />
              <Bar dataKey="Acked"    fill="#60a5fa" radius={[4, 4, 0, 0]} maxBarSize={28} />
              <Bar dataKey="Snoozed"  fill="#fb923c" radius={[4, 4, 0, 0]} maxBarSize={28} />
              <Bar dataKey="Resolved" fill="#4ade80" radius={[4, 4, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Team table */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: '1px solid rgba(255,255,255,0.05)' }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                {['Team', 'Open', 'Acknowledged', 'Snoozed', 'Resolved'].map((h) => (
                  <th
                    key={h}
                    className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: '#4b5568' }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {teamData
                .sort((a, b) => b.Open - a.Open)
                .map(({ team, Open, Acked, Snoozed, Resolved }) => (
                  <tr
                    key={team}
                    className="transition-colors"
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                    onMouseOver={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                    onMouseOut={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td className="px-5 py-3 font-medium" style={{ color: '#dde3ef' }}>{team}</td>
                    <td className="px-5 py-3 font-bold tabular-nums" style={{ color: Open > 0 ? '#f87171' : '#4b5568' }}>{Open}</td>
                    <td className="px-5 py-3 tabular-nums" style={{ color: '#60a5fa' }}>{Acked}</td>
                    <td className="px-5 py-3 tabular-nums" style={{ color: Snoozed > 0 ? '#fb923c' : '#4b5568' }}>{Snoozed}</td>
                    <td className="px-5 py-3 tabular-nums" style={{ color: '#4ade80' }}>{Resolved}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
