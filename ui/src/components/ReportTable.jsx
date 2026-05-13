import { useState } from 'react'
import { POLICY_INFO, SEV_ORDER, SEV_STYLES, RESOURCE_ACTIONS, getActionsForFindings } from '../lib/policyInfo'
import { runAction } from '../api'

const DESTRUCTIVE = new Set(['terminate','delete','deregister','release','revoke'])

// Safe actions — non-destructive
const SAFE_ACTIONS = new Set(['tag','notify','mark-for-op','snapshot','enable-access-logging',
  'toggle-versioning','set-bucket-encryption','block-public-access','enforce-ssl-policy'])

const CAT_BADGE = {
  security: 'text-orange-600 bg-orange-50 border-orange-200',
  cost:     'text-violet-600 bg-violet-50 border-violet-200',
}

// Severity sections — in display order
const SEV_SECTIONS = ['CRITICAL','HIGH','WARNING','MEDIUM','COST','LOW','INFO']

const SEV_LIGHT = {
  CRITICAL: { section: 'bg-red-50 border-red-200',     badge: 'bg-red-100 text-red-700 border-red-200',     dot: 'bg-red-500' },
  HIGH:     { section: 'bg-orange-50 border-orange-200', badge: 'bg-orange-100 text-orange-700 border-orange-200', dot: 'bg-orange-500' },
  WARNING:  { section: 'bg-amber-50 border-amber-200',  badge: 'bg-amber-100 text-amber-700 border-amber-200',  dot: 'bg-amber-500' },
  MEDIUM:   { section: 'bg-yellow-50 border-yellow-200', badge: 'bg-yellow-100 text-yellow-700 border-yellow-200', dot: 'bg-yellow-500' },
  COST:     { section: 'bg-violet-50 border-violet-200', badge: 'bg-violet-100 text-violet-700 border-violet-200', dot: 'bg-violet-500' },
  LOW:      { section: 'bg-blue-50 border-blue-200',    badge: 'bg-blue-100 text-blue-700 border-blue-200',    dot: 'bg-blue-400' },
  INFO:     { section: 'bg-gray-50 border-gray-200',    badge: 'bg-gray-100 text-gray-600 border-gray-200',    dot: 'bg-gray-400' },
}

function worstSev(findings) {
  return findings.reduce(
    (best, f) => (SEV_ORDER[f.severity] ?? 9) < (SEV_ORDER[best] ?? 9) ? f.severity : best,
    'INFO'
  )
}

