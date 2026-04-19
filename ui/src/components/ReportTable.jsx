import { useState } from 'react'
import { POLICY_INFO, SEV_ORDER, SEV_STYLES, RESOURCE_ACTIONS, getActionsForFindings } from '../lib/policyInfo'
import { runAction } from '../api'

const DESTRUCTIVE = new Set(['terminate','delete','deregister','release','revoke'])

const SERVICE_LABELS = {
  ec2:           'EC2 / Security Groups',
  s3:            'S3 Buckets',
  ebs:           'EBS Volumes',
  eni:           'ENI / Elastic IP',
  ami:           'AMI Images',
  rds:           'RDS Databases',
  iam:           'IAM',
  lambda:        'Lambda',
  cloudtrail:    'CloudTrail',
  vpc:           'VPC / Networking',
  secretsmanager:'Secrets Manager',
  other:         'Other',
}
const SERVICE_ORDER = ['ec2','s3','ebs','eni','ami','rds','iam','lambda','cloudtrail','vpc','secretsmanager']

const CAT_BADGE = {
  security: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
  cost:     'text-violet-400 bg-violet-500/10 border-violet-500/20',
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

  // extraPolicyInfo lets callers (e.g. PolicyBuilder) inject metadata for dynamic
  // policy names that aren't in the static POLICY_INFO registry
  const policyLookup = extraPolicyInfo ? { ...POLICY_INFO, ...extraPolicyInfo } : POLICY_INFO

  // ── Build tree: service → resourceType → resourceId → { baseData, findings[] }
  const tree = {}
  for (const r of results) {
    const info = policyLookup[r.policy] || {}
    const svc  = info.service      || 'other'
    const rt   = info.resourceType || 'Other'
    for (const res of (r.resources || [])) {
      const rid = res.ResourceId || 'unknown'
      tree[svc]               = tree[svc]               || {}
      tree[svc][rt]           = tree[svc][rt]           || {}
      tree[svc][rt][rid]      = tree[svc][rt][rid]      || { baseData: res, findings: [] }
      tree[svc][rt][rid].findings.push({
        policy:         r.policy,
        category:       info.category  || 'security',
        severity:       res.Severity   || info.severity || 'INFO',
        label:          info.label     || r.policy,
        finding:        res.Finding,
        recommendation: res.Recommendation,
      })
    }
  }

  // ── Summary counts ──────────────────────────────────────────────
  const allResources = Object.values(tree)
    .flatMap(rtMap => Object.values(rtMap))
    .flatMap(ridMap => Object.values(ridMap))
  const total    = allResources.length
  const critical = allResources.filter(r => worstSev(r.findings) === 'CRITICAL').length
  const high     = allResources.filter(r => worstSev(r.findings) === 'HIGH').length
  const costOnly = allResources.filter(r => r.findings.every(f => f.category === 'cost')).length
  const clean    = results.filter(r => (r.resources || []).length === 0).length

  function exportCSV() {
    const cols = ['Account', 'Region', 'Service', 'ResourceType', 'ResourceId', 'Name', 'Severity', 'Category', 'Policy', 'Finding', 'Recommendation']
    const rows = [cols.join(',')]
    for (const [svc, rtMap] of Object.entries(tree)) {
      for (const [rt, ridMap] of Object.entries(rtMap)) {
        for (const [rid, { baseData, findings }] of Object.entries(ridMap)) {
          const name = baseData.GroupName || baseData.Name || baseData.InstanceId || rid
          for (const f of findings) {
            const row = [
              account?.account_id || '',
              repRegion || '',
              svc, rt, rid, name,
              f.severity, f.category, f.policy,
              f.finding || '', f.recommendation || '',
            ].map(v => `"${String(v).replace(/"/g, '""')}"`)
            rows.push(row.join(','))
          }
        }
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
    <div className="text-center py-16 text-gray-600 text-sm">
      No findings — all selected policies returned 0 resources.
    </div>
  )

  const activeServices = SERVICE_ORDER.filter(s => tree[s])
  Object.keys(tree).forEach(s => { if (!SERVICE_ORDER.includes(s)) activeServices.push(s) })

  return (
    <div className="space-y-4">

      {/* ── Account / Region header ───────────────────────────── */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 px-5 py-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-5 flex-wrap">
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Account</p>
            <p className="text-sm font-mono font-semibold text-gray-200">{account?.account_id || '—'}</p>
          </div>
          <div className="w-px h-8 bg-gray-800" />
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Region</p>
            <p className="text-sm font-mono font-semibold text-gray-200">{repRegion || '—'}</p>
          </div>
          <div className="w-px h-8 bg-gray-800" />
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Auth</p>
            <p className="text-sm font-semibold text-gray-200">
              {authType === 'iam-role' ? 'IAM Role' : 'Access Key'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Pill label="Resources" value={total}    color="text-gray-300 bg-gray-800" />
          <Pill label="Critical"  value={critical} color="text-red-400 bg-red-500/10" />
          <Pill label="High"      value={high}     color="text-orange-400 bg-orange-500/10" />
          <Pill label="Cost-only" value={costOnly} color="text-violet-400 bg-violet-500/10" />
          {clean > 0 && <Pill label="Clean" value={clean} color="text-emerald-400 bg-emerald-500/10" />}
          {total > 0 && (
            <button
              onClick={exportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              Export CSV
            </button>
          )}
        </div>
      </div>

      {/* ── Service sections ──────────────────────────────────── */}
      {activeServices.map(svc => (
        <ServiceSection
          key={svc}
          label={SERVICE_LABELS[svc] || svc}
          rtMap={tree[svc]}
          region={repRegion}
          authType={authType}
        />
      ))}

    </div>
  )
}

// ── Service section ────────────────────────────────────────────────
function ServiceSection({ label, rtMap, region, authType }) {
  const [open, setOpen] = useState(true)
  const total = Object.values(rtMap)
    .reduce((sum, ridMap) => sum + Object.keys(ridMap).length, 0)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div
        className="flex items-center gap-3 px-5 py-3.5 cursor-pointer hover:bg-gray-800/40 transition-colors border-b border-gray-800"
        onClick={() => setOpen(o => !o)}
      >
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
        </svg>
        <span className="font-bold text-gray-100 text-sm">{label}</span>
        <span className="text-[11px] text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">
          {total} resource{total !== 1 ? 's' : ''}
        </span>
      </div>

      {open && (
        <div className="divide-y divide-gray-800/60">
          {Object.entries(rtMap).map(([rt, ridMap]) => (
            <ResourceTypeGroup
              key={rt}
              resourceType={rt}
              ridMap={ridMap}
              region={region}
              authType={authType}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Resource-type group ────────────────────────────────────────────
function ResourceTypeGroup({ resourceType, ridMap, region, authType }) {
  const [open, setOpen]             = useState(true)
  const [bulkAction, setBulkAction] = useState('')
  const [checkedIds, setCheckedIds] = useState(new Set())
  const [actionResult, setActionResult] = useState(null)
  const [running, setRunning]       = useState(false)
  const [confirm, setConfirm]       = useState(null)

  const resources = Object.entries(ridMap)   // [[rid, {baseData, findings[]}], ...]

  // Per-resource action lists — sg-unused gets delete-only, sg-open-ssh gets revoke, etc.
  const perResourceActions = Object.fromEntries(
    resources.map(([rid, { findings }]) => [rid, getActionsForFindings(findings, resourceType)])
  )
  // Group-level bulk action list = deduplicated union of all per-resource actions
  const seen = new Set()
  const actions = resources
    .flatMap(([rid]) => perResourceActions[rid])
    .filter(a => seen.has(a.value) ? false : seen.add(a.value))

  const allChecked = resources.length > 0 && resources.every(([rid]) => checkedIds.has(rid))
  function toggleAll() {
    setCheckedIds(allChecked ? new Set() : new Set(resources.map(([rid]) => rid)))
  }
  function toggleOne(rid) {
    setCheckedIds(prev => { const n = new Set(prev); n.has(rid) ? n.delete(rid) : n.add(rid); return n })
  }

  function getPolicyForIds(ids) {
    for (const id of ids) {
      const p = ridMap[id]?.findings?.[0]?.policy
      if (p) return p
    }
    return null
  }

  async function execAction(ids, action) {
    setRunning(true)
    setActionResult(null)
    const policyName = getPolicyForIds(ids)
    try {
      const res = await runAction(policyName, ids, action, { region, authType })
      setActionResult({ ok: true, msg: `${action} applied to ${res.resources_affected ?? ids.length} resource(s)` })
    } catch (e) {
      setActionResult({ ok: false, msg: e.message })
    }
    setRunning(false)
    setConfirm(null)
  }

  function handleBulkRun() {
    const ids = Array.from(checkedIds)
    if (!ids.length || !bulkAction) return
    const def = actions.find(a => a.value === bulkAction)
    if (def?.destructive) setConfirm({ ids, action: bulkAction, label: def.label, scope: `${ids.length} resource(s)` })
    else execAction(ids, bulkAction)
  }

  const groupWorst = resources.reduce((best, [, { findings }]) => {
    const ws = worstSev(findings)
    return (SEV_ORDER[ws] ?? 9) < (SEV_ORDER[best] ?? 9) ? ws : best
  }, 'INFO')
  const sevStyle = SEV_STYLES[groupWorst] || SEV_STYLES.INFO

  return (
    <div>
      {/* ResourceType header */}
      <div
        className="flex items-center gap-2.5 px-5 py-2.5 cursor-pointer hover:bg-gray-800/20 transition-colors bg-gray-950/40"
        onClick={() => setOpen(o => !o)}
      >
        <svg
          className={`w-3.5 h-3.5 text-gray-600 transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
        </svg>
        <span className="text-xs font-semibold text-gray-400">{resourceType}</span>
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${sevStyle}`}>
          {resources.length}
        </span>
        {checkedIds.size > 0 && (
          <span className="text-[11px] text-blue-400 ml-1">{checkedIds.size} selected</span>
        )}
      </div>

      {open && (
        <>
          {/* Bulk action bar */}
          <div className="flex items-center gap-2 px-5 py-2 bg-gray-950/60 border-y border-gray-800/50 flex-wrap">
            <input type="checkbox" checked={allChecked} onChange={toggleAll}
              className="w-3 h-3 accent-blue-500 shrink-0" />
            <span className="text-[11px] text-gray-600 mr-1">All</span>
            <select
              value={bulkAction}
              onChange={e => setBulkAction(e.target.value)}
              className="flex-1 min-w-[140px] max-w-[200px] px-2 py-1 text-xs bg-gray-900 border border-gray-700 rounded-lg text-gray-300 focus:outline-none focus:border-blue-500"
            >
              <option value="">Bulk action…</option>
              {actions.map(a => (
                <option key={a.value} value={a.value}>{a.label}{a.destructive ? ' ⚠' : ''}</option>
              ))}
            </select>
            <button
              onClick={handleBulkRun}
              disabled={!checkedIds.size || !bulkAction || running}
              className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {running
                ? <><div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"/>Running…</>
                : '▶ Run'}
            </button>
            {actionResult && (
              <span className={`text-xs ${actionResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                {actionResult.msg}
              </span>
            )}
          </div>

          {/* Resource rows */}
          <div className="divide-y divide-gray-800/30">
            {resources.map(([rid, { baseData, findings }]) => (
              <ResourceRow
                key={rid}
                resourceId={rid}
                baseData={baseData}
                findings={findings}
                actions={perResourceActions[rid]}
                checked={checkedIds.has(rid)}
                onCheck={() => toggleOne(rid)}
                onAction={(ids, action, label) => {
                  if (DESTRUCTIVE.has(action))
                    setConfirm({ ids, action, label, scope: '1 resource' })
                  else
                    execAction(ids, action)
                }}
                running={running}
              />
            ))}
          </div>
        </>
      )}

      {confirm && (
        <ConfirmDialog
          action={confirm.label}
          scope={confirm.scope}
          onConfirm={() => execAction(confirm.ids, confirm.action)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  )
}

// ── Single resource row ────────────────────────────────────────────
function ResourceRow({ resourceId, baseData, findings, actions, checked, onCheck, onAction, running }) {
  const [expanded,  setExpanded]  = useState(false)
  const [rowAction, setRowAction] = useState('')

  const worst    = worstSev(findings)
  const sevStyle = SEV_STYLES[worst] || SEV_STYLES.INFO
  const name     = baseData.GroupName || baseData.Name || baseData.InstanceId ||
                   baseData.VolumeId  || baseData.NetworkInterfaceId ||
                   baseData.ImageId   || baseData.PublicIp || resourceId

  const skipKeys = new Set(['Severity','Finding','ResourceId','Recommendation'])
  const meta = Object.entries(baseData).filter(([k]) => !skipKeys.has(k))

  return (
    <div className={`${expanded ? 'bg-gray-900/60' : ''} hover:bg-gray-800/10 transition-colors`}>

      {/* ── Main row ───────────────────────────────────────────── */}
      <div className="flex items-start gap-3 px-5 py-3">

        {/* Checkbox */}
        <input
          type="checkbox" checked={checked} onChange={onCheck}
          className="w-3.5 h-3.5 accent-blue-500 shrink-0 mt-1"
          onClick={e => e.stopPropagation()}
        />

        {/* Worst-severity badge */}
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase border shrink-0 mt-0.5 ${sevStyle}`}>
          {worst}
        </span>

        {/* Resource name + findings chips */}
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => setExpanded(e => !e)}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-gray-200">
              {name !== resourceId ? name : resourceId}
            </span>
            {name !== resourceId && (
              <span className="text-[11px] text-gray-500 font-mono">{resourceId}</span>
            )}
            <span className="text-[10px] text-gray-600 ml-auto">
              {expanded ? '▲ less' : '▼ details'}
            </span>
          </div>

          {/* All findings as compact chips — never clips */}
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {findings.map((f, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border ${SEV_STYLES[f.severity] || SEV_STYLES.INFO}`}
                title={f.finding}
              >
                <span className="font-bold">{f.severity}</span>
                <span className="opacity-80 max-w-[160px] truncate">{f.label}</span>
                <span className={`ml-0.5 px-1 py-px rounded text-[9px] font-semibold border ${CAT_BADGE[f.category] || CAT_BADGE.security}`}>
                  {f.category === 'security' ? 'SEC' : '$$$'}
                </span>
              </span>
            ))}
          </div>
        </div>

        {/* Action controls — flex, wraps instead of clipping */}
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end min-w-0">
          <select
            value={rowAction}
            onChange={e => setRowAction(e.target.value)}
            onClick={e => e.stopPropagation()}
            className="px-2 py-1.5 text-xs bg-gray-950 border border-gray-700 rounded-lg text-gray-300 focus:outline-none focus:border-blue-500 min-w-[110px] max-w-[150px]"
          >
            <option value="">Action…</option>
            {actions.map(a => (
              <option key={a.value} value={a.value}>{a.label}{a.destructive ? ' ⚠' : ''}</option>
            ))}
          </select>
          <button
            onClick={e => {
              e.stopPropagation()
              if (rowAction) onAction([resourceId], rowAction, actions.find(a => a.value === rowAction)?.label)
            }}
            disabled={!rowAction || running}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            Run
          </button>
        </div>

      </div>

      {/* ── Expanded detail panel ─────────────────────────────── */}
      {expanded && (
        <div className="px-11 pb-4 space-y-2.5">

          {/* Per-finding recommendation cards */}
          {findings.map((f, i) => (
            <div key={i} className="bg-gray-950 rounded-lg border border-gray-800 p-3">
              <div className="flex items-start gap-2 mb-2 flex-wrap">
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${SEV_STYLES[f.severity] || SEV_STYLES.INFO}`}>
                  {f.severity}
                </span>
                <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border shrink-0 ${CAT_BADGE[f.category] || CAT_BADGE.security}`}>
                  {f.category === 'security' ? 'SECURITY' : 'COST'}
                </span>
                <span className="text-xs text-gray-300 flex-1 min-w-0">{f.finding}</span>
                <span className="text-[10px] text-gray-600 font-mono shrink-0">{f.policy}</span>
              </div>
              {f.recommendation && (
                <pre className="text-[11px] text-blue-300/80 whitespace-pre-wrap font-mono leading-relaxed bg-blue-500/5 rounded p-2 border border-blue-500/15">
                  {f.recommendation}
                </pre>
              )}
            </div>
          ))}

          {/* Resource metadata grid */}
          {meta.length > 0 && (
            <div className="bg-gray-950 rounded-lg p-3 border border-gray-800">
              <p className="text-[11px] font-bold uppercase tracking-wider text-gray-500 mb-2">
                Resource Details
              </p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                {meta.map(([k, v]) => (
                  <div key={k} className="flex gap-2 min-w-0">
                    <span className="text-[11px] text-gray-600 shrink-0 w-28">{k}</span>
                    <span
                      className="text-[11px] text-gray-400 font-mono truncate"
                      title={String(v)}
                    >
                      {String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      )}

    </div>
  )
}

// ── Confirmation modal ─────────────────────────────────────────────
function ConfirmDialog({ action, scope, onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-500/15 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/>
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-100">Confirm: {action}</p>
            <p className="text-xs text-gray-500 mt-0.5">Runs LIVE on {scope}. Cannot be undone.</p>
          </div>
        </div>
        <div className="flex gap-3 mt-4">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 text-sm rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2 text-sm rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium"
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
