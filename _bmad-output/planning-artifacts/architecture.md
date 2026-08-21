# automation-c7 — Architecture Document

**Project:** automation-c7 — AWS Governance Automation (Cloud Custodian)
**Date:** 2026-04-19
**Status:** Active development

---

## 1. System Overview

automation-c7 is a Cloud Custodian (c7n) governance platform with a React UI. It scans AWS accounts for security and cost violations, shows results hierarchically, and lets operators apply remediation actions per resource — without writing YAML policies by hand.

```
┌──────────────────────────────────────────────────────────────┐
│  Browser  :3001                                               │
│  React + Vite + Tailwind                                      │
│  RunReport → ReportTable → per-resource action dropdowns      │
└────────────────┬─────────────────────────────────────────────┘
                 │ HTTP/JSON
        ┌────────┴────────┐
        │                 │
   :8081 (local)    API Gateway (Lambda)
   local-server.py  https://vgs6w2yd2d...amazonaws.com
        │                 │
        └────────┬────────┘
                 │
          handler.py  (shared logic)
          ├─ _resolve_policies()
          ├─ _run_policy()  →  custodian CLI  →  resources.json
          ├─ _normalize_resources()  →  POLICY_META enrichment
          └─ _run_action_on_resources()  →  live execution
                 │
          AWS APIs (boto3)
          EC2 · S3 · EBS · ENI · AMI · RDS · …
```

---

## 2. Dual Execution Modes

| Mode | Auth | Entry point | Port | Use case |
|---|---|---|---|---|
| **Local** | Access Key / AWS Profile | `local-server.py` | 8081 | Dev, demo, ad-hoc scans |
| **Lambda** | IAM Role | `handler.lambda_handler` | API GW HTTPS | Production, CI, scheduled |

The UI selects the mode via the `Auth Type` dropdown:
- `Access Key` / `AWS Profile` → `http://localhost:8081`
- `IAM Role` → `https://abcd123456.execute-api.ap-south-1.amazonaws.com`

Same `handler.py` logic runs in both. `local-server.py` is a ~200-line HTTP wrapper.

---

## 3. Component Map

```
automation-c7/
│
├── handler.py              Core engine — policy runner, normalizer, action executor
├── local-server.py         HTTP wrapper for local credential mode (port 8081)
├── mock-api.py             Offline dev mock server (port 8080) — 94 policies with fake data
├── policies/               Cloud Custodian YAML policy files (source of truth)
│   ├── finops/             Cost optimization policies (S3, EBS, EC2, RDS…)
│   └── security/           Security & compliance policies (IAM, SG, CloudTrail, VPC…)
│
├── ui/src/
│   ├── api.js              Endpoint router + fetch wrappers
│   ├── lib/
│   │   ├── policyInfo.js   Static UI metadata for all 94 policies (service/category/severity/label)
│   │   └── userRules.js    localStorage CRUD for custom user-defined rules
│   ├── pages/
│   │   ├── RunReport.jsx   Main scan page — filter bar, policy selector, run trigger
│   │   ├── PolicyBuilder.jsx   Visual policy builder — resource, filters, actions, saved rules list
│   │   ├── RunHistory.jsx  Run history viewer — past scans with per-policy breakdown
│   │   └── Settings.jsx    Auth type, endpoint URL, region config
│   └── components/
│       ├── ReportTable.jsx  Hierarchical results: service → resourceType → resource
│       └── Layout.jsx       Nav shell
│
├── c7n_schema.csv          Full c7n schema: 273 resources · 2641 filters · 1728 actions
├── extract_c7n_schema.py   Script that generated c7n_schema.csv
├── Dockerfile              Lambda container (python:3.11-slim + c7n)
└── Dockerfile.local        Local dev container (same + local-server.py)
```

---

## 4. Request / Response Flow

### Scan flow (`POST /run`)

```
1. UI sends:  { policies: ["sg-open-ssh", "ebs-unattached-volumes"], dryrun: "true", region: "ap-south-1" }

2. handler._resolve_policies("sg-open-ssh")
     → looks up POLICY_INDEX[name] → { file: "ec2-security.yml", policy: {...} }

3. handler._run_policy(file, filter_name, dryrun=True, region)
     a. Write temp YAML with only this policy
     b. Run: custodian run --dry-run -s <tempdir> <tempyaml>
     c. Read: <tempdir>/sg-open-ssh/resources.json
     d. Cleanup tempdir

4. handler._normalize_resources("sg-open-ssh", raw_resources)
     → for each raw AWS resource:
       meta = POLICY_META["sg-open-ssh"]
       ResourceId = resource[meta["id_field"]]   # e.g. resource["GroupId"]
       return { Severity, Finding, ResourceId, Recommendation, ...meta["meta"] fields }

5. Response: {
     account: { account_id, arn, region },
     results: [{ policy, status, resources: [...normalized...] }]
   }

6. ReportTable builds tree:
     service → resourceType → resourceId → { baseData, findings[] }
   Same resource failing multiple policies: ONE row, multiple finding chips
```

### Action flow (`POST /action`)

