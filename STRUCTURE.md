# Platform structure

One codebase, multi-cloud by design, AWS first.

## The flow

The platform is five stages, and the directory tree mirrors them:

```
1. discover            providers/        collect raw resources (read-only)
2. build assets        cspm/ + emit      canonical cspm_asset records
3. build architecture  scene graph       layered account diagram → out/scene.json
4. compliance          engines/compliance + posture/   policy checks for one, many, or all resources
5. finops              engines/cost + engines/pricing  cost rules → priced recommendations
```

Run it end to end, or any stage alone:

```bash
python -m orchestration.pipeline all --region ap-south-1
python -m orchestration.pipeline compliance --policies sg-open-ssh --resources sg-0abc123
python -m orchestration.pipeline all --region ap-south-1 --offline   # replay, no cloud calls
```

Each stage reads the previous stage's artifact from `out/` and writes its
own, so `--offline` replays stages 2–5 against the last collection for free.
The cluster deployment drives the same stages through the Discoveries API
(`providers/common/api_server.py`) and the Inventory Engine API
(`inventory/api/api_server.py`) with Postgres and K8s Jobs behind them.

```
cspm/                    THE CONTRACT — every provider fills it, every engine reads it
  schema.py                cspm_asset.v2 = v1 + topology
  uid.py                   resource identity per provider (ARN / resource ID / self-link / OCID)

providers/               COLLECTION — one package per cloud
  aws/                     catalog-driven: 4,761 types, 1,404 collectable
    build/                   offline catalog generation from botocore + CFN + c7n
    catalog/                 generated CSVs — the data that drives collection
    runtime/                 the only code that calls AWS
    validate/                relation verdicts
    enrich/                  metadata + CloudWatch metrics
  azure/  gcp/  oci/  ibm/  kubernetes/
  common/                  shared scanner scaffolding

inventory/               NORMALISATION, STORAGE, GRAPH, DRIFT
  normalizer/              raw provider JSON -> canonical assets
  schemas/                 the Pydantic Asset model (v1)
  api/                     assets, architecture, graph, drift routers
  db/                      schema + seed

engines/                 EVALUATION — three domains, three engines
  compliance/              Cloud Custodian
    policies/                90 c7n policies
  cost/                    declarative YAML rule engine
    rules/                   65 rules across aws / azure / gcp
  pricing/                 AWS Pricing API catalog -> dollar figures

posture/                 THE JOIN — findings, domains, arbitration
  catalog/                 policy_catalog.csv: THE source of policy metadata
  resolve.py               a c7n resource -> a discovered asset
  findings.py              findings.json

orchestration/           the flow as code
  pipeline.py              CLI — one subcommand per stage, `all` chains them
  stages/                  discover, build_assets, build_architecture,
                           compliance, finops — one module per stage
  main.py                  FinOps-only CLI (stage 5 standalone)
ui/                      one frontend
out/                     run output; out/samples holds fixtures
```

## The rules that keep it coherent

**Dependencies point one way.** `providers/*` and `engines/*` depend on `cspm/`.
`posture/` depends on providers and engines. Nothing depends on `posture/`, and
no provider depends on another. That is what lets a second cloud be added
without touching a consumer.

**Nothing references anything outside this repository.** The FinOps platform's
own scan is kept in `out/samples/` as a fixture, so the cross-pipeline identity
check runs anywhere the repo is checked out.

**Provider vocabulary stops at the provider boundary.** `vpc_id` is an AWS word.
Above `providers/`, position is expressed only in the shared `topology` keys —
`container_uid`, `parent_uid`, `zone`. `cspm.schema.validate` fails a record
that smuggles a provider-specific key into the shared shape.

**The catalog approach is AWS-specific, and that is fine.** `providers/aws`
derives what to collect from botocore and the CloudFormation registry. Azure and
GCP have no equivalent, so each provider is free to decide *how* it knows what
to collect. What they may not vary is *what they emit* — `cspm_asset.v2`.

## Where each system's strengths landed

| from | kept because |
|---|---|
| discovery (cloud-estate) | catalog-driven breadth — 1,404 collectable types against 5 hand-written fetchers |
| discovery | ARN recipes, relations (2,774), layers, scene graph |
| FinOps | the canonical `cspm_asset` schema, and `hash_sha256` drift detection |
| FinOps | multi-region and multi-cloud scanner scaffolding |
| FinOps | the pricing catalog — what turns a finding into a dollar figure |
| FinOps | 65 declarative cost rules, and the `finops_category` taxonomy |
| FinOps | CloudWatch metric enrichment (`providers/aws/enrich`) |
| c7n | 90 compliance/governance policies and 1,000+ filters |

Dropped: `service_scanner.py` (2,060 lines, one `scan_` method, ec2+sts only —
superseded by `fetch_real_assets.py`, itself superseded by the catalog),
`aws_builder.py`'s hand-coded placement (104 hardcoded `vpc` checks against a
catalog that places 4,761 types from data), and `engine_common/` (stubs, 2–13
lines each).
