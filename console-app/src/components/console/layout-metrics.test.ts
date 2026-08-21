/**
 * Sizing, and the one rung no real estate has reached.
 *
 * `layout-metrics.ts` is pure arithmetic — no React, no DOM. The summary rung
 * is the reason this exists: it triggers past 18 siblings and this estate has
 * at most four, so the only way to know it works is to hand it a number no real
 * account has produced yet.
 *
 * Ported from `scripts/check-layout-metrics.mjs`, which ran under
 * `--experimental-strip-types` and could not import a `.tsx` file — which is
 * where the defects actually were.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ASPECT,
  CHIP_W,
  EDGE_GAP,
  LAYER_GAP,
  RAIL_V,
  railClearance,
  PANEL,
  PANEL_GAP,
  VIEWPORT_PAD,
  MIN_VIEWPORT,
  placePanel,
  RAIL_TAB_LEN,
  VISIBLE,
  chooseColumns,
  measureChip,
  measureContainer,
  measureGroup,
} from "./layout-metrics";

const GRID_MAX = 18; // must match architecture.tsx
const SUMMARY_KEEP = 6;

/* ── the rung ladder ───────────────────────────────────────────────────── */
describe("how many siblings before the drawing changes shape", () => {
  const rung = (k: number) => (k > GRID_MAX ? "summary" : k <= 6 ? "row" : "grid");

  it("draws a few in a row", () => expect(rung(4)).toBe("row"));
  it("wraps a dozen into a grid", () => expect(rung(12)).toBe("grid"));
  it("summarises past the grid maximum", () => expect(rung(40)).toBe("summary"));
  it("keeps the heaviest few in a summary, plus a count", () => {
    expect(Math.min(40, SUMMARY_KEEP)).toBe(SUMMARY_KEEP);
  });
});

/* ── bottom-up sizing ──────────────────────────────────────────────────── */
describe("a parent is as big as its children, never less", () => {
  const chip = measureChip();
  const group = measureGroup(Array.from({ length: 9 }, () => chip));

  it("is one row high whatever it holds", () => {
    // The whole reason a band's columns line up. These two assertions used to
    // compare `measureGroup(3)` against itself and `9` against `40 + 1`, which
    // pass for any implementation at all — the property was untested while the
    // renderer changed underneath it.
    const heights = [1, 3, 5, 9, 40, 400].map(
      (n) => measureGroup(Array.from({ length: n }, () => chip)).h,
    );
    expect(new Set(heights).size).toBe(1);
  });

  it("is shorter than the chips it stands for", () => {
    // A tile that grew with its members is what put a 26-instance group and a
    // 1-instance group at different heights in the same row.
    expect(group.h).toBeLessThan(chip.h * 3);
  });

  it("makes a container wider than one child", () => {
    expect(measureContainer([group, group, group]).w).toBeGreaterThan(group.w);
  });

  it("makes a container taller than one child", () => {
    expect(measureContainer([group, group, group]).h).toBeGreaterThan(group.h);
  });
});

/* ── column choice ─────────────────────────────────────────────────────── */
describe("column choice", () => {
  const group = measureGroup(Array.from({ length: 9 }, () => measureChip()));

  it.each([2, 3, 5, 9, 17, 33])("picks a landscape-ish grid for %i children", (n) => {
    const kids = Array.from({ length: n }, () => group);
    const cols = chooseColumns(kids);
    const rows = Math.ceil(n / cols);
    const ratio = (cols * group.w) / (rows * group.h);
    expect(Math.abs(Math.log(ratio / ASPECT))).toBeLessThan(1.2);
  });

  it("gives the same answer every time", () => {
    const kids = Array.from({ length: 7 }, () => group);
    expect(new Set(Array.from({ length: 50 }, () => chooseColumns(kids))).size).toBe(1);
  });
});

/* ── no Tailwind class may be built at runtime ─────────────────────────
   The JIT scans source TEXT for class names it can resolve, so
   `bg-[color-mix(...${n}%...)]` produces no CSS rule at all. It type-checks, it
   renders, the attribute appears in the HTML, and the box has no background.
   Nothing in the toolchain says a word.

   Interpolation inside an arbitrary-value bracket is the tell. */
