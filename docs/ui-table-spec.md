# UI Table Specification — Cloud Estate Console

Theme: **light** (white surfaces, slate borders, color reserved for severity/status).
References: Wiz (inventory & issues), Prisma Cloud (asset explorer), AWS Config
(resource timeline), AWS Compute Optimizer / CloudHealth (savings tables),
Datadog (density & filtering patterns).

## Global conventions (apply to every table)

- **Entity cell pattern** — the first column is always the entity: service
  icon + display name (primary line), canonical id in monospace (secondary
  line, middle-truncated for ARNs, click-to-copy).
- **Severity** sorts by rank (critical > high > medium > low), never
  alphabetically. Rendered as a solid-dot badge, not a filled row.
- **Numbers right-aligned** with tabular numerals (costs, counts, savings).
- **Timestamps relative** ("2 h ago") with absolute ISO on hover.
- Every table has: sticky header, column picker (defaults below; the rest
  opt-in), per-column sort, faceted filter bar above the table, CSV export,
  50 rows/page, and a saved-views dropdown.
- Row click never navigates away — it opens a right-side detail panel
  (drawer) with tabs; cmd-click opens the full page. Panels are defined in
  the "Row panels" section below.
- **Standard audit columns — present on EVERY table, hidden by default,
  available via the column picker** (customers surface them for multi-tenant
  ops, audits and support):

  | Column | Source | Notes |
  |---|---|---|
  | Tenant | `tenant_id` | multi-tenant deployments |
  | Provider | `provider` | logo chip |
  | Account | `account_id` | visible by default only where listed per-table |
  | Scan ID | `scan_run_id` | mono, links to the run panel |
  | First seen | first scan containing the record | relative + absolute |
  | Last seen | latest scan containing the record | relative + absolute |
  | Fix | metadata registry `ai_fix_prompt` present? | wrench icon → opens the Fix tab of the row panel |

- **Cross-link rule** — any entity rendered anywhere is a link: resource
  cells open the Asset panel, policy/rule names open the Policy panel,
  scan ids open the Run panel, counts open the target table pre-filtered
  (e.g. the Assets "Findings" chip opens Findings filtered to that ARN).

## Policy & rule metadata registry

Every compliance policy (90) and cost rule (62) gets one registry entry —
the single source for what tables and panels display. Lives beside the
policy catalog (`posture/catalog/policy_metadata.yaml`, keyed by policy/rule
id) and is served with findings/recommendations.

| Field | Purpose | Example (`sg-open-ssh`) |
|---|---|---|
| `title` | human finding title shown in tables | "Security group allows SSH from the internet" |
| `description` | what was detected, one paragraph | "Ingress rule permits 0.0.0.0/0 on port 22…" |
| `rationale` | why it matters (risk / cost impact) | "Exposed SSH is the most common brute-force entry point" |
| `recommendation` | human remediation steps (CLI/console) | "Restrict to a bastion CIDR: `aws ec2 revoke-…`" |
| `ai_fix_prompt` | **vendor-neutral prompt the customer can paste into any local AI assistant** (Copilot, Cursor, Claude Code, …). Written with placeholders the UI fills from the finding: `{{resource_id}}`, `{{region}}`, `{{account_id}}`, `{{evidence}}` | "You are working in my infrastructure repo. Security group {{resource_id}} in {{region}} allows 0.0.0.0/0 on port 22. Find the Terraform/CloudFormation source that defines it and restrict SSH ingress to our admin CIDR, keeping other rules intact. Evidence: {{evidence}}" |
| `references` | doc links (CIS, provider docs, pricing pages) | CIS 4.1 |
| `frameworks` | compliance framework mappings (future) | CIS, PCI |

The UI never shows a bare policy id where a `title` exists; the id stays as
the monospace secondary line.

---

## 1. Assets — Inventory module (`/inventory`)

