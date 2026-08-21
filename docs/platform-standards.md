# Platform Standards — naming, storage, data access, API

Principle: **everything the platform knows lives in a database table whose
name says what it is; everything that reads data goes through one modular
repository layer; every API endpoint follows one grammar.** Files (CSV/YAML
in git) remain the *authoring* format; tables are the *serving* format; a
loader keeps them in sync.

---

## 1. Table naming standard

`<domain>_<entity>` — plural entity, snake_case, no abbreviations. The
domain prefix states the table's lifecycle and producer:

| Prefix | Lifecycle | Producer | Examples |
|---|---|---|---|
| `core_` | slow-changing platform registry | onboarding/admin | `core_tenants`, `core_accounts` |
| `catalog_` | **build-generated reference data** (regenerated, never hand-edited) | `providers/aws/build` loaders | `catalog_resource_types`, `catalog_relations` |
| `rules_` | evaluation rules + authored metadata | posture sync + authors | `rules_definitions`, `rules_metadata` |
| `inventory_` | discovered estate state + history | stage 2 (inventory) | `inventory_assets`, `inventory_drift_events` |
| `posture_` | joined findings | stage 4 (compliance+posture) | `posture_findings` |
| `finops_` | cost outputs | stage 5 (finops+pricing) | `finops_recommendations`, `finops_pricing_catalog` |
| `pipeline_` | run orchestration | pipeline | `pipeline_runs`, `pipeline_run_artifacts` |

Rules: no table without a prefix; a column named the same thing means the
same thing everywhere (`resource_uid`, `tenant_id`, `scan_run_id`,
`rule_id`, `first_seen_at`, `last_seen_at` are reserved and never reused
with a different meaning).

## 2. Every CSV/YAML becomes a `catalog_` or `rules_` table

Git remains the source of truth (reviewable diffs); `catalog-sync` loads
them into tables with `loaded_at` + `content_hash` so drift between git and
DB is detectable. Runtime reads the DB when configured, falls back to the
file — the same dual-feed parity rule as everywhere else.

| Source file (today) | Table | Notes |
|---|---|---|
| `providers/aws/catalog/resource_catalog.csv` (4,761) | `catalog_resource_types` | absorbs `asset_types.csv` (asset_class already a column) |
| `arn_recipes_full.csv` + `arn_recipes.csv` | `catalog_arn_recipes` | `source` column: full \| c7n |
| `relations_full.csv` + `relations_mined.csv` + `relations.csv` + `relationship_master.csv` | `catalog_relations` | `source` + `verdict` columns preserve provenance (CONFIRMED/PARTIAL/ABSENT/REFUTED) |
| `layers.csv` + `layer_assignment.csv` | `catalog_layers`, `catalog_layer_assignments` | |
| `icon_map.csv` | `catalog_icons` | |
| `cfn_types.csv` | `catalog_cfn_types` | |
| `resource_types.csv` (c7n) | `catalog_c7n_types` | the c7n_name bridge |
| `location_paths.csv` | `catalog_location_paths` | |
| `policy_sources.csv` | `catalog_policy_sources` | mechanism B |
| `value_joins.csv` | `catalog_value_joins` | mechanism C |
| `collection_args.csv`, `collection_filters.csv`, `non_asset_types.csv` | `catalog_collection_args`, `catalog_collection_filters`, `catalog_non_asset_types` | |
| `specs/*.discovery.yaml` (456) | `catalog_discovery_specs` | one row per discovery_id, spec as JSONB |
| `topology_scenarios.yaml` (18) | `catalog_topology_scenarios` | |
| `posture/catalog/policy_catalog.csv` (90) + `engines/compliance/policies/**` | `rules_definitions` (kind=compliance) | YAML definition stored in `definition` |
| `engines/cost/rules/**` (62) | `rules_definitions` (kind=cost) | parameters/savings_model as JSONB |
| `posture/catalog/policy_metadata.yaml` (authored) | `rules_metadata` | titles, rationale, `ai_fix_prompt` |
| `inventory/config/*_relationship_rules.json` | `rules_relationship_rules` | standardises the existing `resource_security_relationship_rules` |
| `inventory/config/internet_exposure_rules.json`, `relation_types.json`, `resource_domains.json` | `rules_exposure_rules`, `catalog_relation_types`, `catalog_resource_domains` | |

