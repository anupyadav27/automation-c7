---
project_name: 'automation-c7'
user_name: 'Ajay'
date: '2026-04-19'
sections_completed: ['technology_stack', 'architecture', 'implementation_rules', 'api_contracts', 'policy_system', 'ui_patterns', 'docker_deployment', 'anti_patterns']
---

# Project Context for AI Agents — automation-c7

_Critical rules and patterns for AI agents working on this Cloud Custodian AWS automation project.
Focus on unobvious details that would otherwise be missed._

---

## Technology Stack & Versions

### Backend
- **Python 3.11** (slim Docker image — do NOT use 3.12+, c7n 0.9.35 pinned)
- **Cloud Custodian (c7n) 0.9.35** — exact pin, no upgrades without testing all policies
- **boto3 1.34.55** — pinned via c7n dependency chain
- **pyyaml ≥ 6.0** — for policy file parsing
- **awslambdaric 2.2.1** — Lambda runtime interface client (only for Lambda mode)

### Frontend
- **React 18.3.1** + **React DOM 18.3.1**
- **Vite 6.0.0** (NOT Create React App, NOT Next.js)
- **Tailwind CSS 3.4.15** (JIT, utility-first — no component library)
- **React Router DOM 6.28.0** (client-side routing only, no SSR)
- **No TypeScript** — plain JSX throughout

### Infrastructure
- **AWS Lambda** — container image (python:3.11-slim), not zip deployment
- **AWS API Gateway HTTP API** — endpoint: `https://vgs6w2yd2d.execute-api.ap-south-1.amazonaws.com`
- **AWS account**: 588989875114, **primary region**: ap-south-1
- **IAM role**: `arn:aws:iam::588989875114:role/c7n-automation-lambda-dev`
- **Docker** — Dockerfile (Lambda), Dockerfile.local (local dev), nginx:alpine (UI)

---

## Architecture — Three Execution Modes

The system runs in THREE modes with the same UI:

```
Mode 1: local (access-key / aws-profile)
  Browser → http://localhost:8081 → local-server.py → handler.py → AWS APIs

Mode 2: lambda (iam-role)
  Browser → https://vgs6w2yd2d...amazonaws.com → Lambda → handler.py → AWS APIs

Mode 3: mock (offline dev)
  Browser → http://localhost:8080 → mock-api.py → deterministic fake data
```

- `ui/src/api.js` `getEndpoint(authType)` selects the endpoint based on `authType`
- `authType === 'iam-role'` → Lambda endpoint; anything else → `http://localhost:8081`
- Both modes call the same `handler.py` logic — local-server.py is a thin HTTP wrapper
- The `dryrun` flag controls whether custodian actually executes actions (default: always true for scans)

---

## Policy System — Critical Details

### Policy Name Alignment (MUST STAY IN SYNC)
Three files must always use **identical** policy names:

1. **YAML files** in `policies/` (source of truth — these are the actual c7n names)
2. **`handler.py` `POLICY_META` dict** — metadata keyed by exact YAML policy name
3. **`ui/src/lib/policyInfo.js` `POLICY_INFO`** — UI metadata for all 94 policies, keyed by exact YAML policy name

If names diverge, the policy silently fails to resolve — no error, just 0 results.

### Known correct name mappings (previously mismatched, now fixed)
| YAML name (correct) | Old broken name |
|---|---|
| `ebs-unattached-volumes` | `ebs-unattached` |
| `ebs-gp2-upgrade-to-gp3` | `ebs-gp2-upgrade` |
| `ebs-old-snapshots` | `ebs-snapshot-old` |
| `eip-unattached` | `eip-unassociated` |
| `ami-unused-detection` | `ami-unused-cleanup` |
| `s3-missing-lifecycle` | `s3-infrequent-access-lifecycle` |

### How `_run_policy` works
1. Writes a **temp YAML** with only the target named policy
2. Runs `custodian run --dry-run` (or without for actions) in a **temp output dir**
3. Reads `resources.json` from output dir **before** tempdir is deleted
4. Normalises resources via `_normalize_resources(policy_name, raw_resources)`
5. Returns `{policy, status, resources: [...normalised...], stderr}`

### Action execution
- `_run_action_on_resources(policy_name, resource_ids, action_type, region)`
- Deep-copies the policy YAML, injects a `{type: value, key: id_field, op: in, value: resource_ids}` filter
- Replaces the policy's `actions` list with the requested action config
- Runs custodian **without** `--dry-run` (LIVE execution)
- Never call this in dryrun mode — it is always destructive/real

