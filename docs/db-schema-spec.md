# Database Schema Specification — Cloud Estate Console

The contract chain, one direction only:

```
engines produce  →  DB stores  →  API serves  →  UI tables/panels render
(pipeline stages)   (this doc)     (BFF endpoints)   (docs/ui-table-spec.md)
```

A column exists in a UI table only if an endpoint serves it; an endpoint
serves it only if a table stores it; a table stores it only if a stage
writes it. This doc defines the middle two links and names the producer for
every table.

Conventions: single Postgres DB, `tenant_id` on every row, `TIMESTAMPTZ`
everywhere, JSONB for provider-shaped payloads, scan lineage via
`first_seen_scan_id` / `last_seen_scan_id` on every long-lived entity
(these back the standard audit columns: Scan ID, First seen, Last seen).

Naming, the repository (`store/`) layer, the API grammar, and the full
CSV/YAML → `catalog_*`/`rules_*` table mapping live in
`platform-standards.md` — this doc uses those table names throughout. The
reference-data tables (`catalog_resource_types`, `catalog_relations`,
`catalog_arn_recipes`, …) are defined there and loaded by `catalog-sync`;
they precede everything below as migration `001b_catalog.sql`.

---

## 1. What exists today (and what we keep)

| Existing table | Verdict | Notes |
|---|---|---|
| `tenants` | rename → `core_tenants` (compat view) | add `display_name` for UI |
| `inventory_report` / `inventory_scans` | keep | inventory-stage bookkeeping; superseded for UI by `pipeline_runs` below |
| `inventory_findings` | **rename → `inventory_assets`** | it stores assets — the name is a standing trap; keep a compat VIEW `inventory_findings` during transition |
| `inventory_scan_data` | keep as `inventory_asset_snapshots` (view/rename) | history, 5 snapshots retained — backs first/last seen + drift panel |
| `inventory_relationships` | keep | backs Architecture tab + graph |
| `inventory_drift` | keep as `inventory_drift_events` | backs Drift table |
| `relation_type_definitions`, `resource_relationship_templates`, `discovered_relationships` | keep | relationship engine internals |
| discoveries DB (`discovery_report`, `discovery_findings`) | keep, upstream | stage-1 raw layer; inventory reads it, UI never does |

## 2. Asset core (stage 2 writes)

```sql
-- renamed from inventory_findings; columns already largely exist
CREATE TABLE inventory_assets (
    resource_uid        TEXT NOT NULL,            -- canonical UID (ARN/OCID/...)
    tenant_id           VARCHAR(255) NOT NULL,
    provider            VARCHAR(50)  NOT NULL,
    account_id          VARCHAR(255) NOT NULL,
    region              VARCHAR(100),
    scope               VARCHAR(20)  NOT NULL DEFAULT 'regional',
    resource_type       VARCHAR(255) NOT NULL,    -- ec2.instance
    resource_id         VARCHAR(255) NOT NULL,
    name                VARCHAR(255),
    tags                JSONB DEFAULT '{}',
    metadata            JSONB DEFAULT '{}',       -- what cost rules evaluate
    topology            JSONB DEFAULT '{}',       -- layer_id, container_uid, zone, uid_quality
    hash_sha256         VARCHAR(64),              -- identity hash (drift)
    monthly_cost_usd    NUMERIC(12,2),            -- pricing join, NULL = unpriced
    first_seen_scan_id  VARCHAR(255),
    first_seen_at       TIMESTAMPTZ,
    last_seen_scan_id   VARCHAR(255),
    last_seen_at        TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, resource_uid)
);
-- indexes: (tenant,provider), (tenant,account_id), (tenant,resource_type),
-- (tenant,region), GIN(tags)
```

