export function saveToHistory(policyName, data) {
  const entry = {
    policy: policyName,
    timestamp: new Date().toLocaleString(),
    data,
  }
  try {
    const prev = JSON.parse(localStorage.getItem('c7n_history') || '[]')
    const next = [entry, ...prev].slice(0, 100)
    localStorage.setItem('c7n_history', JSON.stringify(next))
  } catch {}
}
