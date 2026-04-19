const KEY = 'c7n_user_rules'

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

export function getUserRules() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]') }
  catch { return [] }
}

export function saveUserRule(rule) {
  const rules = getUserRules()
  const now   = new Date().toISOString()
  if (rule.id) {
    const idx = rules.findIndex(r => r.id === rule.id)
    if (idx >= 0) {
      rules[idx] = { ...rule, updatedAt: now }
      localStorage.setItem(KEY, JSON.stringify(rules))
      return rules[idx]
    }
  }
  const created = { ...rule, id: uid(), createdAt: now, updatedAt: now }
  localStorage.setItem(KEY, JSON.stringify([...rules, created]))
  return created
}

export function deleteUserRule(id) {
  localStorage.setItem(KEY, JSON.stringify(getUserRules().filter(r => r.id !== id)))
}

// Returns custom category names (excludes built-ins: security, cost)
export function getUserCategories() {
  const builtIn = new Set(['security', 'cost'])
  const seen    = new Set()
  return getUserRules()
    .map(r => r.category)
    .filter(c => c && !builtIn.has(c) && !seen.has(c) && seen.add(c))
}
