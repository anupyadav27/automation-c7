# Design Language — extracted from threat-engine (the grade to match)

Source: `/Users/apple/Desktop/threat-engine/frontend` (Next.js 15, Tailwind v4
tokens-in-CSS, TanStack Table, Recharts). The Cloud Estate Console UI must
match this system. Authoritative reference files there:
`src/app/globals.css`, `src/design-system/DESIGN_SYSTEM.md`,
`src/lib/design-tokens.js`, `src/lib/severity-styles.js`,
`src/components/shared/DataTable.jsx`,
`src/components/table/cells/COMPACT_CELL_CONTRACT.md`.

## Tokens (light-only)

Surfaces: page `#ffffff`, secondary `#f6f8fb` (row hover, bands),
tertiary `#eef2f7` (table header band, chips, toolbar buttons),
input `#f5f7fa`, code `#f1f5f9`.
Borders: primary `#e5e9f0` (every default border), secondary `#cdd6e2`
(inputs, header underline).
Text: primary `#0f172a`, secondary `#1e3350` (td default),
tertiary `#4a6280` (headers, labels), muted `#6b849e` (sub-lines, em-dash).
Sidebar namespace: bg `#f7f9fb`, fg `#475569`, hover `#eef4fc`,
active `#e4eefe`, active-text/accent `#2563eb`, border `#e5e9f0`.
Accent: `#3b82f6` (primary), success `#22c55e`, warning `#f59e0b`,
danger `#ef4444`.
Severity ramp: critical `#dc2626`, high `#ea580c`, medium `#d97706`,
**low `#0284c7` (blue)**, info `#64748b`. AA text variants:
critical-text `#b91c1c`, medium-text `#b45309`.
Provider brand: aws `#FF9900`, azure `#0078D4`, gcp `#4285F4`, oci `#C74634`,
ibm `#0F62FE`, k8s `#326CE5`.
Radii: 8 / 12 / 16 (buttons+inputs 6, badges 4–5, cards 12).
Shadows (two-layer slate): `0 1px 2px rgba(15,23,42,.04), 0 1px 3px
rgba(15,23,42,.06)`; lg `0 4px 6px rgba(15,23,42,.04), 0 12px 28px
rgba(15,23,42,.12)`. Popovers `0 8px 32px rgba(0,0,0,.25)`.
Motion: 100ms hover / 200ms drawers+tabs / 350ms sidebar,
`cubic-bezier(.4,0,.2,1)`; all 0ms under prefers-reduced-motion.

## Typography

Inter (300–800) with `font-feature-settings: 'cv02','cv03','cv04','cv11'`
and **global `font-variant-numeric: tabular-nums`** on body.
JetBrains Mono only for identifiers. Practical scale:
**11 / 12 / 13 / 15 / 22 px** (+ 24px/700 KPI values, lh 1.1).
Page title 22/700/−0.02em; panel heading 15/600/−0.01em; table header
11/700/+0.055em UPPERCASE; body 13/400/1.6; meta 12/400; cell primary
12/500; cell sub 11. No light weights anywhere.

## The chip formula (one formula, all chips)

`bg = color @ 12% · border = 1px solid color @ 30% · text = color @ 100%`,
radius 5, 11px/700, padding `2px 8px 2px 6px`, icon 11–12px at
`strokeWidth 2.5`. Severity always icon + label (AlertOctagon / AlertTriangle
/ Minus / Info), never color-only. Low-signal false booleans render `—`
(never a "No" chip); null cells render `—` 11px muted — never blank.

## Table anatomy (DataTable)

- Frame: `rounded-lg border #e5e9f0`, table bg `#ffffff`. Inside a
  Panel/Card the table drops its own frame (single border, always).
- Sticky header band `#eef2f7`, th 11/700/0.055em uppercase `#4a6280`,
  column borders right, sort arrows `opacity 0` until header hover,
  accent when active. Draggable/resizable headers.
- Density toggle (persisted): rows 32px compact / 48 comfortable / 56
  spacious (`px-3 py-2 text-xs` compact).
- Two-line cell skeleton everywhere: primary 12/500 `#0f172a` + secondary
  11 `#6b849e` (mono for ids/ARN tails, absolute date under relative age).
- **3px severity stripe on the row's left border**; hover bg `#f6f8fb`;
  selected `rgba(59,130,246,.06)`; row actions `opacity 0` until hover.
- Canonical column order + declared px widths: Provider 88 → Account 150 →
  Region 100 (hidden) → Severity 88 → Asset 220 → Finding 240 → …extras… →
  Risk 78 (right) → Status 88 → First/Last scan 100.
- Toolbar: search `pl-10` on `#eef2f7` + selects + row-count chip + saved
  views + columns + density segmented control + export. Per-column filter
  popovers (select/text/range/date, auto-detected).
- Pagination: separate bordered card below; active page `rgb(37,99,235)`.
- Age cells color-coded by recency (≤1d green, ≤7d `#eab308`, ≤30d
  `#f97316`, older red), absolute date on line 2.
- Four states mandatory: dense data / skeleton shimmer / actionable error /
  named empty state with next-step copy.

## Shell

Top bar 56px fixed, bg `#f7f9fb`, logo zone width = sidebar width (edges
align), ⌘K search button 260px, avatar 28px. Sidebar 240px default
(collapse 64, drag-resize to 380): section labels 11/700/0.12em uppercase,
items 14px/500 with 18px icons, active = `#e4eefe` bg + `#2563eb` text +
3px accent left border (inactive rows reserve 3px transparent — nothing
shifts), count pills 11/700 rounded-full. Main content `p-6`.
PageHeader: breadcrumb 12px → 22/700 title with 22px accent icon →
12px `#4a6280` subtitle → right actions (primary = accent bg, rest
`#f6f8fb` bordered). Tabs: underline style, `-mb-px`, active accent text +
border-current, count pills tabular.

## Drawer (detail panel)

Right-anchored 640px, scrim `rgba(0,0,0,.4)`, slide-in 200ms, focus trap,
Esc closes. Header: severity chip + title + tiny meta chips (`#eef2f7`,
mono for ids) + right mono finding id. Underline tabs (Overview / Evidence
/ Compliance / Remediation pattern). Field rows: fixed 128px 12px/500 muted
label left, right-aligned value (mono + copy button for ids). Missing data:
dashed-border placeholder box.

## Charts (Recharts, defined once)

No axis lines, no tick lines, dashed horizontal-only grid `#cdd6e2`, ticks
11px `#4a6280`, `isAnimationActive false`, `dot false`, strokes 1.5–1.8,
area gradients 0.35→0.02, bars always sorted desc (radius 4), donut
inner/outer 60/90 pad 2 with center total (20px/700 over 12px "Total"),
legend dots 8px + "Label: count". Tooltip: white card, border `#e5e9f0`,
radius 8, 12px.

## KPI (Stat)

label 12 `#4a6280` → value 24/700 `#0f172a` lh 1.1 (never colored, never
resized) → delta arrow 12px colored by semantics → sublabel 12 `#6b849e`.