```
1. UI sends:  { policy: "sg-open-ssh", resource_ids: ["sg-abc"], action: "revoke", region }

2. handler._run_action_on_resources(policy_name, resource_ids, action_type, region)
     a. Deep-copy policy YAML
     b. Inject filter: { type: value, key: GroupId, op: in, value: ["sg-abc"] }
     c. Replace actions: [ _build_action_config("revoke") ]
     d. Run custodian WITHOUT --dry-run  ← LIVE execution

3. Response: { status, resources_affected, action, policy }
```

---

## 5. Policy Name Alignment (Critical Rule)

Three files must always use the **same** name for the same policy:

```
policies/ec2-security.yml   →  name: sg-open-ssh          (YAML, source of truth)
handler.py POLICY_META      →  "sg-open-ssh": { ... }     (must match)
ui/src/lib/policyInfo.js    →  'sg-open-ssh': { ... }     (must match)
```

Mismatch = silent failure. Policy won't resolve, returns 0 resources, no error.

---

## 6. UI Component Architecture

```
RunReport.jsx
│  State: region, authType, service, category, selected (Set), report
│  Loads: POLICY_INFO (94 entries) + userRules → visibleRules
│  On run: POST /run { policies: Array.from(selected), dryrun, region }
│
└── ReportTable.jsx
    │  Props: { report, region, authType }
    │  Builds tree: service → resourceType → resourceId → { baseData, findings[] }
    │
    └── ServiceSection    (EC2, S3, EBS, ENI, AMI)
        └── ResourceTypeGroup   (Security Group, EC2 Instance, EBS Volume…)
            │  State: checkedIds, bulkAction, running, confirm
            │  Bulk action bar: select-all + dropdown + Run
            └── ResourceRow
                │  Severity badge  (worst across all findings)
                │  Finding chips   [SEV] policy-label [SEC|$$$]  one per policy failure
                │  Action dropdown + Run (flex-wrap, never clips)
                └── Expanded detail
                    ├── Per-finding card (severity + category + finding + recommendation)
                    └── Resource metadata grid
```

---

## 7. c7n Schema Database (`c7n_schema.csv`)

Extracted from the installed c7n 0.9.35 using `extract_c7n_schema.py`.

| Field | Description |
|---|---|
| `provider` | `aws` |
| `service_group` | Logical group: Compute, Storage, Database, Network, Security… |
| `resource` | c7n resource type: `ec2`, `s3`, `ebs`, `rds`… (273 total) |
| `category` | `filter` or `action` |
| `name` | Filter/action name: `instance-age`, `stop`, `tag`… |
| `schema_path` | Dot notation: `aws.ec2.filters.instance-age` |
| `doc` | First line of class docstring |
| `params_json` | JSON schema properties of the filter/action |
| `permissions` | IAM permissions required |

**Coverage:** 273 resources · 2641 filters · 1728 actions · 4369 rows

**Service groups:**

| Group | Resources | Schema Entries |
|---|---|---|
| Network | 34 | 702 |
| Database | 31 | 553 |
| AppServices | 30 | 407 |
| Analytics | 28 | 397 |
| Security | 27 | 356 |
| Storage | 20 | 335 |
| Compute | 11 | 276 |
| Serverless | 16 | 240 |
| Monitoring | 17 | 215 |
| IAM | 13 | 191 |
| Messaging | 11 | 181 |
| Containers | 11 | 170 |
| ML | 12 | 154 |
| DevTools | 9 | 128 |

---

## 8. Completed Features

### 8.1 Dynamic Policy Builder ✓
`PolicyBuilder.jsx` — visual rule builder backed by `c7n_schema.csv`:
- Select resource type, add filter rows (field / operator / value), add action rows
- Assign label, category, severity
- Save to localStorage via `userRules.js`; `SavedRulesList` sub-component shows saved rules with Edit / Delete
- Custom rules run via `/build` endpoint; results appear in the same ReportTable with `extraPolicyInfo` metadata

### 8.2 Run History ✓
`RunHistory.jsx` — past scan runs viewer:
- Displays run timeline and per-policy findings breakdown
- Currently backed by mock data; production backend needs DynamoDB `c7n-runs` table

### 8.3 Mock Server ✓
`mock-api.py` — offline dev server on port 8080:
- Returns deterministic fake data for all 94 policies
- Covers EC2, S3, EBS, RDS, IAM, Lambda, CloudTrail, VPC, Secrets Manager, AMI, ENI
- `/run`, `/build`, `/action` endpoints all implemented

---

## 9. Remaining Roadmap

### 9.1 Scheduled Scans
- EventBridge rule → Lambda (cron expression)
- Results stored in DynamoDB
- Optional SNS notification on new findings

### 9.2 Run History Backend
- DynamoDB table `c7n-runs` (timestamp, account, region, policy, findings_count, resource_ids)
- Wire RunHistory.jsx to real `/history` endpoint

### 9.3 Multi-region Support
- Run same selected policies across multiple regions in parallel
- Aggregate results in the same ReportTable

### 9.4 Export (PDF / CSV)
- Export current scan results from UI
- Suitable for audit reports

### 9.5 Lambda Deployment Automation
- CDK or Terraform stack
- ECR image push + Lambda update in `deploy.sh`

### 9.6 API Authentication
- No auth currently on `/run` or `/action` — critical gap for production
- Options: API Gateway authorizer, Cognito, or API key header