```sql
CREATE TABLE core_accounts (               -- NEW: account alias registry
    tenant_id   VARCHAR(255) NOT NULL,
    provider    VARCHAR(50)  NOT NULL,
    account_id  VARCHAR(255) NOT NULL,
    alias       VARCHAR(255),         -- "prod-payments" shown above the raw id
    environment VARCHAR(50),          -- prod/staging/dev badge
    PRIMARY KEY (tenant_id, provider, account_id)
);
```

## 3. Policy & rule registry (posture sync writes)

```sql
CREATE TABLE rules_definitions (               -- NEW: from policy_catalog.csv + cost rules
    rule_id      VARCHAR(255) PRIMARY KEY,  -- compliance: bare c7n name ('sg-open-ssh');
                                            -- cost: '<provider>.<name>' ('gcp.disk-stale-snapshot') —
                                            -- names repeat across clouds and engines, ids must not
    rule_kind    VARCHAR(20) NOT NULL,      -- 'compliance' | 'cost'
    provider     VARCHAR(50),               -- cost rules; NULL = aws c7n
    resource     VARCHAR(255),              -- c7n type or finops kind (vm/disk/...)
    domain       VARCHAR(20),               -- compliance|cost|governance
    severity     VARCHAR(20) NOT NULL,
    category     VARCHAR(50),               -- finops_category for cost rules
    action_tier  VARCHAR(20),               -- notify|mark|tag|remediate|destroy
    automatable  BOOLEAN DEFAULT FALSE,
    graph_check  VARCHAR(50),
    parameters   JSONB DEFAULT '{}',        -- cost-rule thresholds (the tunable chips)
    savings_model JSONB,
    definition   TEXT,                      -- YAML source for the panel
    source_file  VARCHAR(500),
    enabled      BOOLEAN DEFAULT TRUE
);

CREATE TABLE rules_metadata (        -- NEW: the authored registry (UI titles + AI fix)
    rule_id        VARCHAR(255) PRIMARY KEY REFERENCES rules_definitions(rule_id),
    title          VARCHAR(500) NOT NULL,   -- "Security group allows SSH from the internet"
    description    TEXT,
    rationale      TEXT,
    recommendation TEXT,                    -- human CLI/console steps
    ai_fix_prompt  TEXT,                    -- vendor-neutral, {{resource_id}}/{{region}}/{{evidence}} placeholders
    references     JSONB DEFAULT '[]',
    frameworks     JSONB DEFAULT '[]'       -- CIS/PCI mappings (future)
);
```

Producer: `posture` sync (extend `build_policy_catalog.py`) upserts
`rules_definitions` from the catalog + `engines/cost/rules/**`; `rules_metadata` is
authored YAML (`posture/catalog/policy_metadata.yaml`) loaded by the same
sync — regenerating the catalog never clobbers authored content.

## 4. Findings with lifecycle (stage 4 writes)

```sql
CREATE TABLE posture_findings (               -- NEW: posture-joined, lifecycle-tracked
    finding_id        UUID PRIMARY KEY,     -- uuid5(rule_id, resource_uid) — stable
    tenant_id         VARCHAR(255) NOT NULL,
    rule_id           VARCHAR(255) NOT NULL REFERENCES rules_definitions(rule_id),
    resource_uid      TEXT,                 -- NULL = unresolved (still shown!)
    resource_id       VARCHAR(255),
    resource_key      VARCHAR(255),
    account_id        VARCHAR(255),
    region            VARCHAR(100),
    severity          VARCHAR(20) NOT NULL, -- snapshot at detection
    domain            VARCHAR(20) NOT NULL,
    exposure          VARCHAR(50),          -- graph_check verdict when evaluated
    evidence          JSONB,                -- raw matched payload (panel Overview)
    status            VARCHAR(20) NOT NULL DEFAULT 'open',  -- open|resolved
    first_detected_scan_id VARCHAR(255) NOT NULL,
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_seen_scan_id VARCHAR(255) NOT NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL,
    resolved_scan_id  VARCHAR(255),
    resolved_at       TIMESTAMPTZ
);
-- indexes: (tenant,status,severity), (tenant,resource_uid), (tenant,rule_id)
```

