const LAMBDA_EP_KEY = 'c7n_lambda_endpoint'
const LOCAL_EP_KEY  = 'c7n_local_endpoint'

const DEFAULT_LAMBDA = import.meta.env.VITE_API_ENDPOINT || 'https://vgs6w2yd2d.execute-api.ap-south-1.amazonaws.com'
const DEFAULT_LOCAL  = 'http://localhost:8082'

export function getEndpoint(authType) {
  if (authType === 'iam-role') {
    return localStorage.getItem(LAMBDA_EP_KEY) || DEFAULT_LAMBDA
  }
  return localStorage.getItem(LOCAL_EP_KEY) || DEFAULT_LOCAL
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  const data = await res.json()
  return typeof data === 'string' ? JSON.parse(data) : data
}

export async function listPolicies(authType = 'access-key') {
  return post(`${getEndpoint(authType)}/run`, { policy: 'list' })
}

// Run one or more policies by name array
export async function runPolicies(policyNames, { dryrun = true, region = null, authType = 'access-key' } = {}) {
  return post(`${getEndpoint(authType)}/run`, {
    policies: policyNames,
    dryrun: dryrun ? 'true' : 'false',
    ...(region ? { region } : {}),
  })
}

// Run a c7n action on specific resource IDs
export async function runAction(policyName, resourceIds, actionType, { region = null, authType = 'access-key' } = {}) {
  return post(`${getEndpoint(authType)}/action`, {
    policy: policyName,
    resource_ids: resourceIds,
    action: actionType,
    ...(region ? { region } : {}),
  })
}

// Run a dynamically-built policy spec (from the Policy Builder page)
// spec = { resource, name?, description?, filters: [...], actions: [...], id_field? }
export async function runBuild(spec, { dryrun = true, region = null, authType = 'access-key' } = {}) {
  return post(`${getEndpoint(authType)}/build`, {
    spec,
    dryrun: dryrun ? 'true' : 'false',
    ...(region ? { region } : {}),
  })
}

// Legacy single-policy call (kept for History page compatibility)
export async function runPolicy(policyName, dryrun = true, authType = 'access-key') {
  return runPolicies([policyName], { dryrun, authType })
}
