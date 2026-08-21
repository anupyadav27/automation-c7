# Build Plan — Cloud Estate Console, define → design → develop

Contracts already frozen (define ✓ / design ✓):
`ui-table-spec.md` (tables + panels) · `db-schema-spec.md` (storage) ·
`platform-standards.md` (naming, store, API grammar) ·
`design-language.md` (visual system, extracted from threat-engine) ·
`engine-improvements.md` (engine backlog). Lovable project "Cloud Guardian"
is the approved visual blueprint; production code lives here.

## Sprint board

Status 2026-08-02: **Sprints 0–6 delivered.** Running stack: postgres :5433,
API :8090, console :3100 (`scripts/smoke.sh` → 19/19). Remaining work is the
engine backlog in `engine-improvements.md` plus the follow-ups at the bottom
of this file.

### Sprint 0 — Platform foundation ✅ DONE
Pipeline stages, store/ repository (postgres+files), migrations 001b–006,
catalog-sync (19 tables) + rules-sync (152 rules), metadata registry with
AI fix prompts, lifecycle ingest verified, pipeline_runs recording,
grouped c7n execution, local deploy.

### Sprint 1 — API service (the UI's data plane)
Goal: every UI table/panel endpoint from the alignment matrix serves real
data through store/, files or postgres alike.
- `api/` FastAPI app on **:8090** — one router per domain
  (`/api/v1/inventory/*`, `/posture/findings`, `/finops/recommendations`
  + dismiss, `/rules`, `/pipeline/runs` + `/{id}/scene`, `/overview`)
- Standard envelope `{data, pagination, meta}`; RFC-7807-ish errors;
  uniform query grammar (limit/offset/sort/filters)
- Registry joined onto findings/recommendations (title + ai_fix_prompt
  rendered per-record with placeholders filled)
- Acceptance: same curl works on STORE_BACKEND=files and =postgres;
  overview aggregates real counts.

### Sprint 2 — Console shell (production frontend)
Goal: Next.js app `console/` carrying threat-engine's design DNA natively.
- globals.css tokens copied verbatim (surfaces/borders/text/sidebar/
  severity/type scale), Inter + JetBrains Mono via next/font,
  global tabular-nums
- Primitives: Button, Card/Panel, Badge (the 12%/30% chip formula),
  Stat, Table/THead/TH/TD, Skeleton, EmptyState, Drawer, Tabs, PageHeader
- AppShell: 56px top bar + 240px sidebar (active #e4eefe/#2563eb + 3px
  accent), 8-module nav
- `lib/api.js` client (envelope-aware), Inventory page live against :8090
- Acceptance: Inventory table renders 686 real assets with two-line entity
  cells, chip severity, em-dash nulls.

### Sprint 3 — Module pages ✅ DONE
Compliance (domain tabs + severity filter, severity-striped rows), FinOps
(summary band, savings column, category tabs), Policy Studio
(compliance/cost tabs, threshold chips), Runs & Drift (5-segment stage
dots, drift tab), Overview (KPI strip), Settings (backend + health).

### Sprint 4 — Panels & the Fix experience ✅ DONE
Shared Drawer/Tabs/Field/CopyBlock primitives. Finding drawer with **Fix
tab** (server-filled `ai_fix_prompt_filled`, one-click copy),
Recommendation drawer (+ Dismiss → POST), Policy drawer (metadata /
definition / fix template), Run drawer (per-stage status).

### Sprint 5 — Architecture page ✅ DONE
Layered containment rendered from asset topology (account → region →
layer → type counts). Charts deferred: recharts conventions are specced in
design-language.md; the pages currently show counts, not plots.

### Sprint 6 — Hardening & ship ✅ DONE
Optional bearer-token auth (`API_TOKEN`, /health stays open), `format=csv`
on every list endpoint, docker-compose (postgres + api + console, legacy UI
behind a `legacy` profile), `scripts/smoke.sh` (19 checks).

