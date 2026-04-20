# automation-c7

Cloud Custodian (c7n) governance platform — FinOps & Security as Policy for AWS.
React dashboard for scanning, inspecting, and remediating AWS resources across 94 built-in policies,
plus a drag-and-drop Policy Builder for custom rules.

---

## What it does

- **Scan** — runs Cloud Custodian policies against your AWS account (dry-run by default)
- **Inspect** — hierarchical results grouped by service → resource type → resource ID
- **Remediate** — apply actions (tag, stop, delete, revoke…) per resource or in bulk
- **Build** — create custom policies with a point-and-click builder; save locally and run them
- **History** — browse past scan runs with per-policy breakdowns

---

## 94 Built-in Policies

| Service | Policies |
|---|---|
| EC2 / Security Groups | sg-open-ssh, sg-open-rdp, ec2-no-iam-role, ec2-stopped-30d, ec2-underutilised-instances, ec2-missing-required-tags … |
| S3 | s3-public-access-bucket, s3-encryption-disabled, s3-missing-lifecycle, s3-versioning-disabled … |
| EBS | ebs-unattached-volumes, ebs-gp2-upgrade-to-gp3, ebs-old-snapshots, ebs-encrypted-volumes … |
| RDS | rds-public-instance, rds-no-backup, rds-encryption-disabled, rds-idle-instance … |
| IAM | iam-inactive-user, iam-unused-access-key, iam-mfa-disabled, iam-admin-policy-attached … |
| Lambda | lambda-old-runtime, lambda-no-vpc, lambda-unused-function … |
| CloudTrail | cloudtrail-disabled, cloudtrail-no-log-validation … |
| VPC / Network | vpc-no-flow-logs, sg-unrestricted-egress, eip-unattached, eni-unused … |
| Secrets Manager | secrets-not-rotated, secrets-not-used-90d … |
| AMI | ami-unused-detection, ami-not-in-launch-config … |

---

## Architecture — Dual Execution Modes

```
Mode 1: Local dev / real AWS (access-key or aws-profile)
  Browser → http://localhost:3000 (Vite)
           → http://localhost:8081 (local-server.py)
           → handler.py → AWS APIs via boto3

Mode 2: Production (IAM Role / Lambda)
  Browser → http://localhost:3001 (nginx built UI)
           → https://vgs6w2yd2d.execute-api.ap-south-1.amazonaws.com (API Gateway)
           → handler.lambda_handler → handler.py → AWS APIs

Mode 3: Mock / offline dev
  Browser → http://localhost:3000 (Vite)
           → http://localhost:8080 (mock-api.py)
           → returns deterministic fake data, no AWS access needed
```

The UI's **Settings** page switches between modes at runtime.

---

## Quick Start — Mock Mode (no AWS needed)

```bash
# 1. Start the mock API server
python mock-api.py
# → listening on http://localhost:8080

# 2. In another terminal, start the UI
cd ui
npm install
npm run dev
# → http://localhost:3000

# 3. In the UI Settings, set endpoint to http://localhost:8080
```

---

## Quick Start — Real AWS

```bash
# Option A: Docker (recommended)
docker build -t c7n-local -f Dockerfile.local .
docker run -d --name c7n-local -p 8081:8081 \
  -v "$HOME/.aws:/root/.aws:ro" \
  -e C7N_REGION="ap-south-1" \
  c7n-local

docker build -t c7n-ui ./ui
docker run -d --name c7n-ui -p 3001:80 c7n-ui

# Option B: Bare metal
pip install -e ".[aws]"
python local-server.py   # port 8081

cd ui && npm install && npm run dev
```

---

## Policy YAML Format (Cloud Custodian)

Policies live in `policies/` and are standard c7n YAML:

```yaml
policies:
  - name: sg-open-ssh
    resource: aws.security-group
    description: Security groups with unrestricted SSH inbound
    filters:
      - type: ingress
        Ports: [22]
        Cidr:
          value: "0.0.0.0/0"
    actions:
      - type: tag
        tags:
          Remediation: "open-ssh-flagged"
```

---

## UI Pages

| Page | Route | Description |
|---|---|---|
| Run & Report | `/` | Policy selector, scan trigger, hierarchical results with per-resource actions |
| Policy Builder | `/builder` | Visual rule builder — pick resource, filters, actions; save custom rules to localStorage |
| Run History | `/history` | Past scan runs list with per-policy findings breakdown |
| Settings | `/settings` | Auth type, endpoint URL, region |

---

## Project Structure

```
automation-c7/
├── handler.py              Core engine — policy runner, normalizer, action executor
├── local-server.py         HTTP wrapper for local mode (port 8081)
├── mock-api.py             Mock server for offline dev (port 8080) — 94 policies with fake data
├── policies/               Cloud Custodian YAML files (source of truth)
│   ├── finops/             Cost optimization policies
│   └── security/           Security & compliance policies
├── ui/
│   ├── src/
│   │   ├── api.js          Endpoint router + fetch wrappers
│   │   ├── lib/
│   │   │   ├── policyInfo.js   Static UI metadata for all 94 policies
│   │   │   └── userRules.js    localStorage CRUD for custom rules
│   │   ├── pages/
│   │   │   ├── RunReport.jsx   Main scan + results page
│   │   │   ├── PolicyBuilder.jsx   Custom policy builder
│   │   │   ├── RunHistory.jsx  Scan history viewer
│   │   │   └── Settings.jsx    Config page
│   │   └── components/
│   │       ├── ReportTable.jsx Hierarchical results tree
│   │       └── Layout.jsx      Nav shell
│   ├── Dockerfile          nginx production image
│   └── vite.config.js
├── Dockerfile              Lambda container image
├── Dockerfile.local        Local dev container
└── c7n_schema.csv          Full c7n schema: 273 resources, 2641 filters, 1728 actions
```

---

## Development

```bash
# Backend tests (requires AWS creds or moto)
pip install -e ".[dev]"
pytest tests/ -v

# Frontend lint/type check
cd ui && npm run lint
```

---

## Branch

Active development branch: `ajay-finops`
Production merges to: `main`
