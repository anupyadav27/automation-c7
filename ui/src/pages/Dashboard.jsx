import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { listPolicies, runPolicy } from '../api'
import StatusBadge from '../components/StatusBadge'
import ResultModal from '../components/ResultModal'
import { saveToHistory } from './RunHistory'

const CATEGORY_META = {
  's3-lifecycle':  { label: 'S3 Lifecycle',   icon: BucketIcon, color: 'orange' },
  's3-security':   { label: 'S3 Security',    icon: ShieldIcon, color: 'red' },
  's3-cost':       { label: 'S3 Cost',        icon: DollarIcon, color: 'amber' },
  'ec2':           { label: 'EC2 Instances',   icon: ServerIcon, color: 'blue' },
  'ec2-security':  { label: 'EC2 Security',   icon: ShieldIcon, color: 'red' },
  'ebs':           { label: 'EBS Volumes',     icon: DiskIcon,   color: 'purple' },
  'ebs-optimize':  { label: 'EBS Optimize',   icon: DollarIcon, color: 'violet' },
  'eni':           { label: 'ENI / EIP',       icon: NetworkIcon, color: 'teal' },
  'ami':           { label: 'AMI Cleanup',     icon: ImageIcon,  color: 'pink' },
}

const colorMap = {
  orange: { card: 'from-orange-500/10 to-orange-500/5', border: 'border-orange-500/20', text: 'text-orange-400', badge: 'bg-orange-500/15' },
  red:    { card: 'from-red-500/10 to-red-500/5', border: 'border-red-500/20', text: 'text-red-400', badge: 'bg-red-500/15' },
  amber:  { card: 'from-amber-500/10 to-amber-500/5', border: 'border-amber-500/20', text: 'text-amber-400', badge: 'bg-amber-500/15' },
  blue:   { card: 'from-blue-500/10 to-blue-500/5', border: 'border-blue-500/20', text: 'text-blue-400', badge: 'bg-blue-500/15' },
  purple: { card: 'from-purple-500/10 to-purple-500/5', border: 'border-purple-500/20', text: 'text-purple-400', badge: 'bg-purple-500/15' },
  violet: { card: 'from-violet-500/10 to-violet-500/5', border: 'border-violet-500/20', text: 'text-violet-400', badge: 'bg-violet-500/15' },
  teal:   { card: 'from-teal-500/10 to-teal-500/5', border: 'border-teal-500/20', text: 'text-teal-400', badge: 'bg-teal-500/15' },
  pink:   { card: 'from-pink-500/10 to-pink-500/5', border: 'border-pink-500/20', text: 'text-pink-400', badge: 'bg-pink-500/15' },
}

