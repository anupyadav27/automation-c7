# Engine Improvements — remaining backlog

The documented gap list per engine, ordered by how much each unlocks.
Standards referenced here live in `platform-standards.md`; storage in
`db-schema-spec.md`; UI contract in `ui-table-spec.md`.

## 1. Discovery (`providers/`)

- **Non-AWS depth**: Azure/GCP/OCI/IBM/K8s scanners cover 4–13 services
  each against AWS's 1,404 catalog-driven types. Priority: Azure (already
  DB-driven, closest to standard), then GCP. The contract stays
  `cspm_asset.v2` — depth is per-provider work, consumers don't change.
- **Multi-region in one run**: the AWS collector runs one region per
  invocation; plan+collect across a region list with shared global-layer
  dedup (IAM/Route53 collected once, not per region).
- **Connection paths** (`ROADMAP.md`, deliberately deferred): TGW → LB →
  ENI → endpoint → S3 path assembly from the 18 topology scenarios.
- **Local pipeline uses AWS only**: `orchestration/stages/discover.py`
  should gain provider fan-out once a second provider reaches parity.

### Child resolution is scoped to the owning service

A child call declares the one parameter it needs — `clusterName`,
`PolicyId`, `Name` — and the collector fills it from assets already
collected. That index used to be a single global namespace keyed on the
parameter name, which is only safe if parameter names are unique across
AWS. They are not: 101 services declare an id field of `Id`, 80 declare
`Name`, 49 declare `arn`.

The result was calls that could never succeed. `ssm.list_document_versions`
took the name of anything in the account that had one — 136 failures
reading *Document with name AutoScalingManagedRule does not exist*.
`fms.list_compliance_status` was fed 21-character ids where FMS wants 36.
`connect.traffic_distribution` asked for `Id` and was handed the estate.

**The rule**: a child takes its parent from its own service. Where no
parent in that service exists, it may reach across only when exactly one
service offers the name *and* the name is not one of the bare forms
(`id`, `name`, `arn`, …) that identify nothing anywhere. Anything else is
recorded as `AmbiguousParent` and not attempted, because there is no
evidence for choosing between the candidates.

Scoping, not banning, is what makes this work: `Name` is meaningless on
its own but perfectly precise as "`Name`, from `ssm`". A blanket ban on
generic names was tried first and cost the legitimate
`ssm.document → document_version` link.

### 37 operations need a required value nobody can guess

botocore declares what every operation requires, so undeclared required
parameters are checkable offline — 42 collectable types had one. Five
needed only a paging knob (`MaxResults`), which has exactly one right
answer and is now taken from botocore's own declared maximum; a test
guards that class permanently.

The remaining 37 need a value that identifies *what to ask about*, and
there is no single right answer:

| shape | examples | what it needs |
|---|---|---|
| an enum | `opensearchserverless.list_*` wants `type`; `iotwireless` wants `ResourceType` | fan out over botocore's declared enum, one call per member |
| a status | `elastictranscoder.list_jobs_by_status` wants `Status` | as above, but only some values are interesting |
| a filter object | `health.describe_affected_entities`, `devops-guru.list_events` | a filter has to be composed, not enumerated |

Fanning over an enum is mechanical and probably correct, but every one of
these services is unused in the only estate available to test against —
so it would be built blind, which is how the family box got built and
reverted. Left declared and unattempted until an account exercises one.

### A failure says why, not just that

`benign` was a boolean over an exact-code set, and AWS gives every service
its own spelling of "that does not exist" — `NoSuchBucketPolicy`,
`RepositoryPolicyNotFoundException`, `NoSuchOriginAccessControl`,
`NamespaceNotFound`. 317 failures in one sweep were that one sentence in
thirty spellings, every one counted as something having gone wrong.

Failures now classify by shape into `absent` (the optional thing is not
configured), `unused` (the service is not switched on here), `transient`
(throttle, timeout), `denied` (our permissions, kept separate so a run
limited by policy says so rather than reporting an empty estate) and
`error`. The run report carries `failures_by_reason`. **`error` is the
only bucket worth reading** — everything else is a fact about the estate,
not about the collector.

