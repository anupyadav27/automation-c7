import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

const PRESETS = [
  { id: 'security', label: 'Security Baseline', icon: '🔴', desc: 'Critical security risks — open ports, unencrypted volumes, IAM issues', color: 'border-red-200 hover:border-red-400 hover:bg-red-50' },
  { id: 'cost',     label: 'Cost Cleanup',       icon: '💰', desc: 'Unattached resources, old snapshots, oversized instances', color: 'border-violet-200 hover:border-violet-400 hover:bg-violet-50' },
  { id: 'full',     label: 'Full Audit',          icon: '📋', desc: 'All security and cost policies across all services', color: 'border-blue-200 hover:border-blue-400 hover:bg-blue-50' },
  { id: 'custom',   label: 'Custom Scan',         icon: '⚙️', desc: 'Choose specific policies manually', color: 'border-gray-200 hover:border-gray-400 hover:bg-gray-50' },
]

const SEV_COLORS = {
  CRITICAL: 'text-red-700 bg-red-100',
  HIGH:     'text-orange-700 bg-orange-100',
  MEDIUM:   'text-yellow-700 bg-yellow-100',
  WARNING:  'text-amber-700 bg-amber-100',
  COST:     'text-violet-700 bg-violet-100',
  LOW:      'text-blue-700 bg-blue-100',
  INFO:     'text-gray-600 bg-gray-100',
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [history, setHistory] = useState([])
  const [lastScan, setLastScan] = useState(null)

  useEffect(() => {
    try {
      const h = JSON.parse(localStorage.getItem('c7n_history') || '[]')
      setHistory(h.slice(0, 6))
      if (h.length > 0) setLastScan(h[0])
    } catch {}
  }, [])

  // Compute summary from last scan
  const results = lastScan?.data?.results || []
  const allResources = results.flatMap(r => r.resources || [])
  const critical = allResources.filter(r => r.Severity === 'CRITICAL').length
  const high     = allResources.filter(r => r.Severity === 'HIGH').length
  const cost     = allResources.filter(r => r.Severity === 'COST').length
  const total    = allResources.length

  // Top findings — sorted by severity
  const SEV_ORDER = { CRITICAL: 0, HIGH: 1, WARNING: 2, MEDIUM: 3, COST: 4, LOW: 5, INFO: 6 }
  const topFindings = results
    .flatMap(r => (r.resources || []).map(res => ({
      severity:   res.Severity || 'INFO',
      resourceId: res.ResourceId || '',
      label:      res.Finding || r.policy,
      policy:     r.policy,
    })))
    .sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9))
    .slice(0, 6)

  function goToScan(presetId) {
    navigate('/scan', { state: { preset: presetId } })
  }

  return (
    <div className="p-6 max-w-6xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        {lastScan ? (
          <p className="text-sm text-gray-500 mt-1">
            Last scan: {lastScan.timestamp} · {lastScan.data?.region || '—'}
          </p>
        ) : (
          <p className="text-sm text-gray-500 mt-1">No scans yet — run your first scan below</p>
        )}
      </div>

      {/* Summary Cards */}
      {lastScan && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <SummaryCard label="Critical"        value={critical} color="text-red-700 bg-red-50 border-red-200" />
          <SummaryCard label="High"            value={high}     color="text-orange-700 bg-orange-50 border-orange-200" />
          <SummaryCard label="Cost"            value={cost}     color="text-violet-700 bg-violet-50 border-violet-200" />
          <SummaryCard label="Total Resources" value={total}    color="text-gray-700 bg-gray-50 border-gray-200" />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Top Findings */}
        <div className="lg:col-span-2 card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide">Top Findings</h2>
            <button
              onClick={() => navigate('/scan')}
              className="text-xs font-medium text-blue-600 hover:text-blue-700"
            >
              Run New Scan →
            </button>
          </div>
          {topFindings.length === 0 ? (
            <div className="text-center py-10 text-gray-400 text-sm">
              No findings yet. Run a scan to see results.
            </div>
          ) : (
            <div className="space-y-2">
              {topFindings.map((f, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg hover:bg-gray-50">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${SEV_COLORS[f.severity] || SEV_COLORS.INFO}`}>
                    {f.severity}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-gray-800 truncate">{f.label}</p>
                    <p className="text-xs text-gray-400 font-mono truncate mt-0.5">{f.resourceId}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Scans */}
        <div className="card p-5">
          <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide mb-4">Recent Scans</h2>
          {history.length === 0 ? (
            <div className="text-center py-10 text-gray-400 text-sm">No history yet</div>
          ) : (
            <div className="space-y-2">
              {history.map((h, i) => {
                const hTotal = (h.data?.results || []).flatMap(r => r.resources || []).length
                return (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-gray-800 truncate">{h.policy}</p>
                      <p className="text-[11px] text-gray-400 mt-0.5">{h.timestamp}</p>
                    </div>
                    <span className="text-xs font-semibold text-gray-600 ml-2 shrink-0">{hTotal} found</span>
                  </div>
                )
              })}
              <button
                onClick={() => navigate('/history')}
                className="w-full text-center text-xs text-blue-600 hover:text-blue-700 pt-2"
              >
                View All History →
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Quick Start */}
      <div className="mt-5">
        <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide mb-3">Quick Start</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {PRESETS.map(p => (
            <button
              key={p.id}
              onClick={() => goToScan(p.id)}
              className={`text-left p-4 rounded-xl border-2 bg-white transition-all ${p.color}`}
            >
              <div className="text-xl mb-2">{p.icon}</div>
              <div className="text-sm font-semibold text-gray-900 mb-1">{p.label}</div>
              <div className="text-xs text-gray-500 leading-relaxed">{p.desc}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function SummaryCard({ label, value, color }) {
  return (
    <div className={`rounded-xl border p-4 ${color}`}>
      <p className="text-xs font-medium uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-3xl font-bold mt-1">{value}</p>
    </div>
  )
}