### Sprint 7 — Design parity & gap closure ✅ DONE
Reviewed the running console in a headless browser against the approved
Lovable blueprint and closed the difference:
- `DataTable` — toolbar (search, filter slot, row count, **column picker**,
  **CSV export**), sortable headers, fixed px widths with ellipsis
  truncation, 48px rows, severity stripe, skeleton + named empty states,
  pagination footer. Every table page uses it.
- **Audit columns** (tenant, scan id, first/last seen, uid quality,
  exposure…) ship hidden and are revealed from the column picker.
- Overview rebuilt: pipeline status strip (5 stages, freshness + records),
  KPI row with dotted severity sublines, **SVG donut** + legend, top savings
  and newest-critical panels.
- Shell: sidebar counts, section label, execution-mode footer; top bar with
  search affordance, backend indicator, avatar.
- **Scan launcher** — `POST /api/v1/pipeline/runs` (background, single-flight
  lock) + dialog with policy and resource scoping. Verified live.
- **Group by resource** toggle on Findings (deduped chip view).
- Bugs found by the browser review and fixed: duplicate React keys (several
  findings share one resource_uid), wrapping entity cells → ragged rows,
  long CLI strings overflowing drawers, dev badge covering the sidebar.
Verification: 19/19 smoke, 7/7 interaction tests, zero browser console
errors.

### Sprint 8 — Topology restored ✅ DONE
The Architecture page had been rewritten twice (merge, then the Lovable
redesign) and lost the original scene-graph presentation. The original
`ui/src/pages/Topology.jsx` (1,057 lines) is now ported into the console
verbatim — it was already the right design:
- **Nesting is containment**: account › region › vpc › az › subnet › unit.
- **Everything else is a code**: `sg-1`, `rt-2`, `iam-3`, `kms-4`, `pol-5`
  on each governed resource's border instead of lines (lines become a
  hairball past a few dozen edges; codes survive filtering).
- **Global panel** on the right (IAM, CloudFront, Route 53, DNS,
  Organizations) and a **supporting band** on top (identity, encryption,
  certificates) with the `encrypted-by · assumes · can-access` tie.
- **Groups show 5 members + `+N table`**, and the table carries ids, ARNs,
  location and every applicable code.
- Overlay toggles (dns/image/network/identity/encryption), per-service
  filters with counts, click-to-select multi-trace with drawn curves,
  resource detail panel, legend, connected accounts.
Required: Tailwind v4 added to the console (the page is Tailwind-authored),
plus `GET /api/v1/pipeline/runs/{id}/scene` and `/resources` so the page
reads artifacts through the API instead of /public.

**Re-skinned to the design system** (the ported page kept its demo-app
aesthetic, which clashed): 15 defects fixed —
1. 40+ service chips (a three-line wall) → one searchable dropdown with counts
2. overlay chips with jammed counts (`dns11`) → spaced toggles (`dns · 11`)
3. unstyled floating search box → `.ce-input` in a proper toolbar
4. edge-to-edge bleed → the canvas sits in a card on the 24px page gutter
5. five pastel fills (pink/lavender/mint/red/green) → neutral surfaces with a
   3px coloured left edge per layer
6. coloured uppercase layer labels → the platform's slate `.ce-section-label`
   with a layer dot
7. `┈┈┈ ASCII tie ┈┈┈` → hairline rule with a centred caption
8. `+43 table` debug buttons → `+43 more` ghost buttons with a table icon
9. node tiles of varying height/padding → one 26px tile spec, ellipsis names
10. `●`/`▾` ASCII group headers → lucide chevrons, tabular counts
11. amber selection (off-palette) → the accent-blue selection used by tables
12. `opacity-25` dimming → 0.3, calmer
13. heavy `ring-slate-800/30` hover → subtle border + surface change
14. code badges wrapped mid-token (`iam-` / `1`) → `white-space: nowrap`
15. raw ARNs used as node names → the ARN's last segment
**Nesting pass** (round two): the coloured left edge on *every* container
had become a cascade of stacked bars, so depth was unreadable. Now the edge
marks a top-level band only (supporting · region · global) and nested
containers are neutral with alternating surfaces + a heavier border past
depth 2; layer identity lives in the label dot. Labels dropped the unicode
glyphs (`▣`, `◈`) and now name themselves — `REGION ap-south-1`,
`VPC vpc-0796…`, `AVAILABILITY ZONE ap-southeast-1a`, `SUBNET Main` — so a
box says what it is without a legend. AZs render in an equal-width grid
with `align-items: start`, so a short zone no longer stretches to its
sibling's height.