---

## API Contract

### POST `/run`
```json
Request:  { "policies": ["sg-open-ssh", "ebs-unattached-volumes"], "dryrun": "true", "region": "ap-south-1" }
          OR { "policy": "list" }  ← returns policy index
          OR { "policy": "all" }   ← runs everything

Response: {
  "execution_time": "ISO8601",
  "dryrun": true,
  "region": "ap-south-1",
  "account": { "account_id": "588989875114", "arn": "...", "region": "..." },
  "policies_executed": 3,
  "results": [
    {
      "policy": "sg-open-ssh",
      "status": "success",
      "resources_found": {"sg-open-ssh": 14},
      "resources": [
        {
          "Severity": "CRITICAL",
          "Finding": "Security group allows SSH...",
          "ResourceId": "sg-051b8e9a5d46fe530",
          "Recommendation": "...",
          "GroupName": "...",
          "VpcId": "..."
        }
      ],
      "stderr": "..."
    }
  ]
}
```

### POST `/action`
```json
Request:  { "policy": "sg-open-ssh", "resource_ids": ["sg-abc123"], "action": "tag", "region": "ap-south-1" }
Response: { "status": "success", "resources_affected": 1, "action": "tag", "policy": "sg-open-ssh" }
```

### `dryrun` field
- Sent as string `"true"` / `"false"` from frontend (`api.js`)
- Parsed server-side: `str(params.get("dryrun", "true")).lower() == "true"`
- Always default to `"true"` in frontend for scan; `/action` endpoint always runs LIVE

---

## UI Pages

| Page | Route | Description |
|---|---|---|
| RunReport | `/` | Policy selector, filter bar, run trigger, hierarchical scan results with per-resource actions |
| PolicyBuilder | `/builder` | Visual rule builder — pick resource, filters, actions; saves custom rules to localStorage via `userRules.js` |
| RunHistory | `/history` | Past scan run list with timeline and per-policy findings breakdown |
| Settings | `/settings` | Auth type, endpoint URL, region |

### Custom Rules (PolicyBuilder + userRules.js)
- User-defined rules are stored in `localStorage` under `c7n_user_rules`
- `userRules.js` provides `listRules()`, `saveRule()`, `deleteRule(id)`
- Custom rules are run via the `/build` endpoint (not `/run`) using a dynamic policy spec
- `extraPolicyInfo` prop on `ReportTable` injects metadata for dynamic policy names not in `POLICY_INFO`
- Account info fallback for user-defined rule results: `res.account || policyData?.account || { account_id: '—', region }`

## UI Data Flow — ReportTable

### Tree structure (current)
```
results[]                          (from /run response)
  → enriched with POLICY_INFO     (service, resourceType, category, severity, label)
  → tree: service → resourceType → resourceId → { baseData, findings[] }
  → each resource appears ONCE regardless of how many policies it fails
  → findings[] contains all policy failures for that resource
```

### Key component hierarchy
```
RunReport.jsx         — filter bar, policy selector, run trigger
  └─ ReportTable.jsx  — account header, service sections, resource rows
       └─ ServiceSection          — collapsible per service (EC2, S3, EBS…)
            └─ ResourceTypeGroup  — collapsible per resource type, bulk actions
                 └─ ResourceRow   — single resource, all findings as chips, action dropdown
```

### Resource deduplication rule
Resources are deduplicated by `ResourceId` **across all policies** at the tree-building stage in `ReportTable.jsx`. A security group failing 3 policies shows as 1 row with 3 finding chips. This is intentional — do NOT revert to per-policy rows.

### Finding chips
Each finding chip shows: `[SEVERITY] policy-label [SEC|$$$]`
- `SEC` badge = security category (orange)
- `$$$` badge = cost category (violet)

---

## POLICY_META Structure (handler.py)

Every policy in YAML should have a corresponding entry:
```python
"sg-open-ssh": {
    "severity": "CRITICAL",          # CRITICAL|HIGH|WARNING|MEDIUM|COST|LOW|INFO
    "id_field": "GroupId",           # AWS field used as ResourceId
    "finding": "Human-readable ...", # Shown in UI finding chip
    "recommendation": "CLI steps...",# Shown in expanded resource row
    "meta": ["GroupName", "VpcId"],  # Extra fields to surface in UI details
}
```
`id_field` must match the actual AWS field name in the resource JSON — wrong id_field = broken action execution.

---

## Docker — Two Containers

