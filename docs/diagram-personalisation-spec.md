# Diagram personalisation — reorder, pinning, and saved preferences

Status: **plan, not built.** Written to be decided on, not to be implemented as-is.

Companion to [diagram-layout-spec.md](diagram-layout-spec.md). That document says
where a box goes and why. This one says what a *reader* is allowed to change
about it, what survives a rescan, and what must not be negotiable.

---

## 1. What is being asked for

Five capabilities, in the user's words:

1. Reposition the boxes inside their scope container so they sit in the
   reader's own sequence, and keep that sequence on the next scan.
2. Pin the list panel and the detail panel so they stop disappearing.
3. **Drag a panel anywhere on screen**, and have it come back to that exact
   place next session.
4. Pin and unpin connection lines.
5. One button that pins every panel, expands every list, and shows every
   connection at once.
6. A **save preferences** action, so positioning, panels and connections come
   back the same way next time.

All six are buildable. One needs reframing before it is (§3), one has a
legibility cliff that changes its shape (§6), and the whole set depends on a
storage substrate that does not exist yet (§7).

Note the asymmetry between (1) and (3), because it is the load-bearing idea in
this plan: **a box may not be freely placed, a panel may.** A box is placement,
which the engine owns; a panel is an overlay, which it does not. §2 and §4b.

---

## 2. The constraint everything must respect

The diagram has **no coordinates**. This is not an omission.

- Sizes are computed bottom-up from content — `measureChip` → `measureGroup` →
  `measureContainer` in [layout-metrics.ts](../console-app/src/components/console/layout-metrics.ts).
- Lane packing is pure arithmetic over those measured heights —
  `allocate` / `packRows` / `splitLane` in [pack.ts](../console-app/src/components/console/pack.ts).
- The renderer draws CSS grid and flex. Nothing on the canvas is absolutely
  positioned except overlays.
- §10 of the layout spec makes determinism a contract: every sort key is total,
  and there is a test suite that runs layout under three hash seeds to prove one
  estate renders one diagram.

The line the codebase already draws, and that this plan keeps:

> **Measurement for an overlay is not measurement for placement.**
> — [trace.ts](../console-app/src/components/console/trace.ts)

Overlays (traces, panels, lights) may read the DOM freely. Placement may not.
Every feature below is either an **overlay** (free) or an **ordering override**
(constrained). None of them introduces a stored coordinate for a box.

---

## 3. Reposition → reorder (the reframe)

### Why not free X/Y drag

Storing `{x, y}` per box would fork the layout engine permanently:

| Problem | What happens |
|---|---|
| Boxes resize between scans | A subnet gains four resources, grows 90px, and now overlaps the saved neighbour. Nothing can repair it — the engine no longer owns placement. |
| Determinism dies | `to_dict()` emits children in position order and a renderer that iterates naively is correct by default. Saved coordinates make that false. |
| Export diverges | Print, PNG and Mermaid export all re-derive from the tree. They would need the preference blob too, or produce a different picture than the screen. |
| Responsive breaks | The grid currently reflows at any width. Absolute coordinates do not. |

### What to build instead

The request is *"position with their sequence"* — that is **order**, not
geometry. So: **drag a box into a different slot among its siblings**, and
persist a per-container ordering override. The engine keeps sizing, packing and
wrapping; the reader only overrides the sort.

Same outcome the user described. Cannot overlap. Cannot go stale. Still exports.

### Where it hooks in

Four ordering decisions exist in [architecture.tsx](../console-app/src/routes/architecture.tsx),
and all four route through one override function:

