import { useState, useEffect } from 'react'

export default function RunHistory() {
  const [history, setHistory] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('c7n_history') || '[]')
    } catch { return [] }
  })

  // Re-read localStorage whenever this page becomes visible
  useEffect(() => {
    function refresh() {
      try {
        setHistory(JSON.parse(localStorage.getItem('c7n_history') || '[]'))
      } catch {}
    }
    window.addEventListener('focus', refresh)
    refresh()
    return () => window.removeEventListener('focus', refresh)
  }, [])

  function clearHistory() {
    setHistory([])
    localStorage.removeItem('c7n_history')
  }

  // Compute per-run resource totals for chart
  const chartData = history.slice(0, 7).reverse().map((entry, i) => {
    const total = (entry.data?.results || []).flatMap(r => r.resources || []).length
    return { label: entry.timestamp?.slice(5, 16) || `Run ${i + 1}`, total }
  })

  const maxVal = Math.max(...chartData.map(d => d.total), 1)

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Run History</h1>
          <p className="text-sm text-gray-500 mt-1">
            Recent policy executions (stored in browser)
          </p>
        </div>
        {history.length > 0 && (
          <button
            onClick={clearHistory}
            className="btn-secondary text-sm"
          >
            Clear History
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="text-center py-20">
          <svg className="w-12 h-12 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-gray-400">No runs yet. Execute a scan from the Scan page.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Trend chart */}
          {chartData.length > 1 && (
            <div className="card p-5">
              <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide mb-4">Findings Trend</h2>
              <TrendChart data={chartData} maxVal={maxVal} />
            </div>
          )}

          {/* Table */}
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Timestamp</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Scan Name</th>
                  <th className="text-center px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Findings</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Region</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Mode</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {history.map((entry, i) => {
                  const total = (entry.data?.results || []).flatMap(r => r.resources || []).length
                  const critical = (entry.data?.results || []).flatMap(r => r.resources || []).filter(r => r.Severity === 'CRITICAL').length
                  const isDry = entry.data?.dryrun !== false
                  return (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      <td className="px-5 py-3 text-xs text-gray-500 font-mono whitespace-nowrap">
                        {entry.timestamp}
                      </td>
                      <td className="px-5 py-3">
                        <p className="text-sm font-medium text-gray-800 truncate max-w-xs" title={entry.policy}>
                          {entry.policy}
                        </p>
                      </td>
                      <td className="px-5 py-3 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <span className={`text-sm font-bold ${total > 0 ? 'text-gray-900' : 'text-gray-400'}`}>
                            {total}
                          </span>
                          {critical > 0 && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 border border-red-200">
                              {critical} crit
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-5 py-3 text-xs text-gray-500 font-mono">
                        {entry.data?.region || '—'}
                      </td>
                      <td className="px-5 py-3">
                        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                          isDry
                            ? 'bg-emerald-100 text-emerald-700'
                            : 'bg-red-100 text-red-700'
                        }`}>
                          {isDry ? 'Dry Run' : 'Live'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// Simple SVG line chart
function TrendChart({ data, maxVal }) {
  const W = 600
  const H = 100
  const PAD = { top: 10, right: 20, bottom: 30, left: 35 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const xStep = innerW / Math.max(data.length - 1, 1)

  const points = data.map((d, i) => ({
    x: PAD.left + i * xStep,
    y: PAD.top + innerH - (d.total / maxVal) * innerH,
    ...d,
  }))

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const areaD = pathD + ` L ${points[points.length - 1].x} ${PAD.top + innerH} L ${PAD.left} ${PAD.top + innerH} Z`

  // Y-axis ticks
  const yTicks = [0, Math.round(maxVal / 2), maxVal]

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: '300px', maxHeight: '120px' }}>
        {/* Grid lines */}
        {yTicks.map(v => {
          const y = PAD.top + innerH - (v / maxVal) * innerH
          return (
            <g key={v}>
              <line x1={PAD.left} y1={y} x2={PAD.left + innerW} y2={y} stroke="#e5e7eb" strokeWidth="1" />
              <text x={PAD.left - 4} y={y + 4} fontSize="8" fill="#9ca3af" textAnchor="end">{v}</text>
            </g>
          )
        })}

        {/* Area fill */}
        <path d={areaD} fill="url(#areaGrad)" opacity="0.3" />

        {/* Line */}
        <path d={pathD} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinejoin="round" />

        {/* Dots + x-labels */}
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r="3.5" fill="#3b82f6" stroke="white" strokeWidth="1.5" />
            <text
              x={p.x}
              y={PAD.top + innerH + 18}
              fontSize="7"
              fill="#6b7280"
              textAnchor="middle"
            >
              {p.label}
            </text>
          </g>
        ))}

        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b82f6" />
            <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  )
}

// Re-exported from lib/history for backward compatibility
export { saveToHistory } from '../lib/history'