| Container | Image | Port | Purpose |
|---|---|---|---|
| `c7n-local` | `c7n-local` | 8081 | Python backend, `local-server.py` |
| `c7n-ui` | `c7n-ui` | 3001 | nginx serving built React SPA |

### c7n-local startup
```bash
docker run -d --name c7n-local -p 8081:8081 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -e C7N_REGION="ap-south-1" \
  c7n-local
```
AWS creds must come from env vars (`AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`) OR `~/.aws` mount.
The container exits at startup if neither is found — check `docker logs c7n-local`.

### Rebuilding after code changes
```bash
# Backend (handler.py, local-server.py, policies/)
docker stop c7n-local && docker rm c7n-local
docker build --no-cache -t c7n-local -f Dockerfile.local .
docker run -d --name c7n-local -p 8081:8081 -v "$HOME/.aws:/root/.aws:ro" -e C7N_REGION=ap-south-1 c7n-local

# Frontend (any ui/src/** change)
docker stop c7n-ui && docker rm c7n-ui
docker build --no-cache -t c7n-ui --build-arg VITE_API_ENDPOINT=http://localhost:8081 ./ui
docker run -d --name c7n-ui -p 3001:80 c7n-ui
```

### VITE_API_ENDPOINT
- Only affects the **Lambda** endpoint default (iam-role mode)
- Local endpoint (`http://localhost:8081`) is hardcoded in `api.js` as `DEFAULT_LOCAL`
- Changing the local port requires updating both `Dockerfile.local` and `api.js`

---

## CORS
The local server sends `Access-Control-Allow-Origin: *` on all responses.
The Lambda function does NOT — CORS is handled at API Gateway level.
Do not add server-side CORS to the Lambda handler.

---

## Datetime — Python
Always use `datetime.now(timezone.utc)` — NEVER `datetime.utcnow()` (deprecated in Python 3.12+).
Both `handler.py` and `local-server.py` have a `_now()` helper for this.

---

## Critical Anti-Patterns

### Don't split resources by category in the UI tree
The old code split the tree as `service → category (security/cost) → resourceType → resources`.
This caused the same resource to appear multiple times (once in Security, once in Cost).
The correct tree is `service → resourceType → resourceId` — category is a badge on each finding.

### Don't add policies to policyInfo.js without adding to POLICY_META
Both must be updated simultaneously. A policy in policyInfo.js with no POLICY_META entry will run
but return resources with `Severity: INFO`, no Finding text, and no Recommendation.

### Don't use fixed grid widths in ResourceRow
The old `grid-cols-[24px_80px_1fr_160px_190px]` caused the Run button to be clipped at ~1100px.
Use `flex items-start gap-3` for the row and `flex-wrap justify-end` for action controls.

### Don't call _run_action_on_resources for dry-run scans
The action runner deep-copies and modifies the policy YAML, then runs custodian without `--dry-run`.
It is always a live execution. Only call it from the `/action` endpoint.

### Don't rebuild the policy index from handler.py on every request in Lambda
`POLICY_INDEX = _build_policy_index()` runs once at module load (Lambda cold start).
For local-server.py, the index is rebuilt only on `policy: "list"` requests.

### Don't use `aws_lambda_powertools` or any Lambda-specific logging in handler.py
The same handler.py runs in both Lambda and local-server contexts.
Use the standard `logging` module only.

---

## Key Environment Variables

| Variable | Where | Purpose |
|---|---|---|
| `C7N_REGION` | Backend container | Default AWS region for all policies |
| `AWS_DEFAULT_REGION` | Host / env | Overrides C7N_REGION if set |
| `POLICY_DIR` | Backend | Path to policy YAML files (default: `/app/policies`) |
| `LOCAL_PORT` | Backend | Port for local-server.py (default: 8081) |
| `VITE_API_ENDPOINT` | UI build arg | Lambda endpoint URL (iam-role mode only) |
| `OUTPUT_BUCKET` | Lambda | S3 bucket for results (optional, not implemented yet) |

---

## Remaining Features (Not Yet Built)

- **Scheduled scans** — EventBridge rule → Lambda trigger on a cron
- **Email/Slack notifications** — SNS topic or webhook from policy actions
- **Scan history persistence** — RunHistory page UI exists but needs a real DynamoDB backend (`c7n-runs` table) to persist results across sessions
- **Lambda deployment automation** — `deploy.sh` exists but needs CDK/Terraform
- **Multi-region scan** — run same policies across multiple regions in parallel
- **PDF/CSV export** — export scan results from the UI
- **API authentication** — no auth on `/run` or `/action` endpoints (critical for production)