## 2. Inventory (stage 2, `inventory/`)

- **Metadata enrichment is the FinOps multiplier**: `emit._metadata` is
  deliberately thin; cost rules find fields absent rather than wrong.
  Populating `size_gb`, `age_days`, `cpu_utilization`, `storage_class`,
  `attached` per type (CloudWatch enrichment exists in
  `providers/aws/enrich`) directly increases how many of the 62 cost rules
  can fire. Highest-value single improvement in the platform.
- **Architecture builders**: `aws_builder.py` is real (360 lines);
  azure/gcp/oci/ibm builders are 15-line stubs on `base_builder`.
- **first/last seen exposure**: history exists (`inventory_scan_data`,
  5 snapshots); surface it through `store/inventory` for the audit columns.
- **Classifier config**: DB/file dual mode standardised behind
  `store/catalog` instead of ad-hoc `USE_DATABASE` checks.

## 3. Compliance (stage 4, `engines/compliance` + c7n execution)

- **Findings lifecycle ingest** (schema ready: `posture_findings`):
  open/resolved transitions computed at ingest; gives the UI New badges and
  History tabs.
- **Multi-region fan-out**: one grouped custodian invocation per region
  today; accept a region list on `/run` and the pipeline compliance stage.
- **Generate `POLICY_META` + `policyInfo.js` from `rules_metadata`**: the
  DESIGN.md goal — one registry, three consumers; kills the three-way
  name-drift class of bugs permanently.
- **mock-api parity**: `mock-api.py` predates the merge (94 vs 90
  policies); regenerate its fixtures from the registry.

## 4. Posture (`posture/`)

- **Author the metadata registry**: 152 entries (90 + 62) in
  `policy_metadata.yaml` — titles/rationale seeded from `POLICY_META`,
  `ai_fix_prompt` authored fresh (vendor-neutral, placeholder-based).
- **Graph checks at ingest**: the catalog assigns `reachable-from-internet`
  / `no-inbound-edges` / `owner-from-parent` per policy; evaluate them
  against `inventory_relationships` during findings ingest and store the
  verdict in `posture_findings.exposure` (severity escalation for
  compliance, safety interlock for cost, owner inheritance for governance).
- **Resolve coverage**: `MANUAL_TYPE_MAP` handles `network-addr`; audit the
  other 18 c7n types against `catalog_c7n_types` for silent mismatches.

## 5. FinOps + Pricing (stage 5)

- **Azure/GCP pricing extractors**: pricing is AWS-only (5 SKU families);
  38 of 62 rules target azure/gcp and can't be priced yet.
- **Actual-cost integration** (CUR / Cost Explorer): today all figures are
  list-price estimates (`pricing_confidence: list_price_estimate`);
  negotiated rates, RIs and Savings Plans change real savings materially.
- **Recommendation lifecycle + dismiss** (schema ready:
  `finops_recommendations.status`).
- **Pricing store → Postgres** (`finops_pricing_catalog`): `store.py` was
  built for a swappable backend; wire it.
- **Config at import-time**: `engines/cost/config.py` freezes env at import
  (the pipeline works around it with `importlib.reload`). Make config
  lazy (function or object), delete the reload hack in
  `orchestration/stages/finops.py`.

## 6. Pipeline & platform (cross-cutting)

- **`pipeline_runs` writing**: each stage records status/counts through
  `store/pipeline` as it runs — feeds the Runs table; file mode writes
  `out/runs.json`.
- **catalog-sync + rules-sync loaders**: the CSV/YAML → table loaders from
  `platform-standards.md` §2, idempotent, content-hashed.
- **Scheduling & notifications**: cron/EventBridge trigger for
  `pipeline all`; notify hooks on new critical findings / savings above a
  threshold.
- **Repo hygiene**: delete dead `tests/test_engine.py`/`test_models.py`
  (import a `src/` package that never existed here); recreate `.venv`
  (shebangs were patched after the repo rename, a fresh venv is cleaner);
  retire legacy UI pages once the Lovable console lands.
- **Auth on the API**: `/run` and `/action` are unauthenticated — required
  before anything is exposed beyond localhost.
