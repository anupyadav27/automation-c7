import { useState } from 'react'
import StatusBadge from './StatusBadge'
import ResultModal from './ResultModal'
import { runPolicy } from '../api'
import { saveToHistory } from '../pages/RunHistory'

export default function GroupRunner({ groupName, files }) {
  const [status, setStatus] = useState('idle')
  const [result, setResult] = useState(null)
  const [showModal, setShowModal] = useState(false)

  async function handleRun(dryrun) {
    setStatus('running')
    try {
      const data = await runPolicy(groupName, dryrun)
      setStatus(dryrun ? 'dryrun' : 'success')
      setResult(data)
      saveToHistory(groupName, data)
    } catch (err) {
      setStatus('error')
      setResult({ error: err.message })
    }
  }

  const fileList = Array.isArray(files) ? files : [files]

  return (
    <>
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900/50 rounded-xl border border-gray-800 hover:border-gray-700 transition-colors">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-sm font-bold text-blue-400 font-mono whitespace-nowrap">{groupName}</span>
          <StatusBadge status={status} />
          <span className="text-xs text-gray-600 truncate hidden sm:inline">
            {fileList.join(', ')}
          </span>
        </div>
        <div className="flex items-center gap-2 ml-3">
          <button
            onClick={() => handleRun(true)}
            disabled={status === 'running'}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 disabled:opacity-50 whitespace-nowrap"
          >
            Dry Run All
          </button>
          <button
            onClick={() => handleRun(false)}
            disabled={status === 'running'}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 whitespace-nowrap"
          >
            Run All Live
          </button>
          {result && (
            <button
              onClick={() => setShowModal(true)}
              className="px-2 py-1.5 text-xs rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 border border-gray-700"
            >
              View
            </button>
          )}
        </div>
      </div>

      {showModal && (
        <ResultModal name={groupName} result={result} onClose={() => setShowModal(false)} />
      )}
    </>
  )
}