describe("the source itself", () => {
  it.each(["../../routes/architecture.tsx", "./decide.ts"])(
    "builds no Tailwind arbitrary value at runtime in %s",
    (file) => {
      const source = readFileSync(new URL(file, import.meta.url), "utf8");
      const runtime = [...source.matchAll(/[a-z-]+-\[[^\]]*\$\{[^}]*\}[^\]]*\]/g)].map((m) => m[0]);
      expect(runtime).toEqual([]);
    },
  );
});

/* ── rails must not collide with anything ──────────────────────────────
   A tab lies wholly outside the box it names, so the box reserves room for it.
   Multi-layer arms are why this has to be computed: the west wall runs two
   deep, and the fixed 64px that fitted one layer overlaps at two. */
describe("how much room an arm needs", () => {
  it("charges nothing for an arm that carries nothing", () => {
    // Otherwise every box is indented for three rails it does not have.
    for (const side of ["n", "s", "e", "w"] as const) {
      expect(railClearance(side, 0)).toBe(0);
      expect(railClearance(side, -1)).toBe(0);
    }
  });

  it("reserves the same on every side, because a tab is one thickness", () => {
    // It used to charge 40 out from a side wall and 20 below a line, so the
    // same object drew twice as thick on the east as on the north and read as
    // two kinds of tab. Depth is the dimension a tab does not use to say
    // anything: the label runs ALONG the border, so across it there is only
    // ever one line of text, whichever way it is turned.
    const sides = ["n", "s", "e", "w"] as const;
    const one = sides.map((side) => railClearance(side, 1));
    expect(new Set(one).size).toBe(1);
    const two = sides.map((side) => railClearance(side, 2));
    expect(new Set(two).size).toBe(1);
  });

  it("grows by a layer plus a gap, not by a whole fresh reservation", () => {
    // The outer gap is paid once; only the tabs and the gaps between them
    // repeat. Charging EDGE_GAP per layer would double-count it.
    const one = railClearance("w", 1);
    const two = railClearance("w", 2);
    expect(two - one).toBe(RAIL_V + LAYER_GAP);
    expect(two).toBeLessThan(one * 2);
  });

  it("fits the tabs it reserves for, with the outer gap left over", () => {
    for (const layers of [1, 2, 3]) {
      const room = railClearance("w", layers);
      const tabs = layers * RAIL_V + (layers - 1) * LAYER_GAP;
      expect(room - tabs).toBe(EDGE_GAP);
    }
  });

  it("reserves enough for the two-layer west wall this estate needs", () => {
    // Ten tabs at the region, five per layer. The old fixed 64px was chosen
    // when the wall was one layer deep; at two it overlaps the box.
    expect(railClearance("w", 2)).toBeGreaterThan(64);
  });

  it("separates two siblings that both carry rails", () => {
    // Both reservations are margins, so the gap between the boxes is their
    // sum — neither can reach into the other whatever it carries.
    expect(railClearance("e", 1) + railClearance("w", 2)).toBeGreaterThanOrEqual(RAIL_V * 3);
  });
});

/* ── overlay panels ────────────────────────────────────────────────────
   Fixed widths, ceilinged heights — and both have to survive the smallest
   window we claim to support. These numbers were previously written twice
   each, once in markup and once in the placement call, with nothing
   comparing them. */

describe("panels fit the window we claim to support", () => {
  it("leaves the diagram visible with a list and its detail both open", () => {
    /* The tightest case on screen: a list opened from a wall, its detail
       docked beside it, and the estate still readable behind them. "Readable"
       is not a feeling — it is at least two chips side by side, which is the
       narrowest thing on the canvas that still carries two resource names. */
    const used = PANEL.list.w + PANEL_GAP + PANEL.detail.w + VIEWPORT_PAD * 2;

    expect(used + CHIP_W * 2).toBeLessThanOrEqual(MIN_VIEWPORT.w);
  });

  it("never asks for a height the window cannot give", () => {
    for (const panel of Object.values(PANEL)) {
      expect(panel.maxH + VIEWPORT_PAD * 2).toBeLessThanOrEqual(MIN_VIEWPORT.h);
    }
  });

  it("keeps the detail panel wider than the list it docks beside", () => {
    // The list carries names; the detail carries a two-column field grid, a
    // contained list and a connection tree. Equal widths made the detail the
    // cramped one, which is the wrong way round.
    expect(PANEL.detail.w).toBeGreaterThan(PANEL.list.w);
  });

  it("keeps every panel wider than a chip, so a name is not the thing that gives", () => {
    for (const panel of Object.values(PANEL)) {
      expect(panel.w).toBeGreaterThan(CHIP_W);
    }
  });
});