// ── Main component ─────────────────────────────────────────────────
export default function ReportTable({ report, region, authType, extraPolicyInfo }) {
  const results    = report?.results || []
  const account    = report?.account
  const repRegion  = report?.region || region

  const policyLookup = extraPolicyInfo ? { ...POLICY_INFO, ...extraPolicyInfo } : POLICY_INFO

  // ── Build flat list of resource+findings, keyed by resourceId ──
  // severity comes from worst finding per resource
  const resourceMap = {}  // resourceId → { baseData, findings[], worstSev, service, resourceType }
  for (const r of results) {
    const info = policyLookup[r.policy] || {}
    const svc  = info.service      || 'other'
    const rt   = info.resourceType || 'Other'
    for (const res of (r.resources || [])) {
      const rid = res.ResourceId || 'unknown'
      if (!resourceMap[rid]) {
        resourceMap[rid] = { baseData: res, findings: [], service: svc, resourceType: rt }
      }
      resourceMap[rid].findings.push({
        policy:         r.policy,
        category:       info.category  || 'security',
        severity:       res.Severity   || info.severity || 'INFO',
        label:          info.label     || r.policy,
        finding:        res.Finding,
        recommendation: res.Recommendation,
      })
    }
  }

  // ── Group by worst severity ────────────────────────────────────
  const sevGroups = {}  // sev → [{ rid, ...resourceMap[rid] }]
  for (const [rid, data] of Object.entries(resourceMap)) {
    const sev = worstSev(data.findings)
    if (!sevGroups[sev]) sevGroups[sev] = []
    sevGroups[sev].push({ rid, ...data })
  }

  // ── Summary counts ──────────────────────────────────────────────
  const allRes   = Object.values(resourceMap)
  const total    = allRes.length
  const critical = (sevGroups['CRITICAL'] || []).length
  const high     = (sevGroups['HIGH'] || []).length
  const costOnly = allRes.filter(r => r.findings.every(f => f.category === 'cost')).length
  const clean    = results.filter(r => (r.resources || []).length === 0).length

  function exportCSV() {
    const cols = ['Account','Region','Service','ResourceType','ResourceId','Severity','Category','Policy','Finding','Recommendation']
    const rows = [cols.join(',')]
    for (const [rid, { baseData, findings, service, resourceType }] of Object.entries(resourceMap)) {
      for (const f of findings) {
        const row = [
          account?.account_id || '', repRegion || '',
          service, resourceType, rid,
          f.severity, f.category, f.policy,
          f.finding || '', f.recommendation || '',
        ].map(v => `"${String(v).replace(/"/g, '""')}"`)
        rows.push(row.join(','))
      }
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `c7n-report-${repRegion}-${new Date().toISOString().slice(0,10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (total === 0 && clean === 0) return (
    <div className="text-center py-16 text-gray-500 text-sm">
      No findings — all selected policies returned 0 resources.
    </div>
  )

  const activeSevs = SEV_SECTIONS.filter(s => sevGroups[s])

  return (
    <div className="space-y-4">

      {/* ── Account / Region header ─────────────────────────── */}
      <div className="card px-5 py-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-5 flex-wrap">
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider">Account</p>
            <p className="text-sm font-mono font-semibold text-gray-800">{account?.account_id || '—'}</p>
          </div>
          <div className="w-px h-8 bg-gray-200" />
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider">Region</p>
            <p className="text-sm font-mono font-semibold text-gray-800">{repRegion || '—'}</p>
          </div>
          <div className="w-px h-8 bg-gray-200" />
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider">Auth</p>
            <p className="text-sm font-semibold text-gray-800">
              {authType === 'iam-role' ? 'IAM Role' : 'Access Key'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Pill label="Resources" value={total}    color="text-gray-700 bg-gray-100" />
          <Pill label="Critical"  value={critical} color="text-red-700 bg-red-100" />
          <Pill label="High"      value={high}     color="text-orange-700 bg-orange-100" />
          <Pill label="Cost-only" value={costOnly} color="text-violet-700 bg-violet-100" />
          {clean > 0 && <Pill label="Clean" value={clean} color="text-emerald-700 bg-emerald-100" />}
          {total > 0 && (
            <button
              onClick={exportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-white hover:bg-gray-50 text-gray-600 border border-gray-300 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              Export CSV
            </button>
          )}
        </div>
      </div>

      {/* ── Severity sections ───────────────────────────────── */}
      {activeSevs.map(sev => (
        <SeveritySection
          key={sev}
          severity={sev}
          resources={sevGroups[sev]}
          region={repRegion}
          authType={authType}
        />
      ))}

    </div>
  )
}

// ── Severity section ───────────────────────────────────────────────
function SeveritySection({ severity, resources, region, authType }) {
  const [open, setOpen] = useState(severity === 'CRITICAL' || severity === 'HIGH')
  const styles = SEV_LIGHT[severity] || SEV_LIGHT.INFO

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div
        className={`flex items-center gap-3 px-5 py-3.5 cursor-pointer hover:bg-gray-50 transition-colors border-b border-gray-200`}
        onClick={() => setOpen(o => !o)}
      >
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
        </svg>
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${styles.dot}`} />
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${styles.badge}`}>
          {severity}
        </span>
        <span className="font-semibold text-gray-800 text-sm">{resources.length} resource{resources.length !== 1 ? 's' : ''}</span>
      </div>

      {open && (
        <div className="divide-y divide-gray-100">
          {resources.map(({ rid, baseData, findings, service, resourceType }) => (
            <SeverityResourceRow
              key={rid}
              resourceId={rid}
              baseData={baseData}
              findings={findings}
              service={service}
              resourceType={resourceType}
              region={region}
              authType={authType}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Single resource row (severity-first view) ──────────────────────
function SeverityResourceRow({ resourceId, baseData, findings, service, resourceType, region, authType }) {
  const [expanded,    setExpanded]    = useState(false)
  const [safeAction,  setSafeAction]  = useState('')
  const [destAction,  setDestAction]  = useState('')
  const [running,     setRunning]     = useState(false)
  const [actionResult,setActionResult]= useState(null)
  const [confirm,     setConfirm]     = useState(null)

  const worst    = worstSev(findings)
  const styles   = SEV_LIGHT[worst] || SEV_LIGHT.INFO
  const name     = baseData.GroupName || baseData.Name || baseData.InstanceId ||
                   baseData.VolumeId  || baseData.NetworkInterfaceId ||
                   baseData.ImageId   || baseData.PublicIp || resourceId

  const skipKeys = new Set(['Severity','Finding','ResourceId','Recommendation'])
  const meta = Object.entries(baseData).filter(([k]) => !skipKeys.has(k))

  // Get all available actions for this resource
  const allActions = getActionsForFindings(findings, resourceType)
  const safeActions = allActions.filter(a => !a.destructive)
  const destructiveActions = allActions.filter(a => a.destructive)

  function getPolicyForResource() {
    return findings[0]?.policy || null
  }

  async function execAction(action, label) {
    setRunning(true)
    setActionResult(null)
    const policyName = getPolicyForResource()
    try {
      const res = await runAction(policyName, [resourceId], action, { region, authType })
      setActionResult({ ok: true, msg: `${label} applied to ${res.resources_affected ?? 1} resource(s)` })
    } catch (e) {
      setActionResult({ ok: false, msg: e.message })
    }
    setRunning(false)
    setConfirm(null)
  }

  function handleSafeRun() {
    if (!safeAction || running) return
    const def = safeActions.find(a => a.value === safeAction)
    execAction(safeAction, def?.label || safeAction)
  }

  function handleDestRun() {
    if (!destAction || running) return
    const def = destructiveActions.find(a => a.value === destAction)
    setConfirm({ action: destAction, label: def?.label || destAction })
  }

  return (
    <div className={expanded ? 'bg-gray-50' : ''}>
      {/* Main row */}
      <div className="flex items-start gap-3 px-5 py-3 hover:bg-gray-50 transition-colors">

        {/* Severity badge */}
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 mt-0.5 ${styles.badge}`}>
          {worst}
        </span>

        {/* Resource info + findings chips */}
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => setExpanded(e => !e)}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-800">
              {name !== resourceId ? name : resourceId}
            </span>
            {name !== resourceId && (
              <span className="text-[11px] text-gray-400 font-mono">{resourceId}</span>
            )}
            <span className="text-[10px] text-gray-400 ml-auto">
              {expanded ? '▲ less' : '▼ details'}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="text-[10px] text-gray-500 font-mono">{resourceType}</span>
            <span className="text-gray-300">·</span>
            {findings.map((f, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border ${
                  SEV_LIGHT[f.severity]?.badge || SEV_LIGHT.INFO.badge
                }`}
                title={f.finding}
              >
                {f.label}
              </span>
            ))}
          </div>
        </div>

        {/* Action controls — safe (blue) and destructive (red) */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          {/* Safe actions */}
          {safeActions.length > 0 && (
            <div className="flex items-center gap-1">
              <select
                value={safeAction}
                onChange={e => setSafeAction(e.target.value)}
                onClick={e => e.stopPropagation()}
                className="px-2 py-1.5 text-xs bg-white border border-gray-300 rounded-lg text-gray-700 focus:outline-none focus:border-blue-500 min-w-[100px]"
              >
                <option value="">Safe action…</option>
                {safeActions.map(a => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
              <button
                onClick={e => { e.stopPropagation(); handleSafeRun() }}
                disabled={!safeAction || running}
                className="px-2.5 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
              >
                Run
              </button>
            </div>
          )}

          {/* Destructive actions */}
          {destructiveActions.length > 0 && (
            <div className="flex items-center gap-1">
              <select
                value={destAction}
                onChange={e => setDestAction(e.target.value)}
                onClick={e => e.stopPropagation()}
                className="px-2 py-1.5 text-xs bg-white border border-red-200 rounded-lg text-red-600 focus:outline-none focus:border-red-400 min-w-[110px]"
              >
                <option value="">⚠ Remediate…</option>
                {destructiveActions.map(a => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
              <button
                onClick={e => { e.stopPropagation(); handleDestRun() }}
                disabled={!destAction || running}
                className="px-2.5 py-1.5 text-xs font-semibold rounded-lg bg-red-600 hover:bg-red-700 text-white disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
              >
                Run
              </button>
            </div>
          )}

          {/* Fallback: single action selector if neither category */}
          {safeActions.length === 0 && destructiveActions.length === 0 && allActions.length > 0 && (
            <FallbackActions
              actions={allActions}
              resourceId={resourceId}
              running={running}
              onAction={(action, label, destructive) => {
                if (destructive) setConfirm({ action, label })
                else execAction(action, label)
              }}
            />
          )}
        </div>

      </div>

      {/* Action result */}
      {actionResult && (
        <div className={`px-5 py-2 text-xs ${actionResult.ok ? 'text-emerald-700' : 'text-red-600'}`}>
          {actionResult.msg}
        </div>
      )}

      {/* Expanded detail panel */}
      {expanded && (
        <div className="px-10 pb-4 space-y-2.5">
          {findings.map((f, i) => (
            <div key={i} className="bg-white rounded-lg border border-gray-200 p-3">
              <div className="flex items-start gap-2 mb-2 flex-wrap">
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${SEV_LIGHT[f.severity]?.badge || SEV_LIGHT.INFO.badge}`}>
                  {f.severity}
                </span>
                <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border shrink-0 ${CAT_BADGE[f.category] || CAT_BADGE.security}`}>
                  {f.category === 'security' ? 'SECURITY' : 'COST'}
                </span>
                <span className="text-xs text-gray-700 flex-1 min-w-0">{f.finding}</span>
                <span className="text-[10px] text-gray-400 font-mono shrink-0">{f.policy}</span>
              </div>
              {f.recommendation && (
                <pre className="text-[11px] text-blue-700 whitespace-pre-wrap font-mono leading-relaxed bg-blue-50 rounded p-2 border border-blue-100">
                  {f.recommendation}
                </pre>
              )}
            </div>
          ))}

          {meta.length > 0 && (
            <div className="bg-white rounded-lg p-3 border border-gray-200">
              <p className="text-[11px] font-bold uppercase tracking-wider text-gray-500 mb-2">Resource Details</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                {meta.map(([k, v]) => (
                  <div key={k} className="flex gap-2 min-w-0">
                    <span className="text-[11px] text-gray-500 shrink-0 w-28">{k}</span>
                    <span className="text-[11px] text-gray-700 font-mono truncate" title={String(v)}>
                      {String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {confirm && (
        <ConfirmDialog
          action={confirm.label}
          scope="1 resource"
          onConfirm={() => execAction(confirm.action, confirm.label)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}

// ── Fallback single action selector ────────────────────────────────
function FallbackActions({ actions, resourceId, running, onAction }) {
  const [rowAction, setRowAction] = useState('')
  return (
    <div className="flex items-center gap-1">
      <select
        value={rowAction}
        onChange={e => setRowAction(e.target.value)}
        onClick={e => e.stopPropagation()}
        className="px-2 py-1.5 text-xs bg-white border border-gray-300 rounded-lg text-gray-700 focus:outline-none focus:border-blue-500 min-w-[110px]"
      >
        <option value="">Action…</option>
        {actions.map(a => (
          <option key={a.value} value={a.value}>{a.label}{a.destructive ? ' ⚠' : ''}</option>
        ))}
      </select>
      <button
        onClick={e => {
          e.stopPropagation()
          if (rowAction) {
            const def = actions.find(a => a.value === rowAction)
            onAction(rowAction, def?.label || rowAction, def?.destructive || false)
          }
        }}
        disabled={!rowAction || running}
        className="px-2.5 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Run
      </button>
    </div>
  )
}

// ── Confirmation modal ─────────────────────────────────────────────
function ConfirmDialog({ action, scope, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/>
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">Confirm: {action}</p>
            <p className="text-xs text-gray-500 mt-0.5">Runs LIVE on {scope}. Cannot be undone.</p>
          </div>
        </div>
        <div className="flex gap-3 mt-4">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 text-sm rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700 border border-gray-200"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2 text-sm rounded-lg bg-red-600 hover:bg-red-700 text-white font-medium"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

function Pill({ label, value, color }) {
  return (
    <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ${color}`}>
      <span className="opacity-70">{label}</span>
      <span className="font-bold">{value}</span>
    </span>
  )
}
