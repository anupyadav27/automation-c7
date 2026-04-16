import { useState, useEffect } from 'react'
import StatusBadge from '../components/StatusBadge'
import ResultModal from '../components/ResultModal'

export default function RunHistory() {
  const [history, setHistory] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('c7n_history') || '[]')
    } catch { return [] }
  })
  const [selected, setSelected] = useState(null)

  // Re-read localStorage whenever this page becomes visible (tab focus / navigation)
  useEffect(() => {
    function refresh() {
      try {
        setHistory(JSON.parse(localStorage.getItem('c7n_history') || '[]'))
      } catch {}
    }
    window.addEventListener('focus', refresh)
    // Also refresh on navigation to this page
    refresh()
    return () => window.removeEventListener('focus', refresh)
  }, [])

  function clearHistory() {
    setHistory([])
    localStorage.removeItem('c7n_history')
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Run History</h1>
          <p className="text-sm text-gray-500 mt-1">
            Recent policy executions (stored in browser)
          </p>
        </div>
        {history.length > 0 && (
          <button
            onClick={clearHistory}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 border border-gray-700"
          >
            Clear History
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="text-center py-20">
          <svg className="w-12 h-12 text-gray-700 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-gray-500">No runs yet. Execute a policy from the Dashboard or Policies page.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {history.map((entry, i) => {
            const r = entry.data?.results?.[0]
            const totalResources = r?.resources_found
              ? Object.values(r.resources_found).reduce((a, b) => a + (b > 0 ? b : 0), 0)
              : 0

            return (
              <div
                key={i}
                className="flex items-center justify-between p-4 rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 cursor-pointer transition-colors"
                onClick={() => setSelected(entry)}
              >
                <div className="flex items-center gap-4 min-w-0">
                  <span className="text-sm font-mono font-semibold text-gray-200 whitespace-nowrap">
                    {entry.policy}
                  </span>
                  <StatusBadge status={entry.data?.dryrun ? 'dryrun' : (r?.status || 'error')} />
                  {totalResources > 0 && (
                    <span className="text-xs text-amber-400 font-medium">
                      {totalResources} resources
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-gray-600">{entry.timestamp}</span>
                  <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {selected && (
        <ResultModal
          name={selected.policy}
          result={selected.data}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

// Re-exported from lib/history for backward compatibility
export { saveToHistory } from '../lib/history'