/* ── where a panel opens ───────────────────────────────────────────────
   The rule that decides whether a reader can see the thing they clicked.
   Pure, so it is checkable here rather than by opening the page and looking. */

describe("placePanel", () => {
  const view = { w: 1280, h: 720 };
  const tile = { x: 400, y: 300, w: 190, h: 26 };
  const list = { w: PANEL.list.w, h: PANEL.list.maxH };

  /* A window with room to spare, so these two assert the RULE rather than the
     clamp. At the 720px minimum a 460px panel can only be anchored in the top
     248px, so every anchor below that is clamped and the rule is invisible —
     which is worth knowing, and is what the clamp tests below cover. */
  const roomy = { w: 1600, h: 1400 };

  it("opens ON a thing that sits in the diagram", () => {
    // A tile, a heading, a container name: what the panel covers is what the
    // panel is about, so covering it costs nothing.
    expect(placePanel(tile, list, undefined, roomy)).toEqual({ left: 400, top: 300 });
  });

  it("opens OUTWARD from the border a tab rides", () => {
    const wall = { x: 500, y: 600, w: RAIL_V, h: RAIL_TAB_LEN };

    expect(placePanel(wall, list, "e", roomy).left).toBe(500 + RAIL_V + PANEL_GAP);
    expect(placePanel(wall, list, "w", roomy).left).toBe(500 - PANEL.list.w - PANEL_GAP);
    expect(placePanel(wall, list, "s", roomy).top).toBe(600 + RAIL_TAB_LEN + PANEL_GAP);
    expect(placePanel(wall, list, "n", roomy).top).toBe(600 - PANEL.list.maxH - PANEL_GAP);
  });

  it("flips to the far side rather than landing on its own parent", () => {
    /* The case that sent a detail panel onto the list that produced it: a list
       opened from an east wall sits at the right edge, its detail has nowhere
       further right to go, and clamping put it over the rows the reader is
       moving between. */
    const atRightEdge = {
      x: view.w - PANEL.list.w - VIEWPORT_PAD,
      y: 100,
      w: PANEL.list.w,
      h: 400,
    };
    const detail = { w: PANEL.detail.w, h: PANEL.detail.maxH };

    const placed = placePanel(atRightEdge, detail, "e", view);

    expect(placed.left + PANEL.detail.w).toBeLessThanOrEqual(atRightEdge.x);
  });

  it("flips upward when there is no room below", () => {
    const nearFoot = { x: 100, y: view.h - 60, w: 190, h: 26 };

    const placed = placePanel(nearFoot, list, "s", view);

    expect(placed.top + PANEL.list.maxH).toBeLessThanOrEqual(nearFoot.y);
  });

  it("clamps to the window when neither side fits", () => {
    // Last resort: a panel pushed back on screen has lost its anchor, but a
    // panel off screen has lost everything.
    const tiny = { w: 400, h: 300 };
    const placed = placePanel({ x: 380, y: 10, w: 10, h: 10 }, { w: 360, h: 280 }, "e", tiny);

    expect(placed.left).toBeGreaterThanOrEqual(VIEWPORT_PAD);
    expect(placed.left + 360).toBeLessThanOrEqual(tiny.w - VIEWPORT_PAD);
  });

  it("never places a panel off screen, from any anchor on the page", () => {
    const detail = { w: PANEL.detail.w, h: PANEL.detail.maxH };
    for (const side of [undefined, "n", "s", "e", "w"] as const) {
      for (let x = 0; x <= view.w; x += 80) {
        for (let y = 0; y <= view.h; y += 60) {
          const p = placePanel({ x, y, w: 26, h: 150 }, detail, side, view);
          expect(p.left).toBeGreaterThanOrEqual(VIEWPORT_PAD);
          expect(p.top).toBeGreaterThanOrEqual(VIEWPORT_PAD);
          expect(p.left + detail.w).toBeLessThanOrEqual(view.w - VIEWPORT_PAD);
          expect(p.top + detail.h).toBeLessThanOrEqual(view.h - VIEWPORT_PAD);
        }
      }
    }
  });
});
