import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { POLICY_INFO, POLICY_DESC, SEV_ORDER } from '../lib/policyInfo'
import { getUserRules, getUserGroups, deleteUserRule } from '../lib/userRules'

const SEV_BADGE = {
  CRITICAL: 'bg-red-100 text-red-700 border-red-200',
  HIGH:     'bg-orange-100 text-orange-700 border-orange-200',
  WARNING:  'bg-amber-100 text-amber-700 border-amber-200',
  MEDIUM:   'bg-yellow-100 text-yellow-700 border-yellow-200',
  COST:     'bg-violet-100 text-violet-700 border-violet-200',
  LOW:      'bg-blue-100 text-blue-700 border-blue-200',
  INFO:     'bg-gray-100 text-gray-600 border-gray-200',
}

// Built-in groups derived from POLICY_INFO
const BUILTIN_GROUPS = [
  { id: 'security', label: 'Security', icon: '🔐', color: 'border-red-200 bg-red-50 text-red-700' },
  { id: 'cost',     label: 'Cost Optimization', icon: '💰', color: 'border-violet-200 bg-violet-50 text-violet-700' },
]

export default function PolicyLibrary() {
  const navigate                        = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeGroup                     = searchParams.get('group') || 'security'

  const [userRules,    setUserRules]    = useState([])
  const [selectedRule, setSelectedRule] = useState(null)
  const [search,       setSearch]       = useState('')

  useEffect(() => { setUserRules(getUserRules()) }, [])

  function setActiveGroup(gid) {
    setSearchParams({ group: gid })
    setSelectedRule(null)
    setSearch('')
  }

  // All user-defined group names
  const userGroups = useMemo(() => {
    const seen = new Set()
    return userRules
      .map(r => r.group)
      .filter(g => g && !seen.has(g) && seen.add(g))
      .map(g => ({ id: g, label: g, icon: '⭐', color: 'border-blue-200 bg-blue-50 text-blue-700' }))
  }, [userRules])

  const allGroups = [...BUILTIN_GROUPS, ...userGroups]

  // Rules for the active group
  const groupRules = useMemo(() => {
    const q = search.toLowerCase()
    if (activeGroup === 'security' || activeGroup === 'cost') {
      // Built-in rules from POLICY_INFO
      return Object.entries(POLICY_INFO)
        .filter(([, info]) => info.category === activeGroup)
        .filter(([name, info]) =>
          !q || name.includes(q) || info.label.toLowerCase().includes(q)
        )
        .sort(([, a], [, b]) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9))
        .map(([name, info]) => ({
          id: name,
          name,
          label: info.label,
          severity: info.severity,
          service: info.service,
          resourceType: info.resourceType,
          suggestedActions: info.suggestedActions || [],
          isBuiltin: true,
        }))
    }
    // User-defined group
    return userRules
      .filter(r => r.group === activeGroup)
      .filter(r => !q || r.name?.includes(q) || r.label?.toLowerCase().includes(q))
      .sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9))
      .map(r => ({ ...r, isBuiltin: false }))
  }, [activeGroup, userRules, search])

  // Counts per group
  function groupCount(gid) {
    if (gid === 'security') return Object.values(POLICY_INFO).filter(i => i.category === 'security').length
    if (gid === 'cost')     return Object.values(POLICY_INFO).filter(i => i.category === 'cost').length
    return userRules.filter(r => r.group === gid).length
  }

  function handleDeleteRule(id) {
    deleteUserRule(id)
    setUserRules(getUserRules())
    if (selectedRule?.id === id) setSelectedRule(null)
  }

  return (
    <div className="flex h-full">
      {/* ── Left: Groups + Rule List ─────────────────────────────── */}
      <div className="w-72 border-r border-gray-200 bg-white flex flex-col shrink-0">
        {/* Header */}
        <div className="px-4 py-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">Policy Library</h1>
          <p className="text-xs text-gray-500 mt-0.5">Browse built-in and custom policies by group</p>
        </div>

        {/* Search */}
        <div className="px-3 pt-3 pb-2">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search rules…"
            className="w-full px-3 py-1.5 text-sm bg-gray-50 border border-gray-200 rounded-lg text-gray-800 placeholder-gray-400 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* Group tabs */}
        <div className="px-3 pb-2 space-y-0.5">
          {allGroups.map(g => (
            <button
              key={g.id}
              onClick={() => setActiveGroup(g.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeGroup === g.id
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <span className="flex items-center gap-2">
                <span>{g.icon}</span>
                <span>{g.label}</span>
              </span>
              <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded-full ${
                activeGroup === g.id ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
              }`}>
                {groupCount(g.id)}
              </span>
            </button>
          ))}
          <button
            onClick={() => navigate('/build')}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-blue-600 hover:bg-blue-50 transition-colors border border-dashed border-blue-200 mt-2"
          >
            <span className="text-base">+</span>
            <span>Create new group via Build Policy</span>
          </button>
        </div>

        {/* Rule list */}
        <div className="flex-1 overflow-y-auto border-t border-gray-200">
          {groupRules.length === 0 ? (
            <div className="text-center py-10 text-gray-400 text-sm px-4">
              {search ? 'No rules match your search.' : 'No rules in this group yet.'}
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {groupRules.map(rule => (
                <button
                  key={rule.id}
                  onClick={() => setSelectedRule(rule)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                    selectedRule?.id === rule.id ? 'bg-blue-50 border-r-2 border-blue-600' : ''
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 mt-0.5 ${SEV_BADGE[rule.severity] || SEV_BADGE.INFO}`}>
                      {rule.severity}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-gray-800 leading-snug">{rule.label}</p>
                      <p className="text-[11px] text-gray-400 mt-0.5">{rule.resourceType || rule.service}</p>
                    </div>
                    {!rule.isBuiltin && (
                      <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-100 text-blue-700 border border-blue-200 shrink-0 ml-auto">MY</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Right: Rule Detail Panel ─────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {!selectedRule ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mb-4">
              <svg className="w-7 h-7 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
            </div>
            <p className="text-gray-500 text-sm font-medium">Select a rule to view details</p>
            <p className="text-gray-400 text-xs mt-1">Click any rule from the list on the left</p>
          </div>
        ) : (
          <RuleDetail
            rule={selectedRule}
            onEdit={() => navigate('/build', { state: { ruleId: selectedRule.id } })}
            onDelete={() => handleDeleteRule(selectedRule.id)}
            onRunScan={() => navigate('/scan', { state: { ruleNames: [selectedRule.name] } })}
          />
        )}
      </div>
    </div>
  )
}

function RuleDetail({ rule, onEdit, onDelete, onRunScan }) {
  const desc = POLICY_DESC[rule.name] || {}
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Build a YAML preview for built-in or user-defined rules
  const yamlText = rule.isBuiltin
    ? null
    : buildYaml(rule)

  return (
    <div className="p-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`text-xs font-bold px-2 py-0.5 rounded border ${SEV_BADGE[rule.severity] || SEV_BADGE.INFO}`}>
              {rule.severity}
            </span>
            {!rule.isBuiltin && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 border border-blue-200">
                Custom Rule
              </span>
            )}
          </div>
          <h2 className="text-xl font-bold text-gray-900 leading-tight">{rule.label}</h2>
          <p className="text-sm text-gray-500 font-mono mt-1">{rule.name}</p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={onRunScan}
            className="btn-primary text-xs px-4 py-2"
          >
            ▶ Run Scan
          </button>
          {!rule.isBuiltin && (
            <>
              <button onClick={onEdit} className="btn-secondary text-xs px-3 py-2">Edit</button>
              <button
                onClick={() => setConfirmDelete(true)}
                className="px-3 py-2 text-xs font-medium rounded-lg bg-white hover:bg-red-50 text-red-600 border border-red-200 transition-colors"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {/* Metadata grid */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        <MetaBox label="Service" value={rule.service?.toUpperCase() || '—'} />
        <MetaBox label="Resource Type" value={rule.resourceType || '—'} />
        <MetaBox label="Category" value={rule.category || '—'} />
      </div>

      {/* Description */}
      {(desc.desc || rule.description) && (
        <div className="card p-4 mb-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">What this rule checks</h3>
          <p className="text-sm text-gray-800 leading-relaxed">{desc.desc || rule.description}</p>
        </div>
      )}

      {/* Recommendation */}
      {(desc.recommendation || rule.recommendation) && (
        <div className="card p-4 mb-4 border-l-4 border-l-blue-400">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recommendation</h3>
          <p className="text-sm text-gray-800 leading-relaxed">{desc.recommendation || rule.recommendation}</p>
        </div>
      )}

      {/* No metadata fallback for built-in rules */}
      {rule.isBuiltin && !desc.desc && (
        <div className="card p-4 mb-4 bg-amber-50 border-amber-200">
          <p className="text-sm text-amber-700">
            Detailed description not yet added for this rule. Run it to see live findings with recommendations.
          </p>
        </div>
      )}

      {/* Suggested Actions */}
      {rule.suggestedActions?.length > 0 && (
        <div className="card p-4 mb-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Suggested Remediation Actions</h3>
          <div className="flex flex-wrap gap-2">
            {rule.suggestedActions.map(a => (
              <span key={a} className="px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-700 border border-gray-200">
                {a}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* YAML (user rules only) */}
      {yamlText && (
        <div className="card p-4 mb-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Policy YAML</h3>
          <pre className="text-xs text-gray-700 bg-gray-50 rounded-lg p-3 overflow-x-auto border border-gray-200 leading-relaxed">
            {yamlText}
          </pre>
        </div>
      )}

      {/* Group badge */}
      {rule.group && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span className="font-medium text-gray-600">Group:</span>
          <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 text-xs font-medium">
            {rule.group}
          </span>
        </div>
      )}

      {/* Confirm delete */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl">
            <p className="text-sm font-semibold text-gray-900 mb-1">Delete "{rule.label}"?</p>
            <p className="text-xs text-gray-500 mb-4">This removes the rule from your library. The action cannot be undone.</p>
            <div className="flex gap-3">
              <button onClick={() => setConfirmDelete(false)} className="btn-secondary flex-1">Cancel</button>
              <button onClick={onDelete} className="flex-1 px-4 py-2 text-sm rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MetaBox({ label, value }) {
  return (
    <div className="card p-3 text-center">
      <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-sm font-semibold text-gray-800">{value}</p>
    </div>
  )
}

function buildYaml(rule) {
  const spec = rule.spec || {}
  const filters = (spec.filters || []).map(f => {
    const { type, ...params } = f
    const lines = [`    - type: ${type}`]
    Object.entries(params).forEach(([k, v]) => {
      lines.push(`      ${k}: ${JSON.stringify(v)}`)
    })
    return lines.join('\n')
  }).join('\n')

  return `policies:
  - name: ${spec.name || rule.name}
    resource: aws.${spec.resource || ''}
    filters:
${filters || '      []'}
    actions:
${(spec.actions || []).map(a => `      - type: ${a.type || a}`).join('\n') || '      []'}`
}
