import { useState, useEffect, useMemo } from 'react'
import { listPolicies, runPolicies } from '../api'
import { POLICY_INFO, SEV_ORDER, SEV_STYLES } from '../lib/policyInfo'
import { saveToHistory } from '../lib/history'
import ReportTable from '../components/ReportTable'

const REGIONS = [
  { value: 'ap-south-1',    label: 'ap-south-1 (Mumbai)' },
  { value: 'us-east-1',     label: 'us-east-1 (N. Virginia)' },
  { value: 'us-east-2',     label: 'us-east-2 (Ohio)' },
  { value: 'us-west-1',     label: 'us-west-1 (N. California)' },
  { value: 'us-west-2',     label: 'us-west-2 (Oregon)' },
  { value: 'eu-west-1',     label: 'eu-west-1 (Ireland)' },
  { value: 'eu-west-2',     label: 'eu-west-2 (London)' },
  { value: 'eu-central-1',  label: 'eu-central-1 (Frankfurt)' },
  { value: 'ap-southeast-1',label: 'ap-southeast-1 (Singapore)' },
  { value: 'ap-southeast-2',label: 'ap-southeast-2 (Sydney)' },
  { value: 'ap-northeast-1',label: 'ap-northeast-1 (Tokyo)' },
  { value: 'ca-central-1',  label: 'ca-central-1 (Canada)' },
]

const AUTH_TYPES = [
  { value: 'access-key', label: 'Access Key / Secret' },
  { value: 'aws-profile', label: 'AWS Profile (~/.aws)' },
  { value: 'iam-role',   label: 'IAM Role (Lambda)' },
]

const SERVICES = [
  { value: 'all', label: 'All Services' },
  { value: 'ec2', label: 'EC2 / Security Groups' },
  { value: 's3',  label: 'S3 Buckets' },
  { value: 'ebs', label: 'EBS Volumes' },
  { value: 'eni', label: 'ENI / Elastic IP' },
  { value: 'ami', label: 'AMI Images' },
]

const CATEGORIES = [
  { value: 'all',      label: 'All Categories' },
  { value: 'security', label: 'Security' },
  { value: 'cost',     label: 'Cost Optimisation' },
]

const SEV_BADGE = {
  CRITICAL: 'bg-red-500/20 text-red-400',
  HIGH:     'bg-orange-500/20 text-orange-400',
  WARNING:  'bg-amber-500/20 text-amber-400',
  MEDIUM:   'bg-yellow-500/20 text-yellow-400',
  COST:     'bg-violet-500/20 text-violet-400',
  LOW:      'bg-blue-500/20 text-blue-400',
  INFO:     'bg-gray-500/20 text-gray-400',
}

