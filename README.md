# cloud-estate

A cloud architecture diagram engine. It reads a live AWS account and draws it —
account → region → VPC → AZ → subnet → workload — with every box in a place it
can justify.

```
discover → build assets → build architecture
```

| stage | what it does | where |
|---|---|---|
| 1. discover | collect raw resources, read-only by construction | `providers/` — catalog-driven AWS collector, 4,647 known types, 2,972 collectable |
| 2. build assets | normalise into canonical `cspm_asset.v2` records, one per ARN | `cspm/` contract + `providers/aws/runtime/emit.py` |
| 3. build architecture | place every asset in the layered diagram | `providers/common/topology/` → `out/scene.json` → the Architecture page |

Compliance, posture and FinOps are **not** here. They live in the threat-engine
platform; this one draws pictures.

---

## Run it

```bash
# everything, in order
python -m orchestration.pipeline all --region ap-south-1

# any stage alone — each reads the previous stage's artifact from out/
python -m orchestration.pipeline discover --region ap-south-1 --scope all
python -m orchestration.pipeline assets
python -m orchestration.pipeline architecture
```

`discover` is the only command that calls AWS. Its results cache in `out/`, so
the other two re-run for free. Always `--dry-run` first on a new account: at
full scope it plans ~1,400 root calls and tells you the cost before you pay it.

Artifacts land in `out/`: `assets.json` (raw), `cspm/assets.v2.json`
(canonical), `edges.csv` (relationships), `scene.json` (the diagram).

---

## The console

`console-app/` — TanStack Start + Tailwind.

| Page | Route | What it shows |
|---|---|---|
| Overview | `/` | the estate: assets, accounts, regions, networks |
| Inventory | `/inventory` | every asset, filterable |
| Architecture | `/architecture` | the diagram |
| Settings | `/settings` | execution mode, endpoint, region |

```bash
cd console-app && npm install && npm run dev    # port 3200
```

---

## How placement is decided

Two independent axes, and the grammar is provider-neutral — a new cloud is a
binding file, not a renderer.

- **KIND** decides placement: `boundary · resident · part · door · rule · record`.
  A role name IS its kind, optionally qualified — `door.egress`, `rule.identity`.
- **DOMAIN** decides grouping and filtering: 13 categories × 74 subcategories.

Two axioms hold everywhere: **vertical is the traffic path**, **horizontal is
redundancy**. Residents carry an exposure level, L1 internet through L4
internal, and groups read outward-in from there.

Supporting services ride a border rail as tabs. Which border comes from the
DOMAIN, so a domain cannot appear in two places:

```
              N — doors only (IGW, TGW, Direct Connect, NAT, endpoints)
   ╭────────────────────────────────────────╮  NE ── dns
   │                                        │
 W │            the container               │  E ─── identity · encryption
   │                                        │        certificates · secrets
   ╰────────────────────────────────────────╯
        SW ──────── S-middle ──────── SE
     governance    connectivity     firewall
     detection      (outbound)      routing
```

`docs/diagram-layout-spec.md` is the authoritative account of every rule and why
it exists. `docs/supporting-services.md` is generated — the full table of which
domain draws where, at which scope, in what order.

---

## What a resource panel shows

Click a box and a panel opens, built from four tiers. Three are structural and
identical for every resource; one varies by type.

| Tier | Shows | Read from |
|---|---|---|
| 1 | identity and placement | `inventory_assets` columns |
| 2 | what the resource IS | `metadata`, per type |
| 3 | what it is made of | `inventory_edges`, this asset as parent |
| 4 | what governs it | `inventory_edges`, this asset as source |

Only Tier 2 needs a catalog. `rule_diagram_discovery` holds it, and it drives
both what `emit` stores and what the panel shows — one list, so a field worth
storing is a field worth showing.

```bash
python3 scripts/build-detail-fields.py          # propose columns from real payloads
python3 scripts/build-detail-fields.py --write  # apply
python3 scripts/build-panel-reference.py > docs/panel-columns.md
```

The columns are **derived, not invented**: the generator reads the payloads in
`out/assets.json` and proposes only fields that are actually there. A column
that cannot be filled reads as "this resource has no encryption setting" when
the truth is "nobody asked". Hand-authored rows always win.

`docs/panel-columns.md` is generated — every type, its columns, and for the
types with none, the reason. It imports the generator's own classifier rather
than re-deriving one, so the reference cannot drift from the catalog.

---

## Development

```bash
# engine — placement, collection, catalog consistency
pytest cspm/tests providers/aws/tests -q

# renderer — the decisions, without a browser
cd console-app && npm test

# the diagram, against the rendered page
cd console-app && npm run check:overlap
```

`console-app/src/components/console/decide.ts` holds the renderer's pure
decisions — the grey ramp, container colours, tab geometry, cluster and group
ordering — separated from the JSX that draws them so a test can call them.
Every case in `decide.test.ts` is a defect that actually shipped: each one
type-checked, passed lint, passed the build and rendered the wrong diagram,
which is exactly the class of bug `tsc` cannot see.

`check:overlap` loads the rendered page and cross-checks every rail tab against
every box it is not inside. The clearance arithmetic is unit-tested, but whether
a box passes the right layer count is a wiring question no unit test sees.

---

## Storage

Postgres, dual-backend — set `STORE_DATABASE_URL`, or run in files mode against
`out/`. The catalog is git-authored CSV synced into `rule_diagram_*` tables:

| table | holds |
|---|---|
| `rule_diagram_services` | one row per resource type — how to collect it, where it draws |
| `rule_diagram_relationship` | one row per edge rule |
| `rule_diagram_discovery` | which fields matter per type, and which call fetches them |
| `rule_diagram_discovery_enrich` | the second call, for types whose list returns identifiers |
| `inventory_assets` | the estate itself, one row per ARN |

```bash
python -m store.catalog_sync          # git → Postgres, skips unchanged files
```

---

## Branch

Active development branch: `ajay-finops`
Production merges to: `main`
