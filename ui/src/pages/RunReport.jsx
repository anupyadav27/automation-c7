import { useState, useEffect, useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { listPolicies, runPolicies, runBuild } from '../api'
import { POLICY_INFO, SEV_ORDER } from '../lib/policyInfo'
import { saveToHistory } from '../lib/history'
import { getUserRules, getUserCategories } from '../lib/userRules'
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
  { value: 'all',            label: 'All Services' },
  { value: 'ec2',            label: 'EC2 / Security Groups' },
  { value: 's3',             label: 'S3 Buckets' },
  { value: 'ebs',            label: 'EBS Volumes' },
  { value: 'eni',            label: 'ENI / Elastic IP' },
  { value: 'ami',            label: 'AMI Images' },
  { value: 'rds',            label: 'RDS Databases' },
  { value: 'iam',            label: 'IAM' },
  { value: 'lambda',         label: 'Lambda' },
  { value: 'cloudtrail',     label: 'CloudTrail' },
  { value: 'vpc',            label: 'VPC / Networking' },
  { value: 'secretsmanager', label: 'Secrets Manager' },
]

const SEV_BADGE = {
  CRITICAL: 'bg-red-100 text-red-700 border border-red-200',
  HIGH:     'bg-orange-100 text-orange-700 border border-orange-200',
  WARNING:  'bg-amber-100 text-amber-700 border border-amber-200',
  MEDIUM:   'bg-yellow-100 text-yellow-700 border border-yellow-200',
  COST:     'bg-violet-100 text-violet-700 border border-violet-200',
  LOW:      'bg-blue-100 text-blue-700 border border-blue-200',
  INFO:     'bg-gray-100 text-gray-600 border border-gray-200',
}

const CAT_BADGE = {
  security: 'bg-orange-50 text-orange-600 border border-orange-200',
  cost:     'bg-violet-50 text-violet-600 border border-violet-200',
}

const SCAN_PRESETS = [
  { id: 'security', label: 'Security Baseline', icon: '🔴' },
  { id: 'cost',     label: 'Cost Cleanup',       icon: '💰' },
  { id: 'full',     label: 'Full Audit',          icon: '📋' },
  { id: 'custom',   label: 'Custom',             icon: '⚙️' },
]