export default function RunReport() {
  // ── filters ──────────────────────────────────────────────
  const [region,   setRegion]   = useState('ap-south-1')
  const [authType, setAuthType] = useState('access-key')
  const [service,  setService]  = useState('all')
  const [category, setCategory] = useState('all')

  // ── API data ──────────────────────────────────────────────
  const [policyData, setPolicyData] = useState(null)
  const [loadError,  setLoadError]  = useState(null)

  // ── rules selection ───────────────────────────────────────
  const [selected, setSelected] = useState(new Set())

  // ── run state ─────────────────────────────────────────────
  const [running,  setRunning]  = useState(false)
  const [report,   setReport]   = useState(null)
  const [runError, setRunError] = useState(null)

  // ── load policy list whenever auth type changes ───────────
  useEffect(() => {
    setPolicyData(null)
    setLoadError(null)
    listPolicies(authType)
      .then(d => setPolicyData(d))
      .catch(e => setLoadError(e.message))
  }, [authType])

  // ── derive visible rules from service + category filter ───
  const visibleRules = useMemo(() => {
    const known = Object.entries(POLICY_INFO)
    return known
      .filter(([, info]) => service  === 'all' || info.service  === service)
      .filter(([, info]) => category === 'all' || info.category === category)
      .sort(([, a], [, b]) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9))
  }, [service, category])

  // reset selections when filter changes
  useEffect(() => { setSelected(new Set()) }, [service, category])

  // ── select-all toggle ─────────────────────────────────────
  const allSelected = visibleRules.length > 0 && visibleRules.every(([n]) => selected.has(n))
  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(visibleRules.map(([n]) => n)))
    }
  }
  function toggleRule(name) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  // ── run ───────────────────────────────────────────────────
  async function handleRun() {
    if (selected.size === 0) return
    setRunning(true)
    setReport(null)
    setRunError(null)
    try {
      const data = await runPolicies(Array.from(selected), {
        dryrun: true,
        region,
        authType,
      })
      setReport(data)
      saveToHistory(Array.from(selected).join(', '), data)
    } catch (e) {
      setRunError(e.message)
    }
    setRunning(false)
  }

  // ── account info ──────────────────────────────────────────
  const account = policyData?.account

  return (
    <div className="p-6 space-y-5">

      {/* ── Filter bar ─────────────────────────────────────── */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">

        {/* Row 1 — 5 dropdowns */}
        <div className="flex gap-3 flex-wrap">

          {/* Account — read-only */}
          <div className="flex-1 min-w-[160px]">
            <label className="filter-label">Account</label>
            <div className="filter-display">
              {account
                ? <><span className="text-gray-200 font-mono text-xs">{account.account_id}</span></>
                : loadError
                  ? <span className="text-red-400 text-xs">Cannot connect</span>
                  : <span className="text-gray-600 text-xs animate-pulse">Detecting…</span>
              }
            </div>
          </div>

          {/* Region */}
          <div className="flex-1 min-w-[190px]">
            <label className="filter-label">Region</label>
            <select value={region} onChange={e => setRegion(e.target.value)} className="filter-select">
              {REGIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>

          {/* Auth Type */}
          <div className="flex-1 min-w-[180px]">
            <label className="filter-label">Auth Type</label>
            <select value={authType} onChange={e => setAuthType(e.target.value)} className="filter-select">
              {AUTH_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>

          {/* Service */}
          <div className="flex-1 min-w-[170px]">
            <label className="filter-label">Service</label>
            <select value={service} onChange={e => setService(e.target.value)} className="filter-select">
              {SERVICES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>

          {/* Category */}
          <div className="flex-1 min-w-[160px]">
            <label className="filter-label">Category</label>
            <select value={category} onChange={e => setCategory(e.target.value)} className="filter-select">
              {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>

        </div>

        {/* Row 2 — Rules */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <label className="filter-label mb-0">
              Rules
              <span className="text-gray-700 font-normal ml-1">
                — {selected.size} of {visibleRules.length} selected
              </span>
            </label>
            <button
              onClick={toggleAll}
              className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors"
            >
              {allSelected ? 'Clear all' : 'Select all'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5 max-h-56 overflow-y-auto pr-1">
            {visibleRules.map(([name, info]) => (
              <label
                key={name}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors select-none ${
                  selected.has(name)
                    ? 'bg-blue-600/10 border-blue-600/40'
                    : 'bg-gray-950 border-gray-800 hover:border-gray-700'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(name)}
                  onChange={() => toggleRule(name)}
                  className="w-3.5 h-3.5 accent-blue-500 shrink-0"
                />
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${SEV_BADGE[info.severity]}`}>
                  {info.severity}
                </span>
                <span className="text-xs text-gray-300 truncate" title={name}>{info.label}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Row 3 — Run button */}
        <div className="mt-4 flex items-center justify-between">
          <span className="text-[11px] text-gray-600">
            {authType === 'iam-role' ? 'Executing via Lambda + IAM Role' : 'Executing locally via credentials'}
            {account && ` · ${account.account_id} · ${region}`}
          </span>
          <button
            onClick={handleRun}
            disabled={running || selected.size === 0}
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {running ? (
              <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Running…</>
            ) : (
              <><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/></svg> Run Scan ({selected.size})</>
            )}
          </button>
        </div>

      </div>

      {/* ── Error ─────────────────────────────────────────── */}
      {runError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
          <p className="text-sm text-red-400 font-medium">Scan failed</p>
          <p className="text-xs text-red-400/70 mt-1">{runError}</p>
        </div>
      )}

      {/* ── Report ────────────────────────────────────────── */}
      {report && <ReportTable report={report} region={region} authType={authType} />}

      {/* ── Empty state ───────────────────────────────────── */}
      {!report && !running && (
        <div className="text-center py-24">
          <svg className="w-16 h-16 text-gray-800 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <p className="text-gray-600 text-sm">Select rules above and click <span className="text-blue-400 font-medium">Run Scan</span></p>
        </div>
      )}

    </div>
  )
}