Lifecycle rule (computed at ingest, no extra table): a finding present in
the new scan → upsert, bump `last_seen_*`; present before but absent now →
`status='resolved'`, stamp `resolved_*`; reappears → back to `open`.
"New" in the UI = `first_detected_scan_id = latest scan`.

## 5. Recommendations with lifecycle (stage 5 writes)

```sql
CREATE TABLE finops_recommendations (        -- NEW
    recommendation_id VARCHAR(600) PRIMARY KEY,  -- '<rule_id>::<resource_uid>'
    tenant_id         VARCHAR(255) NOT NULL,
    rule_id           VARCHAR(255) NOT NULL REFERENCES rules_definitions(rule_id),
    resource_uid      TEXT NOT NULL,
    account_id        VARCHAR(255),
    region            VARCHAR(100),
    severity          VARCHAR(20) NOT NULL,
    category          VARCHAR(50)  NOT NULL,     -- finops_category
    details           JSONB,                     -- evaluated conditions actual-vs-threshold
    current_monthly_cost_usd  NUMERIC(12,2),
    savings_min_usd   NUMERIC(12,2),
    savings_max_usd   NUMERIC(12,2),
    pricing_confidence VARCHAR(50),              -- list_price_estimate
    status            VARCHAR(20) NOT NULL DEFAULT 'open', -- open|dismissed|resolved
    dismissed_by      VARCHAR(255),
    dismissed_at      TIMESTAMPTZ,
    first_detected_scan_id VARCHAR(255) NOT NULL,
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_seen_scan_id VARCHAR(255) NOT NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE finops_pricing_catalog (        -- NEW: Postgres backend for store.py
    sku_key      VARCHAR(255) PRIMARY KEY,       -- 'ec2:us-east-1:m5.xlarge:linux:shared'
    region       VARCHAR(100),
    attributes   JSONB,
    on_demand_usd NUMERIC(14,6) NOT NULL,
    unit         VARCHAR(50),                    -- hour|gb-month
    fetched_at   TIMESTAMPTZ NOT NULL            -- TTL staleness
);
```

Same lifecycle rule as findings, plus user-driven `dismissed`.

## 6. Pipeline runs (orchestrator writes)

```sql
CREATE TABLE pipeline_runs (          -- NEW: one row per pipeline run — the Runs table
    scan_run_id   VARCHAR(255) PRIMARY KEY,
    tenant_id     VARCHAR(255) NOT NULL,
    trigger       VARCHAR(20) NOT NULL DEFAULT 'manual', -- manual|scheduled|api
    triggered_by  VARCHAR(255),
    providers     JSONB DEFAULT '[]',
    accounts      JSONB DEFAULT '[]',
    regions       JSONB DEFAULT '[]',
    stages        JSONB NOT NULL DEFAULT '{}',  -- {discover:{status,started,finished,records,error}, assets:{...}, ...}
    totals        JSONB DEFAULT '{}',           -- {assets, findings_by_severity, recommendations, savings_min, savings_max}
    status        VARCHAR(20) NOT NULL,         -- running|success|partial|failed
    started_at    TIMESTAMPTZ NOT NULL,
    completed_at  TIMESTAMPTZ
);

CREATE TABLE pipeline_run_artifacts (          -- NEW: stage outputs (scene.json etc.)
    scan_run_id  VARCHAR(255) NOT NULL REFERENCES pipeline_runs(scan_run_id),
    stage        VARCHAR(30) NOT NULL,          -- architecture|compliance|finops
    kind         VARCHAR(30) NOT NULL,          -- scene|findings|recommendations
    content      JSONB,                         -- cluster mode: inline
    path         VARCHAR(500),                  -- file mode: out/... pointer
    records      INTEGER,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (scan_run_id, stage, kind)
);
```

Run "deltas" (Assets ±, Findings ±) are computed by the API from the
previous run's `totals` — no extra storage.