export default function ScanRemediate() {
  const location = useLocation()

  // ── filters ──────────────────────────────────────────────
  const [region,   setRegion]   = useState('ap-south-1')
  const [authType, setAuthType] = useState('access-key')
  const [service,  setService]  = useState('all')
  const [category, setCategory] = useState('all')
  const [dryrun,   setDryrun]   = useState(true)

  // ── preset state ─────────────────────────────────────────
  const [preset,        setPreset]        = useState('security')
  const [showCustomize, setShowCustomize] = useState(false)

  // ── API data ──────────────────────────────────────────────
  const [policyData, setPolicyData] = useState(null)
  const [loadError,  setLoadError]  = useState(null)

  // ── user-defined rules (from localStorage) ────────────────
  const [userRules, setUserRules] = useState([])

  useEffect(() => { setUserRules(getUserRules()) }, [])

  // ── rules selection ───────────────────────────────────────
  const [selected, setSelected] = useState(new Set())

  // ── run state ─────────────────────────────────────────────
  const [running,         setRunning]         = useState(false)
  const [report,          setReport]          = useState(null)
  const [extraPolicyInfo, setExtraPolicyInfo] = useState(null)
  const [runError,        setRunError]        = useState(null)

  // ── load policy list whenever auth type changes ───────────
  useEffect(() => {
    setPolicyData(null)
    setLoadError(null)
    listPolicies(authType)
      .then(d => setPolicyData(d))
      .catch(e => setLoadError(e.message))
  }, [authType])

  // ── dynamic categories — built-ins + any user-defined ones ─
  const categories = useMemo(() => {
    const base = [
      { value: 'all',      label: 'All Categories' },
      { value: 'security', label: 'Security' },
      { value: 'cost',     label: 'Cost Optimisation' },
    ]
    const custom = getUserCategories()
    custom.forEach(c => base.push({ value: c, label: c.charAt(0).toUpperCase() + c.slice(1) }))
    if (userRules.length > 0)
      base.push({ value: 'user-defined', label: 'User Defined' })
    return base
  }, [userRules])

  // ── merge built-in + user rules into one flat list ─────────
  const allRules = useMemo(() => {
    const builtin = Object.entries(POLICY_INFO)
    const user    = userRules.map(r => [
      r.name,
      {
        service:      r.service      || 'other',
        resourceType: r.resourceType || r.name,
        category:     r.category     || 'user-defined',
        severity:     r.severity     || 'INFO',
        label:        r.label        || r.name,
        isUserDefined: true,
      },
    ])
    return [...builtin, ...user]
  }, [userRules])

  // ── visible rules after service + category filter ──────────
  const visibleRules = useMemo(() => {
    return allRules
      .filter(([, info]) => service  === 'all' || info.service   === service)
      .filter(([, info]) => {
        if (category === 'all') return true
        if (category === 'user-defined') return info.isUserDefined
        return info.category === category
      })
      .sort(([, a], [, b]) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9))
  }, [allRules, service, category])

  // ── apply preset — auto-selects policies ──────────────────
  function applyPreset(id) {
    setPreset(id)
    if (id === 'custom') {
      setShowCustomize(true)
      return
    }
    const newSelected = new Set()
    allRules.forEach(([name, info]) => {
      if (id === 'full') {
        newSelected.add(name)
      } else if (id === 'security' && info.category === 'security') {
        newSelected.add(name)
      } else if (id === 'cost' && info.category === 'cost') {
        newSelected.add(name)
      }
    })
    setSelected(newSelected)
  }

  // ── handle incoming preset from Dashboard quick-start ─────
  useEffect(() => {
    const incomingPreset = location.state?.preset
    if (incomingPreset) {
      applyPreset(incomingPreset)
    } else {
      // Default: security preset
      applyPreset('security')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allRules.length]) // Run once allRules are populated

  // ── select-all toggle (for customize panel) ───────────────
  const allSelected = visibleRules.length > 0 && visibleRules.every(([n]) => selected.has(n))
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(visibleRules.map(([n]) => n)))
  }
  function toggleRule(name) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  // reset customize filters when preset changes
  useEffect(() => { setService('all'); setCategory('all') }, [preset])

  // ── run ───────────────────────────────────────────────────
  async function handleRun() {
    if (selected.size === 0) return
    setRunning(true)
    setReport(null)
    setExtraPolicyInfo(null)
    setRunError(null)

    const allSelectedArr  = Array.from(selected)
    const userRuleMap     = Object.fromEntries(userRules.map(r => [r.name, r]))
    const predefinedNames = allSelectedArr.filter(n => !userRuleMap[n])
    const userDefinedNames= allSelectedArr.filter(n =>  userRuleMap[n])

    try {
      let allResults  = []
      let accountInfo = null
      const injected  = {}

      // ── predefined policies via /run ─────────────────────
      if (predefinedNames.length > 0) {
        const data = await runPolicies(predefinedNames, { dryrun, region, authType })
        allResults  = [...allResults, ...(data.results || [])]
        accountInfo = data.account
      }

      // ── user-defined policies via /build (one at a time) ──
      for (const name of userDefinedNames) {
        const rule = userRuleMap[name]
        const res  = await runBuild(rule.spec, { dryrun, region, authType })
        allResults.push(res)
        if (!accountInfo) accountInfo = res.account || policyData?.account || { account_id: '—', region }
        injected[res.policy] = {
          service:      rule.service      || 'other',
          resourceType: rule.resourceType || rule.name,
          category:     rule.category     || 'user-defined',
          severity:     rule.severity     || 'INFO',
          label:        rule.label        || rule.name,
        }
      }

      const merged = { results: allResults, account: accountInfo, region, dryrun }
      setReport(merged)
      if (Object.keys(injected).length > 0) setExtraPolicyInfo(injected)
      saveToHistory(allSelectedArr.join(', '), merged)
    } catch (e) {
      setRunError(e.message)
    }
    setRunning(false)
  }

  const account = policyData?.account

  return (
    <div className="p-6 max-w-5xl space-y-5">

      {/* ── Config + Preset bar ────────────────────────────── */}
      <div className="card p-5">

        {/* Row 1 — dropdowns */}
        <div className="flex gap-3 flex-wrap mb-4">

          {/* Account */}
          <div className="flex-1 min-w-[140px]">
            <label className="filter-label">Account</label>
            <div className="filter-display">
              {account
                ? <span className="text-gray-700 font-mono text-xs">{account.account_id}</span>
                : loadError
                  ? <span className="text-red-500 text-xs">Cannot connect</span>
                  : <span className="text-gray-400 text-xs animate-pulse">Detecting…</span>
              }
            </div>
          </div>

          {/* Region */}
          <div className="flex-1 min-w-[180px]">
            <label className="filter-label">Region</label>
            <select value={region} onChange={e => setRegion(e.target.value)} className="filter-select">
              {REGIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>

          {/* Auth Type */}
          <div className="flex-1 min-w-[170px]">
            <label className="filter-label">Auth Type</label>
            <select value={authType} onChange={e => setAuthType(e.target.value)} className="filter-select">
              {AUTH_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>

          {/* Dry-run toggle */}
          <div className="flex-shrink-0 flex flex-col justify-end pb-0.5">
            <label className="filter-label">Mode</label>
            <label className="flex items-center gap-2 cursor-pointer select-none h-[38px]">
              <div
                onClick={() => setDryrun(d => !d)}
                className={`relative w-8 h-4 rounded-full transition-colors ${dryrun ? 'bg-emerald-500' : 'bg-red-500'}`}
              >
                <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${dryrun ? 'left-0.5' : 'left-4'}`} />
              </div>
              <span className={`text-sm font-medium ${dryrun ? 'text-emerald-700' : 'text-red-600'}`}>
                {dryrun ? 'Dry Run' : 'Live'}
              </span>
            </label>
          </div>
        </div>

        {/* Row 2 — Preset pills */}
        <div className="flex gap-2 flex-wrap mb-4">
          {SCAN_PRESETS.map(p => (
            <button
              key={p.id}
              onClick={() => applyPreset(p.id)}
              className={`px-4 py-2 rounded-full text-sm font-medium border transition-colors ${
                preset === p.id
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400 hover:text-blue-600'
              }`}
            >
              {p.icon} {p.label}
            </button>
          ))}
        </div>

        {/* Row 3 — Policy count + Customize + Run */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <span className="text-sm text-gray-500">
            {selected.size} {selected.size === 1 ? 'policy' : 'policies'} selected
            {account && ` · ${account.account_id} · ${region}`}
          </span>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => setShowCustomize(s => !s)}
              className="btn-secondary"
            >
              {showCustomize ? 'Hide Picker' : 'Customize ▾'}
            </button>
            <button
              onClick={handleRun}
              disabled={running || selected.size === 0}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${
                dryrun ? 'bg-blue-600 hover:bg-blue-700' : 'bg-red-600 hover:bg-red-700'
              }`}
            >
              {running ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Running…</>
              ) : (
                <>{dryrun ? `▶ Run Scan (${selected.size})` : `⚠ Run Live (${selected.size})`}</>
              )}
            </button>
          </div>
        </div>

        {/* Expandable policy picker */}
        {showCustomize && (
          <div className="mt-4 border-t border-gray-200 pt-4">
            {/* Service / Category filters */}
            <div className="flex gap-3 flex-wrap mb-3">
              <div className="flex-1 min-w-[160px]">
                <label className="filter-label">Service</label>
                <select value={service} onChange={e => setService(e.target.value)} className="filter-select">
                  {SERVICES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="filter-label">Category</label>
                <select value={category} onChange={e => setCategory(e.target.value)} className="filter-select">
                  {categories.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
              <div className="flex items-end pb-0.5">
                <button
                  onClick={toggleAll}
                  className="text-xs text-blue-600 hover:text-blue-700 font-medium whitespace-nowrap"
                >
                  {allSelected ? 'Clear all' : 'Select all'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5 max-h-60 overflow-y-auto pr-1">
              {visibleRules.map(([name, info]) => (
                <label
                  key={name}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors select-none ${
                    selected.has(name)
                      ? 'bg-blue-50 border-blue-300'
                      : 'bg-white border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(name)}
                    onChange={() => toggleRule(name)}
                    className="w-3.5 h-3.5 accent-blue-600 shrink-0"
                  />
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${SEV_BADGE[info.severity] || SEV_BADGE.INFO}`}>
                    {info.severity}
                  </span>
                  <span className="text-xs text-gray-700 truncate flex-1" title={name}>{info.label}</span>
                  {info.isUserDefined && (
                    <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-100 text-blue-700 border border-blue-200 shrink-0">
                      MY
                    </span>
                  )}
                </label>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* ── Error ─────────────────────────────────────────── */}
      {runError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-700 font-medium">Scan failed</p>
          <p className="text-xs text-red-500 mt-1">{runError}</p>
        </div>
      )}

      {/* ── Report ────────────────────────────────────────── */}
      {report && (
        <ReportTable
          report={report}
          region={region}
          authType={authType}
          extraPolicyInfo={extraPolicyInfo}
        />
      )}

      {/* ── Empty state ───────────────────────────────────── */}
      {!report && !running && (
        <div className="text-center py-24">
          <svg className="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <p className="text-gray-500 text-sm">
            Select a preset above and click <span className="text-blue-600 font-medium">Run Scan</span>
          </p>
        </div>
      )}

    </div>
  )
}
