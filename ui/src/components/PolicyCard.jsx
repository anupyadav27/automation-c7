import { useState } from 'react'
import StatusBadge from './StatusBadge'
import ResultModal from './ResultModal'
import { runPolicy } from '../api'
import { saveToHistory } from '../pages/RunHistory'

const categoryColors = {
  s3: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', label: 'S3' },
  ec2: { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-400', label: 'EC2' },
  ebs: { bg: 'bg-purple-500/10', border: 'border-purple-500/30', text: 'text-purple-400', label: 'EBS' },
  eni: { bg: 'bg-teal-500/10', border: 'border-teal-500/30', text: 'text-teal-400', label: 'ENI' },
  ami: { bg: 'bg-pink-500/10', border: 'border-pink-500/30', text: 'text-pink-400', label: 'AMI' },
  sg: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', label: 'SG' },
  eip: { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', label: 'EIP' },
}

function getCategory(name) {
  if (name.startsWith('sg-')) return categoryColors.sg
  if (name.startsWith('eip-')) return categoryColors.eip
  if (name.startsWith('eni-')) return categoryColors.eni
  if (name.startsWith('ebs-')) return categoryColors.ebs
  if (name.startsWith('ec2-')) return categoryColors.ec2
  if (name.startsWith('ami-')) return categoryColors.ami
  if (name.startsWith('s3-')) return categoryColors.s3
  return { bg: 'bg-gray-500/10', border: 'border-gray-500/30', text: 'text-gray-400', label: '?' }
}

export default function PolicyCard({ name, file, description, onResult }) {
  const [status, setStatus] = useState('idle')
  const [result, setResult] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [lastCount, setLastCount] = useState(null)
  const cat = getCategory(name)

  async function handleRun(dryrun) {
    setStatus('running')
    setResult(null)
    setLastCount(null)
    try {
      const data = await runPolicy(name, dryrun)
      const r = data.results?.[0]
      const count = r?.resources_found ? Object.values(r.resources_found).reduce((a, b) => a + (b > 0 ? b : 0), 0) : 0
      setStatus(dryrun ? 'dryrun' : r?.status || 'success')
      setResult(data)
      setLastCount(count)
      saveToHistory(name, data)
      if (onResult) onResult(data)
    } catch (err) {
      setStatus('error')
      setResult({ error: err.message })
    }
  }

  // Truncate description for card display
  const desc = typeof description === 'string' ? description : (typeof file === 'object' ? file.description : '')
  const shortDesc = desc ? (desc.length > 90 ? desc.slice(0, 90) + '...' : desc) : null

  return (
    <>
      <div className={`rounded-xl border ${cat.border} ${cat.bg} p-4 flex flex-col gap-3 hover:border-opacity-60 transition-all`}>
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-[10px] font-bold uppercase tracking-wider ${cat.text}`}>
                {cat.label}
              </span>
              <StatusBadge status={status} />
              {lastCount !== null && lastCount > 0 && (
                <span className="text-[10px] font-bold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                  {lastCount} found
                </span>
              )}
              {lastCount === 0 && status !== 'idle' && status !== 'running' && (
                <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                  Clean
                </span>
              )}
            </div>
            <h3 className="text-sm font-semibold text-gray-200 truncate" title={name}>
              {name}
            </h3>
            {shortDesc && (
              <p className="text-[11px] text-gray-500 mt-1 line-clamp-2 leading-relaxed" title={desc}>
                {shortDesc}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 mt-auto">
          <button
            onClick={() => handleRun(true)}
            disabled={status === 'running'}
            className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 transition-colors disabled:opacity-50"
          >
            {status === 'running' ? 'Running...' : 'Dry Run'}
          </button>
          <button
            onClick={() => handleRun(false)}
            disabled={status === 'running'}
            className="flex-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
          >
            Run Live
          </button>
          {result && (
            <button
              onClick={() => setShowModal(true)}
              className="px-2 py-1.5 text-xs rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 border border-gray-700"
              title="View results"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {showModal && (
        <ResultModal
          name={name}
          result={result}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  )
}
