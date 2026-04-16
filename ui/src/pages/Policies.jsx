import { useState, useEffect, useMemo } from 'react'
import { listPolicies } from '../api'
import PolicyCard from '../components/PolicyCard'

const CATEGORY_ORDER = ['s3', 'ec2', 'sg', 'ebs', 'eni', 'eip', 'ami']

function getCategory(name) {
  if (name.startsWith('sg-')) return 'sg'
  if (name.startsWith('eip-')) return 'eip'
  for (const c of CATEGORY_ORDER) {
    if (name.startsWith(c + '-')) return c
  }
  return 'other'
}

const CATEGORY_LABELS = {
  s3: 'S3 Storage',
  ec2: 'EC2 Instances',
  sg: 'Security Groups',
  ebs: 'EBS Volumes & Snapshots',
  eni: 'Network Interfaces',
  eip: 'Elastic IPs',
  ami: 'AMI Images',
  other: 'Other',
}

export default function Policies() {
  const [policyData, setPolicyData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterCat, setFilterCat] = useState('all')

  useEffect(() => {
    listPolicies()
      .then(setPolicyData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const allPolicies = policyData?.individual_policies || {}

  const grouped = useMemo(() => {
    const groups = {}
    for (const [name, entry] of Object.entries(allPolicies)) {
      const file = typeof entry === 'string' ? entry : entry?.file || ''
      const description = typeof entry === 'object' ? entry?.description || '' : ''
      if (search && !name.toLowerCase().includes(search.toLowerCase()) && !description.toLowerCase().includes(search.toLowerCase())) continue
      const cat = getCategory(name)
      if (filterCat !== 'all' && cat !== filterCat) continue
      if (!groups[cat]) groups[cat] = []
      groups[cat].push({ name, file, description })
    }
    return groups
  }, [allPolicies, search, filterCat])

  const visibleCount = Object.values(grouped).reduce((a, b) => a + b.length, 0)
  const totalPolicies = Object.keys(allPolicies).length
  const categories = [...new Set(Object.keys(allPolicies).map(getCategory))]

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">All Policies</h1>
        <p className="text-sm text-gray-500 mt-1">
          Run individual policies with dry run or live mode
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-md">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search policies..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 text-sm bg-gray-900 border border-gray-700 rounded-lg text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setFilterCat('all')}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              filterCat === 'all'
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
            }`}
          >
            All ({totalPolicies})
          </button>
          {CATEGORY_ORDER.filter(c => categories.includes(c)).map(cat => (
            <button
              key={cat}
              onClick={() => setFilterCat(cat)}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-colors uppercase ${
                filterCat === cat
                  ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                  : 'bg-gray-900 border-gray-700 text-gray-500 hover:text-gray-300'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-gray-600 mb-4">
        Showing {visibleCount} of {totalPolicies} policies
      </p>

      {/* Policy grid grouped by category */}
      {CATEGORY_ORDER.filter(c => grouped[c]?.length > 0).map(cat => (
        <div key={cat} className="mb-8">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            {CATEGORY_LABELS[cat] || cat} ({grouped[cat].length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {grouped[cat].map(({ name, file, description }) => (
              <PolicyCard key={name} name={name} file={file} description={description} />
            ))}
          </div>
        </div>
      ))}

      {visibleCount === 0 && (
        <div className="text-center py-16 text-gray-600">
          No policies match your search.
        </div>
      )}
    </div>
  )
}