Purpose: the estate's system of record. Reference: Wiz Inventory, Prisma
Asset Explorer.

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Resource | `name`, `resource_id` | entity cell: icon + name / mono id |
| 2 | Resource type | `resource_type` | human label + raw key ("EC2 Instance · ec2.instance") |
| 3 | Provider | `provider` | logo chip |
| 4 | Account | `account_id` (+ alias when known) | alias primary, id secondary |
| 5 | Region | `region`, `scope` | code; "global" pill when scope=global |
| 6 | Placement | `topology.layer_id`, `topology.container_uid` | layer badge (L5 workload) + container id |
| 7 | Findings | join `findings.json` by `arn` | severity-split chips: `2C 1H 3M`; "—" when clean |
| 8 | Cost /mo | pricing catalog join | USD right-aligned; "—" unpriced |
| 9 | Tags | `tags` | first 2 as chips + "+N" |
| 10 | Last seen | scan timestamp | relative |

Hidden by default: full ARN (`resource_uid`), `uid_quality`, zone,
owner account, `cfn_type`, first seen, tenant.
Default sort: Findings desc, then name. Filters: provider, account, region,
service, resource type, layer, tag, has-findings, unpriced.
Row → asset drawer: overview, metadata, topology, relationships, findings,
recommendations, drift timeline.

## 2. Findings — Compliance module (`/compliance`), default view

Purpose: triage queue. Reference: Wiz Issues, Prisma Alerts. Flat list is the
default; "Group by resource" toggle gives the deduped chip view (one row per
resource, one chip per failed policy — current dashboard behaviour).

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Severity | `severity` | rank-sorted badge |
| 2 | Finding | registry `title` (fallback: policy id) | finding **title** primary ("Security group allows SSH from the internet"), policy id mono secondary |
| 3 | Domain | `domain` | badge: compliance=blue, governance=violet, cost=emerald |
| 4 | Resource | `name`, `resource_id`, `arn` | entity cell, links to Inventory |
| 5 | Type | `resource_key` | raw key |
| 6 | Account | `account_id` | id (alias when known) |
| 7 | Region | `region` | code |
| 8 | Exposure | `graph_check` result | badge only when set (e.g. "internet-reachable") |
| 9 | Remediation | `action_tier`, `automatable` | tier badge + auto/manual icon |
| 10 | Detected | scan timestamp | relative |

Hidden by default: layer, matched_by, scan id, full ARN.
Default sort: severity rank desc, then detected desc. Filters: severity,
domain, policy, service, account, region, automatable, exposure.
Row → finding drawer: raw evidence payload, recommendation text, affected
asset link, action menu (tag / notify / mark; destructive actions
double-confirm and are labelled LIVE).

Scan launcher above the table: policy multi-select (search across 90),
resource-scope input (ids/ARNs, empty = all), region, dry-run toggle
(default on).

## 3. Recommendations — FinOps module (`/finops`)

Purpose: ranked savings backlog. Reference: AWS Compute Optimizer,
CloudHealth, Vantage.

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Recommendation | `rule_name` + rule summary | human title primary ("Unattached EBS volume"), rule id mono secondary |
| 2 | Category | `finops_category` | badge: waste / rate / right-size / visibility |
| 3 | Priority | `severity` | rank-sorted badge |
| 4 | Resource | `resource_uid` (+ asset name join) | entity cell |
| 5 | Account | asset join | id |
| 6 | Region | asset join | code |
| 7 | Cost /mo | `current_monthly_cost_usd` | USD right-aligned |
| 8 | Est. savings /mo | `estimated_monthly_savings_usd.{min,max}` | green range "$4.96–12.40", sorts by max |
| 9 | Confidence | `pricing_confidence` | "list price" badge; "—" unpriced |
| 10 | Detected | run timestamp | relative |

Hidden by default: savings model type, `estimated_savings` text, source
metric (CloudWatch / Compute Optimizer), tenant.
Default sort: Est. savings max desc; unpriced rows sink to bottom.
Filters: category, priority, provider, account, region, resource kind,
priced-only toggle.
Sticky summary band above table: total current cost, total savings range,
priced/unpriced counts.
Row expand: evaluated conditions with actual vs threshold
("cpu_utilization 3.1% < 5%"), savings math, asset metadata.

## 4. Compliance policies — Policy Studio (`/policies`, tab 1)

