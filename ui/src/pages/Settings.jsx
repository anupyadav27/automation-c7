import { useState } from 'react'

const LAMBDA_EP_KEY = 'c7n_lambda_endpoint'
const LOCAL_EP_KEY  = 'c7n_local_endpoint'

const DEFAULT_LAMBDA = import.meta.env.VITE_API_ENDPOINT || 'https://vgs6w2yd2d.execute-api.ap-south-1.amazonaws.com'
const DEFAULT_LOCAL  = 'http://localhost:8081'

export default function Settings() {
  const [lambdaEp, setLambdaEp] = useState(
    () => localStorage.getItem(LAMBDA_EP_KEY) || DEFAULT_LAMBDA
  )
  const [localEp, setLocalEp] = useState(
    () => localStorage.getItem(LOCAL_EP_KEY) || DEFAULT_LOCAL
  )
  const [saved, setSaved] = useState(false)
  const [testTarget, setTestTarget] = useState(null)  // 'lambda' | 'local'
  const [testStatus, setTestStatus] = useState(null)
  const [testError, setTestError]   = useState(null)

  function handleSave() {
    localStorage.setItem(LAMBDA_EP_KEY, lambdaEp)
    localStorage.setItem(LOCAL_EP_KEY,  localEp)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  async function handleTest(endpoint, target) {
    setTestTarget(target)
    setTestStatus('testing')
    setTestError(null)
    try {
      const res = await fetch(`${endpoint}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy: 'list' }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const parsed = typeof data === 'string' ? JSON.parse(data) : data
      if (parsed.individual_policies || parsed.groups) {
        setTestStatus('success')
      } else {
        throw new Error('Unexpected response format')
      }
    } catch (e) {
      setTestStatus('error')
      setTestError(e.message)
    }
  }

  return (
    <div className="p-8 max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-100 mb-6">Settings</h1>

      {/* Lambda / IAM Role endpoint */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-1">Lambda Endpoint</h2>
        <p className="text-[11px] text-gray-500 mb-4">
          Used when Auth Type is <span className="text-gray-400 font-medium">IAM Role (Lambda)</span>
        </p>
        <div className="space-y-3">
          <input
            type="text"
            value={lambdaEp}
            onChange={(e) => setLambdaEp(e.target.value)}
            placeholder="https://xxx.execute-api.region.amazonaws.com"
            className="w-full px-4 py-2.5 text-sm bg-gray-950 border border-gray-700 rounded-lg text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => handleTest(lambdaEp, 'lambda')}
              disabled={testStatus === 'testing' && testTarget === 'lambda'}
              className="px-4 py-2 text-sm font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 disabled:opacity-50"
            >
              {testStatus === 'testing' && testTarget === 'lambda' ? 'Testing…' : 'Test'}
            </button>
            {testTarget === 'lambda' && testStatus === 'success' && (
              <span className="text-sm text-emerald-400">Connected</span>
            )}
            {testTarget === 'lambda' && testStatus === 'error' && (
              <span className="text-sm text-red-400 truncate">{testError}</span>
            )}
          </div>
        </div>
      </div>

      {/* Local / Access Key endpoint */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-1">Local Server Endpoint</h2>
        <p className="text-[11px] text-gray-500 mb-4">
          Used when Auth Type is <span className="text-gray-400 font-medium">Access Key</span> or <span className="text-gray-400 font-medium">AWS Profile</span>
        </p>
        <div className="space-y-3">
          <input
            type="text"
            value={localEp}
            onChange={(e) => setLocalEp(e.target.value)}
            placeholder="http://localhost:8081"
            className="w-full px-4 py-2.5 text-sm bg-gray-950 border border-gray-700 rounded-lg text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => handleTest(localEp, 'local')}
              disabled={testStatus === 'testing' && testTarget === 'local'}
              className="px-4 py-2 text-sm font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 disabled:opacity-50"
            >
              {testStatus === 'testing' && testTarget === 'local' ? 'Testing…' : 'Test'}
            </button>
            {testTarget === 'local' && testStatus === 'success' && (
              <span className="text-sm text-emerald-400">Connected</span>
            )}
            {testTarget === 'local' && testStatus === 'error' && (
              <span className="text-sm text-red-400 truncate">{testError}</span>
            )}
          </div>
        </div>
      </div>

      {/* Save */}
      <div className="mb-6">
        <button
          onClick={handleSave}
          className="px-5 py-2 text-sm font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white"
        >
          {saved ? 'Saved!' : 'Save Settings'}
        </button>
      </div>

      {/* Info */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">Effective Endpoints</h2>
        <div className="space-y-2.5">
          <InfoRow label="Lambda (IAM Role)"     value={lambdaEp} />
          <InfoRow label="Local (Access Key)"    value={localEp} />
          <InfoRow label="VITE_API_ENDPOINT"     value={import.meta.env.VITE_API_ENDPOINT || '(not set)'} />
        </div>
      </div>

      {/* Quick reference */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h2 className="text-sm font-semibold text-gray-200 mb-3">Quick Reference</h2>
        <pre className="text-xs text-gray-400 bg-gray-950 rounded-lg p-4 overflow-x-auto">{`# Start local server (Access Key / Profile mode)
python local-server.py

# UI in Docker
docker build -t c7n-ui ./ui
docker run -p 3000:80 \\
  -e VITE_API_ENDPOINT=https://xxx.execute-api.region.amazonaws.com \\
  c7n-ui`}</pre>
      </div>
    </div>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4 min-w-0">
      <span className="text-xs text-gray-500 font-mono shrink-0">{label}</span>
      <span className="text-xs text-gray-400 font-mono truncate">{value}</span>
    </div>
  )
}
