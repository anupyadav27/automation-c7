const severityStyles = {
  CRITICAL: 'bg-red-500/15 text-red-400 border-red-500/30',
  HIGH: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  WARNING: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  MEDIUM: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  COST: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
  LOW: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  INFO: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
}

export default function ResultModal({ name, result, onClose }) {
  const allResults = result?.results || []
  const totalResources = allResults.reduce((sum, r) => {
    const counts = r?.resources_found || {}
    return sum + Object.values(counts).reduce((a, b) => a + (b > 0 ? b : 0), 0)
  }, 0)
  const hasMultiple = allResults.length > 1

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-semibold text-gray-100">{name}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {result?.dryrun ? 'Dry Run' : 'Live Run'} &middot; {result?.execution_time || ''} &middot; {totalResources} resources found
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="overflow-y-auto p-6 space-y-4" style={{ maxHeight: 'calc(85vh - 65px)' }}>
          {/* Summary strip */}
          <div className="grid grid-cols-3 gap-3">
            <SummaryCard label="Policies Run" value={allResults.length} color="text-blue-400" />
            <SummaryCard label="Resources Found" value={totalResources} color={totalResources > 0 ? 'text-amber-400' : 'text-emerald-400'} />
            <SummaryCard label="Status" value={allResults.every(r => r.status === 'success') ? 'Success' : 'Error'} color={allResults.every(r => r.status === 'success') ? 'text-emerald-400' : 'text-red-400'} />
          </div>

          {/* Per-policy results */}
          {allResults.map((policyResult, idx) => (
            <PolicyResultSection key={idx} policyResult={policyResult} defaultOpen={!hasMultiple || allResults.length <= 3} />
          ))}

          {/* Raw JSON */}
          <details className="group">
            <summary className="text-xs font-medium text-gray-600 cursor-pointer hover:text-gray-400">
              Raw JSON Response
            </summary>
            <pre className="mt-2 bg-gray-950 rounded-lg border border-gray-800 p-4 text-[11px] text-gray-600 overflow-x-auto whitespace-pre-wrap max-h-48">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </div>
      </div>
    </div>
  )
}

function PolicyResultSection({ policyResult, defaultOpen }) {
  const resources = policyResult?.resources || []
  const counts = policyResult?.resources_found || {}
  const count = Object.values(counts).reduce((a, b) => a + (b > 0 ? b : 0), 0)

  if (count === 0 && resources.length === 0) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-950/50 p-4">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-medium text-gray-300">{policyResult.policy}</span>
          <span className="text-xs text-emerald-400 ml-auto">Clean — no issues found</span>
        </div>
        {policyResult.description && (
          <p className="text-xs text-gray-600 mt-1 ml-5">{policyResult.description}</p>
        )}
      </div>
    )
  }

  return (
    <details open={defaultOpen} className="group rounded-xl border border-gray-800 bg-gray-950/50 overflow-hidden">
      <summary className="flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-900/50">
        <svg className="w-4 h-4 text-gray-600 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-sm font-semibold text-gray-200">{policyResult.policy}</span>
        <span className="text-xs font-medium text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
          {count} {count === 1 ? 'issue' : 'issues'}
        </span>
      </summary>

      {policyResult.description && (
        <p className="text-xs text-gray-500 px-4 pb-2 -mt-1 ml-7">{policyResult.description}</p>
      )}

      <div className="px-4 pb-4 space-y-3">
        {resources.map((res, i) => (
          <ResourceCard key={i} resource={res} />
        ))}
      </div>
    </details>
  )
}

function ResourceCard({ resource }) {
  const severity = resource.Severity || 'INFO'
  const sevStyle = severityStyles[severity] || severityStyles.INFO

  // Separate known display fields from metadata
  const { Finding, Description, Recommendation, Severity, ResourceId, ...metadata } = resource

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Finding header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-start gap-3">
        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase border mt-0.5 shrink-0 ${sevStyle}`}>
          {severity}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-200">{Finding || ResourceId}</p>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{ResourceId}</p>
        </div>
      </div>

      {/* Description */}
      {Description && (
        <div className="px-4 py-2.5 border-b border-gray-800">
          <p className="text-xs text-gray-400">{Description}</p>
        </div>
      )}

      {/* Recommendation */}
      {Recommendation && (
        <div className="px-4 py-3 border-b border-gray-800 bg-blue-500/5">
          <p className="text-[10px] font-bold uppercase tracking-wider text-blue-400 mb-1.5">Recommendation</p>
          <pre className="text-xs text-blue-300/80 whitespace-pre-wrap font-mono leading-relaxed">{Recommendation}</pre>
        </div>
      )}

      {/* Metadata grid */}
      {Object.keys(metadata).length > 0 && (
        <div className="px-4 py-2.5 grid grid-cols-2 gap-x-6 gap-y-1.5">
          {Object.entries(metadata).map(([key, val]) => (
            <div key={key} className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-gray-600 truncate">{key}</span>
              <span className="text-[11px] text-gray-400 font-mono truncate text-right">{String(val)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SummaryCard({ label, value, color }) {
  return (
    <div className="bg-gray-950 rounded-lg border border-gray-800 p-3">
      <p className="text-[11px] text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-lg font-bold mt-0.5 ${color}`}>{value}</p>
    </div>
  )
}