Source of truth: `posture/catalog/policy_catalog.csv` (90 rows).

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Policy | `policy` + c7n description | name mono primary, description secondary |
| 2 | Domain | `domain` | badge |
| 3 | Severity | `severity` | badge |
| 4 | Resource type | `resource` | c7n key |
| 5 | Findings | last-scan count join | right-aligned; 0 muted |
| 6 | Action tier | `action_tier` | notify / mark / tag / remediate / destroy badge (destroy = red outline) |
| 7 | Automatable | `automatable` | check / dash icon |
| 8 | Graph check | `graph_check` | badge or "—" |

Hidden by default: source file, domain_basis, raw actions list.
Default sort: Findings desc. Filters: domain, severity, resource type,
action tier, automatable. Row → policy drawer: YAML view, run-this-policy
button (pre-fills scan launcher).

## 5. Cost rules — Policy Studio (`/policies`, tab 2)

Source: `engines/cost/rules/**` (62 rules).

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Rule | `rule_name` + description | mono name, summary secondary |
| 2 | Provider | `provider` | logo chip |
| 3 | Resource kind | `resource` | vm / disk / storage / network / snapshot / image |
| 4 | Category | `finops_category` | badge |
| 5 | Severity | `action.severity` | badge |
| 6 | Thresholds | `condition.parameters` | editable chips ("cpu < 5%", "age > 30 d") — the tunable surface |
| 7 | Savings model | `action.savings_model` | "40–100%" or "$/mo flat" |
| 8 | Matches | last-run count join | right-aligned |

Hidden by default: source metric/doc reference, `_source_file`.
Default sort: Matches desc. Filters: provider, category, resource kind,
severity. Row → rule drawer: full YAML, threshold edit (writes back later).

## 6. Pipeline runs — Runs & Drift (`/runs`, tab 1)

Reference: CI run tables (GitHub Actions) fused with scan history.

| # | Column | Source | Render |
|---|---|---|---|
| 1 | Run | `scan_run_id` + trigger | mono id, trigger icon (manual/scheduled/API) |
| 2 | Stages | per-stage status | 5-segment indicator, tooltip per stage |
| 3 | Scope | provider/account/region | chips |
| 4 | Assets | summary | count + delta vs previous run (↑12) |
| 5 | Findings | summary | severity-split + delta |
| 6 | Savings | finops summary | max range + delta |
| 7 | Duration | timing | "4 m 12 s" |
| 8 | Started | timestamp + actor | relative + who/what triggered |
| 9 | Status | overall | success / partial / failed badge |

Default sort: Started desc. Row → run detail: per-stage artifact links,
stage logs, failure reasons.

## 7. Drift events — Runs & Drift (`/runs`, tab 2)

Source: drift detector output (`cspm_drift.v1`). Reference: AWS Config
resource timeline.

| # | Column | Source field | Render |
|---|---|---|---|
| 1 | Change | `change_type` | badge: + added / − removed / ~ changed, edge variants prefixed "rel:" |
| 2 | Resource | asset join | entity cell |
| 3 | Type | `resource_type` | raw key |
| 4 | What changed | field diff summary | "3 fields: state, tags.Env, instance_type"; relation type for edges |
| 5 | Account / Region | asset join | compact combined |
| 6 | Between | scan pair | "scan_a1b2 → scan_c3d4" |
| 7 | Detected | timestamp | relative |

Default sort: Detected desc. Filters: change type, resource type, account,
region, scan pair. Row expand: side-by-side before/after field diff,
noise keys already excluded by the detector.

---

## Row panels (drawers)

Every panel: entity header (icon, name, mono id with copy, provider/account/
region chips), tab strip, and a footer with Scan ID · First seen · Last seen.
"Open full page" in the corner. Fields that reference other entities follow
the cross-link rule.

### Asset panel (from Assets table, and from any resource cell anywhere)

| Tab | Contents | Links out |
|---|---|---|
| **Overview** | name, type, ARN, state, key metadata (instance_type, size, storage class…), tags, uid quality, cost /mo when priced | account → filtered Assets; tags → filtered Assets |
| **Compliance** | this asset's findings: severity badge, finding title, domain, detected — mini-table of the Findings spec | row → Finding panel; "view all" → Findings filtered to this ARN |
| **Cost** | recommendations for this asset with savings range + total potential | row → Recommendation panel |
| **Architecture** | topology placement (layer, container chain: account > region > vpc > az > subnet), relationships in/out with relation types, exposure verdicts | container/related nodes → Asset panel; "view in diagram" → Architecture module focused on this node |
| **Drift** | this asset's change timeline (added/changed fields per scan pair) | scan ids → Run panel |
| **Raw** | canonical `cspm_asset.v2` JSON, copy button | — |