---

## 7. Alignment matrix — every UI table, end to end

| UI table / panel | API endpoint (BFF) | DB tables | Producer (stage) |
|---|---|---|---|
| Assets | `GET /api/v1/inventory/assets` (+`?include=finding_counts,cost`) | `inventory_assets` ⋈ `posture_findings` ⋈ `finops_recommendations` ⋈ `core_accounts` | 2 build_assets (index writer) |
| Asset panel · Compliance tab | `GET /api/v1/inventory/assets/{uid}/findings` | `posture_findings` ⋈ `rules_metadata` | 4 |
| Asset panel · Cost tab | `GET /api/v1/inventory/assets/{uid}/recommendations` | `finops_recommendations` ⋈ `rules_metadata` | 5 |
| Asset panel · Architecture tab | `GET /api/v1/inventory/assets/{uid}/relationships` | `inventory_relationships` + `topology` | 2/3 |
| Asset panel · Drift tab | `GET /api/v1/inventory/assets/{uid}/drift` | `inventory_drift_events` | 2 (detector) |
| Findings | `GET /api/v1/posture/findings` | `posture_findings` ⋈ `rules_definitions` ⋈ `rules_metadata` ⋈ `core_accounts` | 4 compliance+posture |
| Finding panel · Fix tab | same payload (`metadata.ai_fix_prompt` + evidence) | `rules_metadata` | authored registry |
| Recommendations | `GET /api/v1/finops/recommendations` | `finops_recommendations` ⋈ `rules_definitions` ⋈ `rules_metadata` | 5 finops |
| Compliance policies | `GET /api/v1/rules?kind=compliance` | `rules_definitions` ⋈ `rules_metadata` ⋈ findings counts | posture sync |
| Cost rules | `GET /api/v1/rules?kind=cost` | `rules_definitions` ⋈ recommendations counts | posture sync |
| Pipeline runs | `GET /api/v1/pipeline/runs` | `pipeline_runs` (+ prev-run delta) | pipeline orchestrator |
| Run panel · Stages tab | `GET /api/v1/pipeline/runs/{id}` | `pipeline_runs` + `pipeline_run_artifacts` | all stages |
| Drift events | `GET /api/v1/inventory/drift` | `inventory_drift_events` ⋈ `inventory_assets` | 2 detector |
| Architecture module | `GET /api/v1/pipeline/runs/{id}/scene` | `pipeline_run_artifacts` (kind=scene) | 3 build_architecture |
| Overview KPIs | `GET /api/v1/overview` | aggregates over all of the above | — |

## 8. File-mode parity

Local/file mode (no Postgres) serves the same endpoint payloads from `out/`
artifacts — `cspm/assets.v2.json`, `findings.json`, `recommendations.json`,
`scene.json`, plus a new `out/registry.json` (policies ⋈ metadata) and
`out/runs.json`. Same JSON shapes as the DB endpoints; the UI cannot tell
the difference. That parity is the file-mode twin of the cspm convergence
rule: one contract, two feeds.

## 9. Migration plan

1. `002_core_rename.sql` — create `inventory_assets` (rename `inventory_findings`),
   compat view, add `first/last_seen_*`, `monthly_cost_usd`; `core_accounts`.
2. `003_registry.sql` — `rules_definitions`, `rules_metadata`; sync tool in
   `posture/` (catalog + cost rules + authored metadata YAML → upsert).
3. `004_posture_findings.sql` — `posture_findings` + lifecycle ingest in the
   compliance stage (writes DB when configured, `findings.json` always).
4. `005_finops.sql` — `finops_recommendations`, `finops_pricing_catalog`; finops stage
   upserts with lifecycle.
5. `006_runs.sql` — `pipeline_runs`, `pipeline_run_artifacts`; `orchestration/pipeline.py`
   writes stage statuses as it goes (file mode: `out/runs.json`).
