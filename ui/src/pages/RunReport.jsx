import { useState, useEffect, useMemo } from 'react'
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
  CRITICAL: 'bg-red-500/20 text-red-400',
  HIGH:     'bg-orange-500/20 text-orange-400',
  WARNING:  'bg-amber-500/20 text-amber-400',
  MEDIUM:   'bg-yellow-500/20 text-yellow-400',
  COST:     'bg-violet-500/20 text-violet-400',
  LOW:      'bg-blue-500/20 text-blue-400',
  INFO:     'bg-gray-500/20 text-gray-400',
}

const CAT_BADGE = {
  security: 'bg-orange-500/15 text-orange-400 border border-orange-500/20',
  cost:     'bg-violet-500/15 text-violet-400 border border-violet-500/20',
}

export default function ScanRemediate() {
  // ── filters ──────────────────────────────────────────────
  const [region,   setRegion]   = useState('ap-south-1')
  const [authType, setAuthType] = useState('access-key')
  const [service,  setService]  = useState('all')
  const [category, setCategory] = useState('all')
  const [dryrun,   setDryrun]   = useState(true)

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
    // always add user-defined bucket if any saved rules exist
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

  // reset selections when filters change
  useEffect(() => { setSelected(new Set()) }, [service, category])

  // ── select-all toggle ─────────────────────────────────────
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

  // ── run ───────────────────────────────────────────────────
  async function handleRun() {
    if (selected.size === 0) return
    setRunning(true)
    setReport(null)
    setExtraPolicyInfo(null)
    setRunError(null)

    const allSelected     = Array.from(selected)
    const userRuleMap     = Object.fromEntries(userRules.map(r => [r.name, r]))
    const predefinedNames = allSelected.filter(n => !userRuleMap[n])
    const userDefinedNames= allSelected.filter(n =>  userRuleMap[n])

    try {
      let allResults  = []
      let accountInfo = null
      const injected  = {}   // extraPolicyInfo for user rules

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
        // prefer account from /build response, then from the initial listPolicies call
        if (!accountInfo) accountInfo = res.account || policyData?.account || { account_id: '—', region }
        // inject display metadata so ReportTable renders correctly
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
      saveToHistory(allSelected.join(', '), merged)
    } catch (e) {
      setRunError(e.message)
    }
    setRunning(false)
  }

  const account = policyData?.account

  return (
    <div className="p-6 space-y-5">

      {/* ── Filter bar ─────────────────────────────────────── */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">

        {/* Row 1 — dropdowns */}
        <div className="flex gap-3 flex-wrap">

          {/* Account */}
          <div className="flex-1 min-w-[160px]">
            <label className="filter-label">Account</label>
            <div className="filter-display">
              {account
                ? <span className="text-gray-200 font-mono text-xs">{account.account_id}</span>
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

          {/* Category — dynamic */}
          <div className="flex-1 min-w-[160px]">
            <label className="filter-label">Category</label>
            <select value={category} onChange={e => setCategory(e.target.value)} className="filter-select">
              {categories.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
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
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${SEV_BADGE[info.severity] || SEV_BADGE.INFO}`}>
                  {info.severity}
                </span>
                <span className="text-xs text-gray-300 truncate flex-1" title={name}>{info.label}</span>
                {info.isUserDefined && (
                  <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/20 shrink-0">
                    MY
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>

        {/* Row 3 — Dry-run toggle + Run button */}
        <div className="mt-4 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-4">
            <span className="text-[11px] text-gray-600">
              {authType === 'iam-role' ? 'Via Lambda + IAM Role' : 'Via local credentials'}
              {account && ` · ${account.account_id} · ${region}`}
            </span>
            {/* Dry-run toggle */}
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <div
                onClick={() => setDryrun(d => !d)}
                className={`relative w-8 h-4 rounded-full transition-colors ${dryrun ? 'bg-emerald-600' : 'bg-red-600'}`}
              >
                <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${dryrun ? 'left-0.5' : 'left-4'}`} />
              </div>
              <span className={`text-[11px] font-medium ${dryrun ? 'text-emerald-400' : 'text-red-400'}`}>
                {dryrun ? 'Dry Run (safe)' : 'Live — changes AWS'}
              </span>
            </label>
          </div>

          <button
            onClick={handleRun}
            disabled={running || selected.size === 0}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${
              dryrun ? 'bg-blue-600 hover:bg-blue-500' : 'bg-red-600 hover:bg-red-500'
            }`}
          >
            {running ? (
              <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Running…</>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                </svg>
                {dryrun ? `Run Scan (${selected.size})` : `⚠ Run Live (${selected.size})`}
              </>
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
          <svg className="w-16 h-16 text-gray-800 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <p className="text-gray-600 text-sm">Select rules above and click <span className="text-blue-400 font-medium">Run Scan</span></p>
        </div>
      )}

    </div>
  )
}