### Finding panel (from Findings table)

| Tab | Contents | Links out |
|---|---|---|
| **Overview** | registry `title`, `description`, `rationale`; severity, domain, action tier, automatable, exposure (graph check); evidence payload (raw matched fields, mono) | resource → Asset panel; policy → Policy panel |
| **Fix** | registry `recommendation` (human steps) + **AI Fix prompt**: rendered with this finding's `{{resource_id}}/{{region}}/{{account_id}}/{{evidence}}` filled in, one-click copy, "works with any local AI assistant" hint — vendor-neutral | — |
| **Actions** | run c7n action (tag / notify / mark; destructive = double-confirm, labelled LIVE) with region + dry-run context | → action result toast + rescan hint |
| **History** | occurrences across scans (first detected, still present / resolved) | scan ids → Run panel |

### Recommendation panel (from FinOps table)

| Tab | Contents | Links out |
|---|---|---|
| **Overview** | rule title + category + priority; evaluated conditions with actual vs threshold ("cpu_utilization 3.1% < 5%"); savings math (current cost, model, min–max) with confidence | resource → Asset panel; rule → Cost-rule panel |
| **Fix** | registry `recommendation` + filled AI Fix prompt (same pattern as findings) | — |
| **History** | recommendation across runs; dismiss / mark-resolved (persisted) | scan ids → Run panel |

### Policy panel (from Compliance policies table)

| Tab | Contents | Links out |
|---|---|---|
| **Metadata** | registry entry: title, description, rationale, references, frameworks; domain / severity / action tier / automatable / graph check | findings count → Findings filtered to this policy |
| **Definition** | c7n YAML, copy | — |
| **Fix template** | the `ai_fix_prompt` template with placeholders visible (what customers customise) | — |
| **Run** | "Run this policy" — pre-fills the scan launcher (policy + optional resource scope) | → Compliance module |

### Cost-rule panel (from Cost rules table)

| Tab | Contents | Links out |
|---|---|---|
| **Metadata** | registry entry + provider, resource kind, category, source metric provenance | matches count → FinOps filtered to this rule |
| **Definition** | rule YAML; threshold parameters as editable fields (write-back later) | — |
| **Fix template** | `ai_fix_prompt` template | — |

### Run panel (from Runs table, and any scan id anywhere)

| Tab | Contents | Links out |
|---|---|---|
| **Stages** | 5 stages with status, duration, record counts, failure output | artifacts: assets → Inventory filtered to scan; findings → Findings; recommendations → FinOps |
| **Deltas** | vs previous run: assets ±, findings ± by severity, savings ± | drift events → Drift filtered to scan pair |

### Drift panel (from Drift table)

Single view: change type, resource (→ Asset panel), scan pair (→ Run
panels), side-by-side before/after field diff with changed keys highlighted.

---

## Backend gaps these tables expose (to schedule)

1. **Policy & rule metadata registry** — `posture/catalog/policy_metadata.yaml`
   with title / description / rationale / recommendation / `ai_fix_prompt` /
   references for all 90 policies + 62 rules. Seed from `handler.POLICY_META`
   (finding + recommendation text already exist there) and each cost rule's
   YAML description; author `ai_fix_prompt` per entry. Served with findings.
2. **Findings lifecycle** — enterprise tools track open / new / resolved.
   We regenerate findings per scan; diffing consecutive runs (drift already
   does this for assets) gives `status` and `first_detected` almost free.
   `generate_finding_id` (uuid5) already exists as the stable key.
3. **Asset ⇄ findings/cost joins** — the Assets table's Findings and
   Cost /mo columns and the Asset panel's Compliance/Cost tabs need one
   aggregated endpoint (extend `ui_data_router` / a static `ui-data.json`
   artifact in file mode).
4. **first_seen / last_seen everywhere** — history exists in
   `inventory_scan_data` (5 snapshots retained); expose it for the standard
   audit columns.
5. **Recommendation status** — dismiss/resolve needs persistence
   (localStorage first, DB later).