| Site | Line | Orders |
|---|---|---|
| `units.sort(byRank)` | [1474](../console-app/src/routes/architecture.tsx#L1474) | **Primary.** Sub-containers, rule wraps, clusters and service groups in one rank-ordered pass |
| `ordered` | [1285](../console-app/src/routes/architecture.tsx#L1285) | Flow children before they are bucketed into rows |
| `packRows(shapes, cols, budget)` | [1510](../console-app/src/routes/architecture.tsx#L1510) | Category lanes within a band |
| `SiblingRow` | [1846](../console-app/src/routes/architecture.tsx#L1846) | Availability zones as uniform columns |

Proposed shape — one pure function, testable without a browser:

```
applyOrder(containerKey, units) → units
  // saved keys first, in saved order
  // unsaved keys after, in engine order (rank, then the existing tie-break)
```

Placed immediately after `units.sort(byRank)`, it inherits the engine's answer
whenever there is no preference. **No preference means no behaviour change** —
that is the acceptance test.

### One defect to fix first

Zone rows are keyed `zones-${i}` at [line 1418](../console-app/src/routes/architecture.tsx#L1418)
— an array index. It changes when a filter hides a container, so a saved order
referencing it would rebind to the wrong row. Must become content-derived
(the sorted member keys, joined) before any order is persisted against it.

Every other unit key is already stable: `node.key`, `rule.key`, the cluster
name, and `groupOf(n)` for service groups.

### Scope of the drag

- **Within one parent only.** Dragging a subnet out of its VPC would assert a
  containment that is not true. The drop target is the sibling list, nothing else.
- **Lanes and zones reorder as units**, not by dragging individual chips.
- Keyboard equivalent required (`Alt+←/→` on a focused box) — a drag-only
  affordance is not operable.

---

## 4. Panels: pin, place, and restore

### What is there now

Both are **singletons**, deliberately. [Lines 746–772](../console-app/src/routes/architecture.tsx#L746-L772):
opening a preview closes the list, selecting a node closes both. The stated
reason — *"one floating rung at a time … two of them on screen at once is two
answers to one question"* — is a real argument, and pinning is the explicit
decision to overrule it for readers who want a comparison view.

### What makes this cheaper than expected

The layout spec says the list renders `absolute inset-0` over its container.
**The implementation has already moved past that.** `InlineList` and
`NodePreview` are `position: fixed`, portalled to `document.body`, and anchored
to the clicked element's measured rect via `useAnchored`
([2899](../console-app/src/routes/architecture.tsx#L2899), [3020](../console-app/src/routes/architecture.tsx#L3020)).

They are already floating cards with real coordinates. Pinning is therefore
mostly a **state** change, not a layout one. *(The spec paragraph at
`diagram-layout-spec.md` §5 needs correcting either way.)*

### The change

Replace the two singletons with one registry:

```
panels: Map<panelId, {
  kind: "list" | "detail",
  subject: string,        // host key, or node key
  place: Placement,       // see §4b — never raw {x, y}
  pinned: boolean,
  collapsed: boolean,
  z: number,
}>
```

- Unpinned panels keep today's behaviour exactly: one at a time, opening one
  closes the others, anchored to whatever was clicked.
- Pinned panels persist across selection, filter changes and scroll.
- A pinned panel gets a **drag handle on its header** and a collapse chevron.
- Cap the pinned count (proposed: **6**) with a stated message. Ten floating
  cards is not a comparison view.
- **z-order** is click-to-front, and stored.

### The full sheet stays as it is

`NodeSheet` is a right-docked shadcn `Sheet` with a scrim — a different
component from the two floating cards, and modal by construction. Recommend it
**stays unpinnable and unplaceable**, since `NodePreview` already renders the
identical body (`NodeBody`) as a floating card. Making a modal draggable is a
third interaction model for the same content.

---

## 4b. Free placement — and what a saved position actually means

This is the part with hidden depth, so it gets its own section.

### Why a panel may be freely placed when a box may not

A panel is `position: fixed`, portalled to `document.body`, and overlaps nothing
the layout engine owns. Moving it cannot cause an overlap the engine has to
repair, cannot change what is drawn, and cannot desynchronise an export. A stale
panel position is also **self-evident and self-fixing** — the reader sees it in
the wrong place and drags it. A stale box coordinate is neither.

So free X/Y is correct here and wrong in §3, and that is not inconsistency —
it is the overlay/placement line from §2 doing its job.

### Raw `{x, y}` is the wrong thing to store

Today's position comes from `place()`
([3101](../console-app/src/routes/architecture.tsx#L3101)), which clamps against
`window.innerWidth` / `window.innerHeight`. Those are **viewport coordinates**,
and the viewport is not the same thing twice:

| Between sessions | What raw coordinates do |
|---|---|
| 2560px monitor → 1440px laptop | A panel saved at `x: 1900` restores entirely off-screen |
| Window resized, or a sidebar opened | Panel drifts away from where it was placed relative to the edge |
| Browser zoom changed | CSS pixels change meaning; the panel lands somewhere else |

### Store a corner and an offset

The rule window managers use, and the one that matches how people actually
think about placement — *"I put it in the top right"*:

```
Placement = {
  corner: "tl" | "tr" | "bl" | "br",   // nearest at drop time
  dx: number,                          // px from that corner, horizontally
  dy: number,                          // px from that corner, vertically
}
```

- On drop, resolve the nearest corner and store the offset from it.
- On restore, resolve back against the *current* viewport, then **clamp** so at
  least the header bar and the close button are on screen — a panel that
  restores unreachable is worse than one that restores in the wrong place.
- A panel placed top-right comes back top-right on any screen. A panel placed
  in the middle of a wide monitor lands sensibly on a laptop instead of off it.

Proportional (`x / vw`) was the alternative and is worse: it stretches the gaps
between panels on a wide screen and squashes them on a narrow one, so a reader
who arranged three panels side by side gets them overlapping or scattered.

### Two memories, not one

*"Next time we will follow same"* means two different things, and both are wanted:

| | Remembers | Restores |
|---|---|---|
| **Per-subject placement** | where the panel for *this* subject was last put | on next open, in this or any session |
| **Session restore** | which panels were pinned, and where | automatically on load |

Rule: **pinned panels restore open; unpinned panels only remember their spot.**
Opening the VPC's list again puts it back where you last dragged it, without
five panels reappearing on every page load.

### Fixed to the viewport, not to the canvas

Panels stay `position: fixed` — they do not scroll with the diagram. That is
right for a workspace panel you placed deliberately, and it creates one gap: a
pinned panel about a box you have since scrolled away from now floats over
unrelated diagram.

Fix with a **locate affordance** on the panel header — click the subject name,
the canvas scrolls the subject into view and flashes it. Cheap, and it uses
machinery that exists (`data-node` attributes, the `HoverLight` stylesheet).

### Restore collisions

Two panels can restore to overlapping positions if the viewport shrank enough
that clamping pushed them together. Trust the reader's arrangement first —
restore as saved, clamp only for reachability. Apply a cascade offset **only**
to a panel that would land fully occluded by another, so it is discoverable
rather than invisible.

### Escape hatch

"Reset panel positions" as its own action, separate from the global preference
reset in §7. Rearranging six panels into a bad state should not cost the reader
their saved diagram order too.

---

## 5. Pinning connections

**Cheapest item in the set.** The geometry is already written and already
tested headlessly: `curve()` returns the bezier plus the label midpoint,
`tracesFrom()` resolves arrowhead direction, and `relativeTo()` handles the
scroll-offset correction. All in [trace.ts](../console-app/src/components/console/trace.ts).

`HoverTraces` ([2643](../console-app/src/routes/architecture.tsx#L2643)) already
does the hard part: it derives the lit set from `connectionsOf()` rather than
reading opacity back off the page, and it tallies multi-member elements so one
tab standing for four interfaces draws `protected-by ×4` rather than a bare line.

### The change

1. A `pinnedTraces: Set<sourceKey>` beside `hovered`. The effect unions
   `hovered` with every pinned key.
2. **Re-measurement on scroll and resize.** Today the effect depends on
   `[hovered]` alone. That is correct for a transient hover; a pinned trace must
   survive the reader scrolling, so it needs a `ResizeObserver` on the canvas
   plus a throttled scroll listener. This is the only real engineering in the item.
3. Pinned traces render in a **calmer register** than hover ones — solid rather
   than dashed, lower opacity — so "what I asked to keep" and "what I am
   pointing at right now" stay distinguishable.
4. Unpin via click on the line, plus a global clear.

### The interaction that has to be resolved

`HoverLight` ([2789](../console-app/src/routes/architecture.tsx#L2789)) drops
every non-lit node to `opacity: .2`. With pinned traces present, a hover would
dim the boxes that pinned lines point at, and the lines would appear to point at
nothing.

**Rule:** pinned endpoints are never dimmed. One extra clause in the generated
stylesheet — cheap, but it must be stated or the feature reads as broken.

---

## 6. The "show everything" button

Feasible. **Not as a single global switch.**

On the live estate — 513 nodes, ~1,030 chips — "every panel pinned + every list
expanded + every connection drawn" produces:

- more pinned cards than the screen holds, each one covering diagram;
- a connection hairball with no readable path through it;
- a paint the browser feels, on every scroll, because pinned traces re-measure.

And the failure is self-defeating: the reader pressed a button asking to *see
more* and the diagram underneath disappeared.

### The shape to build instead

**Three independent toggles, each scoped.**

| Toggle | Scope | Cap |
|---|---|---|
| Expand all lists | selected container, or current filter | pinned-panel cap (6) applies |
| Show all connections | selected container's subtree | stated cap, e.g. 200 edges, with the overflow counted in the UI |
| Pin all open panels | whatever is currently open | — |

Same button count for the user. Honest at 513 nodes, and each is independently
useful. If a global "everything, whole account" mode is still wanted, it belongs
behind an explicit confirm that states the node count.

**Non-negotiable:** any cap is **stated in the UI**, never applied silently. The
codebase already holds this line — `LIST_CAP` prints
`showing 250 of 1,030 — filter to narrow` rather than stopping quietly, because
*"a list that silently stops at 250 reads as 'that is all there is', which is the
one thing it must not say."*

---

## 7. Saved preferences

### The scope key

`SCENE.account` + `SCENE.region`. The scene is a build-time import
(`liveScene ?? sceneFromFixture()` in [mock-data.ts:1346](../console-app/src/lib/mock-data.ts#L1346)),
so a preference must never leak from a fixture session into a live one —
`IS_LIVE_SCENE` gates the write.

### The document

```
{
  version: 1,
  scope: "588989875114/ap-southeast-1",
  savedAt: "2026-08-19T...",
  order:   { [containerKey]: string[] },      // §3

  // §4 — pinned panels restore OPEN, in this arrangement
  panels:  [ { kind, subject, place, collapsed, z } ],

  // §4b — where a panel for this subject goes when opened, pinned or not.
  //        Outlives the panel being closed; that is the point.
  places:  { [subjectKey]: Placement },       // { corner, dx, dy }

  traces:  string[],                          // §5, pinned source keys
  filter:  { hidden: string[] },              // the existing `hidden` set
  toggles: { showArtifacts: boolean }
}
```

`panels` and `places` are deliberately separate. `panels` is *"this is my
workspace, bring it back"*; `places` is *"whenever you show me this VPC's list,
it goes here"*. Collapsing them into one would mean a panel had to stay pinned
to keep its position.

`filter` is included because it is the preference readers will miss first —
`QUIET_BY_DEFAULT` hides six categories on every load, and a reader who turns
them on re-does it every session.

### Storage

**v1: `localStorage`.** There is no persistence anywhere in the console today —
verified, zero `localStorage`/`sessionStorage` calls in `console-app/src`. One
key, one JSON blob, no backend, no migration.

**v2: an API record**, once there is a user identity to hang it on. The document
shape above is deliberately transport-agnostic so the move is a swap of two
functions, not a redesign.

### Surviving a rescan

Node keys are ARN- and ID-derived and minted deterministically in
[layers.py](../providers/aws/runtime/layers.py) — `account:{id}`,
`region:{account}/{region}`, `az:{vpc}/{zone}`, plus collected keys like
`ec2.instance:i-…`. A preference keyed on them survives a rescan for anything
whose identity survives. Three rules make that safe:

1. **Orphans drop silently.** Autoscaled instances and ENIs get new IDs each
   scan. A pinned panel or trace whose subject is gone is discarded on load, not
   errored on. Count them and say so once, in the reset affordance. A `places`
   entry for a vanished subject is harmless and can be garbage-collected lazily.
2. **New arrivals append.** A resource that did not exist when the order was
   saved goes *after* the saved ones, in engine rank order. Stated, so it is
   predictable rather than emergent.
3. **Version invalidates.** A change to how units are keyed bumps `version`, and
   an older document is dropped with a notice rather than partially applied.

### The affordance nobody asks for and everybody needs

A visible **"layout customised · reset"** indicator whenever a preference is
active. Without it, a reader with a six-month-old saved order sees a diagram
that disagrees with the engine and has no way to find out why. Reset restores
engine order, unpins everything, and clears the stored document.

---

## 8. Phasing

| Phase | Contents | Depends on | Rough size |
|---|---|---|---|
| **0** | Fix the `zones-${i}` key defect. Correct the stale `absolute inset-0` claim in the layout spec. | — | small |
| **1** | Preference substrate: document shape, versioning, load/save, scope gating, reset indicator. Wire the existing `hidden` filter through it as the first consumer. | 0 | medium |
| **2** | Sibling reorder — `applyOrder` at all four sites, drag affordance, keyboard equivalent, persisted. | 0, 1 | medium–large |
| **3** | Pinned connections — pinned set, scroll/resize re-measure, calm register, `HoverLight` exemption, persisted. | 1 | medium |
| **4** | Panel registry — pin, collapse, z-order, cap, persisted. | 1 | medium |
| **4b** | Free placement — drag handle, corner+offset codec, clamped restore, `places` vs `panels`, locate affordance, reset-positions. | 4 | medium |
| **5** | The three scoped toggles. | 3, 4 | small |

Phase 1 ships value alone (the filter stops resetting every session), and every
later phase stores into it. Phase 3 before 4 because it is cheaper and the
payoff is immediate.

4 and 4b are split because they fail differently: 4 is state plumbing against an
existing invariant, 4b is geometry and restore semantics. 4b could ship first as
placement-without-pinning (panels remember where they open, but still one at a
time) if that is the more wanted half.

---

## 9. Testing

Pure functions first, in the pattern the console already uses
(`pack.test.ts`, `layout-metrics.test.ts`, `trace.test.ts`, `decide.test.ts`):

- `applyOrder` — empty preference is identity; partial preference keeps engine
  order for the remainder; unknown keys are ignored; new keys append.
- Preference codec — round-trip, version rejection, orphan pruning.
- Trace geometry under scroll — already covered by `relativeTo`, extend for the
  pinned re-measure path.
- **Placement codec** (§4b) — `toPlacement(x, y, viewport)` picks the nearest
  corner; `fromPlacement(p, viewport)` round-trips at the same viewport size;
  a placement saved at 2560×1440 restores on-screen and reachable at 1280×720;
  a panel whose offset exceeds the viewport clamps to keep its header visible.
  Pure arithmetic, no DOM — same shape as the `pack.ts` tests.

And one **regression gate**, which is the important one:

> With no saved preference, the rendered diagram is byte-identical to today's.

That is what keeps §2 true.

---

## 10. Open decisions

1. **Reorder, not free X/Y** — §3. Recommended, and everything above assumes it.
   Free-drag is buildable but ends determinism, export parity and responsive
   reflow. It should be a deliberate choice, not a side effect.
2. **Corner + offset, not raw `{x, y}`** — §4b. Recommended. Raw coordinates
   restore off-screen the first time someone opens the console on a different
   monitor, which is the failure that makes people stop trusting saved layouts.
3. **Pinned panels restore open; unpinned ones only remember their spot** —
   §4b. The alternative is every panel you ever opened reappearing on load.
4. **Global "show everything"** — §6 recommends three scoped toggles instead.
   Confirm, or specify the confirm-with-node-count variant.
5. **`NodeSheet` stays unpinnable and unplaceable** — §4. Recommended, since
   `NodePreview` already renders the identical body.
6. **`localStorage` for v1** — §7. Confirm there is no near-term requirement for
   preferences to follow a user across machines. Note this bites hardest on
   §4b: placement saved on a work laptop will not appear on a home machine.
7. **Pinned-panel cap of 6, connection cap of 200** — both are starting numbers,
   not measured ones. Worth setting against a real session.