## 3. Modular data access — the repository layer

One package: `store/` (importable by engines, API routers, and the pipeline
alike). **Nobody else writes SQL. Nobody reads out/ paths directly.**

```
store/
  __init__.py          get_store(domain) factory — backend chosen by env
  backends/
    postgres.py        one pool, one place
    files.py           serves the same shapes from out/ artifacts
  inventory.py         list_assets(filters, page) / get_asset(uid) / asset_findings(uid) ...
  posture.py           list_findings / get_finding / ingest_findings(scan)
  finops.py            list_recommendations / dismiss / ingest(scan)
  rules.py             list_rules(kind) / get_rule / rule_metadata
  catalog.py           resource_type(key) / arn_recipe(key) / relations(source_key)
  pipeline.py          record_stage(run, stage, status) / list_runs / run_detail
```

Rules: repositories return plain dicts in the **contract shapes** (the same
JSON the API serves — one shape from DB or file backend); engines write
through repositories (`posture.ingest_findings`), so file mode and DB mode
are one code path with two backends; pagination/filter args are uniform
(`limit`, `offset`, `sort`, `**filters`).

## 4. API endpoint standard

Grammar: `/api/v1/<domain>/<collection>[/{id}][/<sub-collection>]` — domain
matches the table prefix, collection matches the entity.

| Endpoint | Serves |
|---|---|
| `GET /api/v1/inventory/assets` · `/{uid}` · `/{uid}/findings` · `/{uid}/recommendations` · `/{uid}/relationships` · `/{uid}/drift` | Assets table + Asset panel tabs |
| `GET /api/v1/posture/findings` · `/{id}` | Findings table + panel |
| `GET /api/v1/finops/recommendations` · `/{id}` · `POST /{id}/dismiss` | FinOps table + panel |
| `GET /api/v1/rules?kind=compliance|cost` · `/{rule_id}` | Policy Studio tabs + panels |
| `GET /api/v1/catalog/resource-types` · `/relations` · `/layers` | catalog consumers (UI pickers, builders) |
| `GET /api/v1/pipeline/runs` · `/{id}` · `/{id}/scene` · `POST /api/v1/pipeline/runs` | Runs table, Run panel, Architecture module, scan trigger |
| `GET /api/v1/inventory/drift` | Drift table |
| `GET /api/v1/overview` | Overview KPIs (aggregation only, no state of its own) |

Query grammar (identical everywhere): `limit`/`offset`, `sort=field:asc|desc`,
repeatable filter params (`severity=high&severity=critical`), `q=` free text,
`include=` for opt-in joins (e.g. `include=finding_counts,cost`),
`format=csv` for table export.

Response envelope (identical everywhere):
```json
{ "data": [...], "pagination": {"total": 686, "limit": 50, "offset": 0},
  "meta": {"scan_run_id": "scan_ab12", "generated_at": "..."} }
```

Errors: RFC-7807-style `{ "error": {"code", "message", "detail"} }`, HTTP
status semantic (400 bad filter, 404 unknown id, 409 stale action).

## 5. Module naming (code)

- Pipeline stages own their domain: stage modules only call `store/<domain>`
  writers for their own prefix (finops never writes `posture_*`).
- Routers: one file per domain (`api/<domain>_router.py`), thin — parse
  query grammar, call repository, wrap envelope. No business logic.
- Loaders/sync tools: `<thing>-sync` naming (`catalog-sync`, `rules-sync`),
  idempotent upserts keyed by content hash.