export default function Dashboard() {
  const [policyData, setPolicyData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [runningGroup, setRunningGroup] = useState(null)
  const [groupResult, setGroupResult] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    listPolicies()
      .then(setPolicyData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  async function handleGroupRun(group, dryrun) {
    setRunningGroup(group)
    setGroupResult(null)
    try {
      const data = await runPolicy(group, dryrun)
      setGroupResult({ group, data })
      saveToHistory(group, data)
      setShowModal(true)
    } catch (e) {
      setGroupResult({ group, data: { error: e.message } })
      saveToHistory(group, { error: e.message })
      setShowModal(true)
    }
    setRunningGroup(null)
  }

  if (loading) return <LoadingScreen />
  if (error) return <ErrorScreen error={error} />

  const groups = policyData?.groups || {}
  const allPolicies = policyData?.individual_policies || {}
  const totalCount = Object.keys(allPolicies).length

  // Count per group
  const groupCounts = {}
  for (const [groupName, files] of Object.entries(groups)) {
    const fileList = Array.isArray(files) ? files : [files]
    let count = 0
    for (const [pName, entry] of Object.entries(allPolicies)) {
      const pFile = typeof entry === 'string' ? entry : entry?.file || ''
      if (fileList.includes(pFile)) count++
    }
    groupCounts[groupName] = count
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-100">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">
          {totalCount} policies across {Object.keys(groups).length} groups
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Policies" value={totalCount} color="text-blue-400" />
        <StatCard label="S3 Policies" value={countByPrefix(allPolicies, 's3-')} color="text-orange-400" />
        <StatCard label="EC2/EBS/ENI" value={countByPrefix(allPolicies, 'ec2-') + countByPrefix(allPolicies, 'ebs-') + countByPrefix(allPolicies, 'eni-') + countByPrefix(allPolicies, 'sg-') + countByPrefix(allPolicies, 'eip-')} color="text-blue-400" />
        <StatCard label="AMI" value={countByPrefix(allPolicies, 'ami-')} color="text-pink-400" />
      </div>

      {/* Quick run all */}
      <div className="flex items-center gap-3 mb-8 p-4 rounded-xl bg-gradient-to-r from-blue-500/10 to-purple-500/10 border border-blue-500/20">
        <div className="flex-1">
          <h2 className="text-sm font-semibold text-gray-200">Run All Policies</h2>
          <p className="text-xs text-gray-500">Execute all 56 policies in one go</p>
        </div>
        <button
          onClick={() => handleGroupRun('all', true)}
          disabled={runningGroup === 'all'}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 disabled:opacity-50"
        >
          {runningGroup === 'all' ? 'Running...' : 'Dry Run All'}
        </button>
        <button
          onClick={() => handleGroupRun('all', false)}
          disabled={runningGroup === 'all'}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
        >
          Run All Live
        </button>
      </div>

      {/* Group cards */}
      <h2 className="text-lg font-semibold text-gray-200 mb-4">Policy Groups</h2>
      <div className="grid grid-cols-3 gap-4">
        {Object.entries(groups).filter(([g]) => g !== 's3').map(([group, files]) => {
          const meta = CATEGORY_META[group] || { label: group, icon: ServerIcon, color: 'blue' }
          const colors = colorMap[meta.color]
          const Icon = meta.icon
          const count = groupCounts[group] || 0

          return (
            <div
              key={group}
              className={`rounded-xl border ${colors.border} bg-gradient-to-br ${colors.card} p-5 flex flex-col gap-4`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${colors.badge}`}>
                    <Icon className={`w-5 h-5 ${colors.text}`} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-200">{meta.label}</h3>
                    <p className="text-xs text-gray-500">{count} policies</p>
                  </div>
                </div>
                {runningGroup === group && <StatusBadge status="running" />}
              </div>

              <div className="flex gap-2 mt-auto">
                <button
                  onClick={() => handleGroupRun(group, true)}
                  disabled={!!runningGroup}
                  className="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-gray-800/80 hover:bg-gray-700 text-gray-300 border border-gray-700 disabled:opacity-50"
                >
                  Dry Run
                </button>
                <button
                  onClick={() => handleGroupRun(group, false)}
                  disabled={!!runningGroup}
                  className="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
                >
                  Run Live
                </button>
                <button
                  onClick={() => navigate('/policies')}
                  className="px-3 py-2 text-xs rounded-lg bg-gray-800/80 hover:bg-gray-700 text-gray-400 border border-gray-700"
                  title="View individual policies"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {showModal && groupResult && (
        <ResultModal
          name={groupResult.group}
          result={groupResult.data}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}

function countByPrefix(policies, prefix) {
  return Object.keys(policies).filter(n => n.startsWith(prefix)).length
}

function StatCard({ label, value, color }) {
  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  )
}

function LoadingScreen() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
        <p className="text-sm text-gray-500 mt-3">Loading policies from API...</p>
      </div>
    </div>
  )
}

function ErrorScreen({ error }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md">
        <div className="w-12 h-12 rounded-full bg-red-500/15 flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-gray-200">Cannot connect to API</h2>
        <p className="text-sm text-gray-500 mt-2">{error}</p>
        <p className="text-xs text-gray-600 mt-3">
          Check that VITE_API_ENDPOINT is set correctly in .env or that the API is running.
        </p>
      </div>
    </div>
  )
}

// --- SVG Icons ---
function BucketIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" /></svg>
}
function ServerIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" /></svg>
}
function ShieldIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
}
function DollarIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
}
function DiskIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" /></svg>
}
function NetworkIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.14 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0" /></svg>
}
function ImageIcon({ className }) {
  return <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
}