Also fixed a real interaction bug the review surfaced: menus had no
dismiss behaviour, so an open dropdown swallowed clicks on the canvas
beneath it (`lib/useDismiss` now handles Escape + click-outside for both
the service filter and the table column picker).

### Sprint 9 — Blueprint parity ✅ DONE
Diffed the console against the Lovable blueprint (fetched via the Lovable
API — the preview URL itself needs the owner's login, so it cannot be
screenshotted headlessly). Page furniture had drifted while the tables were
being built; realigned:
- sidebar nav grouped **Discover / Govern / Operate** (was one "Pipeline" list)
- **breadcrumb** on every page (`Cloud Estate / <page>`)
- **page icons** restored in headers
- top bar: **⌘K chip** and the green **API healthy** pill (was plain text)
- **severity chips ship an icon** (AlertOctagon/AlertTriangle/Minus/Info),
  per design-language's "severity is never colour-only" rule
- sidebar footer reads execution mode + tenant, as the blueprint does

Deliberate deviation, on request: **Architecture** follows the original
`ui/` topology plus the AWS architecture-diagram group convention (official
group colours, dashed Region/AZ borders, corner service glyphs) rather than
the blueprint's simplified nested boxes — the blueprint never had the scene
graph, codes, overlays or layer filters.

### Sprint 10 — the blueprint IS the console ✅
Reimplementing the Lovable design in a second stack was the mistake: it
guaranteed drift and cost a review cycle per page. The Lovable codebase now
runs as the console (`console-app/`, TanStack Start + Tailwind v4 + shadcn),
so its components, tokens and presentation are used verbatim rather than
approximated.

Wiring: every route imports its data from `src/lib/mock-data.ts`, so that
single module is the seam. `scripts/sync-live-data.mjs` pulls the real
estate from the API (`/inventory/assets?include=rollups`, `/posture/findings`,
`/finops/recommendations`, `/pipeline/runs`, `/overview`) and writes
`src/lib/live-data.json` in the exact shapes the app declares; mock-data
prefers it and falls back to the generated fixtures when the API is down, so
the UI is never blocked by a dead backend. Runs automatically on `predev`;
`npm run sync` refreshes it. Sidebar badges and Inventory now read live
counts (564 assets, 67 findings, 41 recommendations, 90 policies).

Ports on :3200 (console-app, the real one) — the Next.js `console/` stays
only until its topology page is moved across.

**Still fixture-backed** (no API source yet, honestly flagged): drift events,
the account/region breadcrumb chips, `$48,312 monthly spend`, and the
per-stage record counts on the Overview strip. Savings show $0.00 because
pricing is off — run the finops stage with `--pricing` to populate them.

### Follow-ups (next session)
- Port `console/src/app/architecture/page.jsx` (the restored topology, with
  its AWS group styling) into `console-app/src/routes/architecture.tsx`,
  then delete `console/`.
- Replace the sync-script snapshot with live loaders (TanStack Router
  `loader` per route) so the console refreshes without a rebuild.
- Wire drift + spend once the pipeline emits them.
- Retire `ui/` now that the console launches scans (keep `handler.py` — it
  is the c7n executor the API stage calls).
- Recharts for trend/bar charts (the donut is hand-rolled SVG today).
- Findings lifecycle UI (status filter, New badge) — data already stored.
- Engine backlog: metadata enrichment (unlocks more cost rules), azure/gcp
  pricing, multi-region fan-out.

Engine backlog (parallel, from engine-improvements.md): metadata
enrichment → more cost rules fire; azure/gcp pricing; multi-region.
