import { describe, expect, it } from "vitest";
import { cornerFor, fromPlacement, occludes, toPlacement } from "./placement";
import { MIN_VIEWPORT, PANEL, VIEWPORT_PAD } from "./layout-metrics";

const BIG = { w: 2560, h: 1440 };
const SMALL = MIN_VIEWPORT; // 1280 x 720
const list = { w: PANEL.list.w, h: 400 };

describe("cornerFor", () => {
  it("reads the panel's centre, not its top-left", () => {
    // Left edge just past the midpoint: visually a right-hand panel, and
    // anchoring it left would walk it inward every time the window narrowed.
    const at = { left: BIG.w / 2 + 10, top: 100 };
    expect(cornerFor(at, list, BIG)).toBe("tr");
  });

  it("picks each of the four corners", () => {
    expect(cornerFor({ left: 20, top: 20 }, list, BIG)).toBe("tl");
    expect(cornerFor({ left: BIG.w - 320, top: 20 }, list, BIG)).toBe("tr");
    expect(cornerFor({ left: 20, top: BIG.h - 440 }, list, BIG)).toBe("bl");
    expect(cornerFor({ left: BIG.w - 320, top: BIG.h - 440 }, list, BIG)).toBe("br");
  });
});

describe("toPlacement / fromPlacement", () => {
  it("round-trips at the same viewport", () => {
    const at = { left: 900, top: 300 };
    expect(fromPlacement(toPlacement(at, list, BIG), list, BIG)).toEqual(at);
  });

  it("round-trips against every corner", () => {
    for (const at of [
      { left: 40, top: 40 },
      { left: BIG.w - list.w - 40, top: 40 },
      { left: 40, top: BIG.h - list.h - 40 },
      { left: BIG.w - list.w - 40, top: BIG.h - list.h - 40 },
    ]) {
      expect(fromPlacement(toPlacement(at, list, BIG), list, BIG)).toEqual(at);
    }
  });

  it("keeps a right-anchored panel the same distance from the right edge", () => {
    // The whole point. 24px in from the right on a 2560px monitor is 24px in
    // from the right on a 1280px laptop, not 1304px off the screen.
    const at = { left: BIG.w - list.w - 24, top: 60 };
    const p = toPlacement(at, list, BIG);
    expect(p.corner).toBe("tr");
    expect(p.dx).toBe(24);
    expect(fromPlacement(p, list, SMALL).left).toBe(SMALL.w - list.w - 24);
  });

  it("keeps a bottom-anchored panel the same distance from the bottom", () => {
    const at = { left: 60, top: BIG.h - list.h - 32 };
    const p = toPlacement(at, list, BIG);
    expect(p.corner).toBe("bl");
    expect(p.dy).toBe(32);
    expect(fromPlacement(p, list, SMALL).top).toBe(SMALL.h - list.h - 32);
  });

  /* The regression this module exists for: a raw {x, y} saved on a wide screen
     restores off the edge of a narrow one, and the panel is simply gone. */
  it("restores on screen and reachable when the viewport shrinks", () => {
    const at = { left: 1900, top: 1100 };
    const p = toPlacement(at, list, BIG);
    const back = fromPlacement(p, list, SMALL);
    expect(back.left).toBeGreaterThanOrEqual(VIEWPORT_PAD);
    expect(back.top).toBeGreaterThanOrEqual(VIEWPORT_PAD);
    expect(back.left + list.w).toBeLessThanOrEqual(SMALL.w - VIEWPORT_PAD);
    expect(back.top + list.h).toBeLessThanOrEqual(SMALL.h - VIEWPORT_PAD);
  });

  it("never restores a panel off screen, from any corner, at any size", () => {
    const views = [BIG, SMALL, { w: 1024, h: 640 }, { w: 800, h: 600 }];
    for (const from of views) {
      for (const at of [
        { left: 0, top: 0 },
        { left: from.w - list.w, top: 0 },
        { left: 0, top: from.h - list.h },
        { left: from.w - list.w, top: from.h - list.h },
      ]) {
        const p = toPlacement(at, list, from);
        for (const to of views) {
          const back = fromPlacement(p, list, to);
          expect(back.left).toBeGreaterThanOrEqual(VIEWPORT_PAD);
          expect(back.top).toBeGreaterThanOrEqual(VIEWPORT_PAD);
        }
      }
    }
  });

  it("keeps the header under the cursor when the panel is wider than the window", () => {
    const wide = { w: 900, h: 400 };
    const tiny = { w: 500, h: 300 };
    const back = fromPlacement({ corner: "tr", dx: 20, dy: 20 }, wide, tiny);
    // Clamped to the padding and allowed to overflow, rather than pushed
    // off-screen left — the drag handle and close button live at the top.
    expect(back.left).toBe(VIEWPORT_PAD);
    expect(back.top).toBe(VIEWPORT_PAD);
  });

  /* A drag that ends past an edge must not be stored as "beyond the window".
     `fromPlacement` would clamp it back on every restore, so nothing visibly
     breaks — but the document would then record the overshoot rather than the
     panel, and the two differ by however far the cursor went. */
  it("clamps an overshot drop before storing it", () => {
    const p = toPlacement({ left: BIG.w - 100, top: 40 }, list, BIG);
    expect(p.dx).toBeGreaterThanOrEqual(0);
    expect(p.dy).toBeGreaterThanOrEqual(0);
    expect(fromPlacement(p, list, BIG).left + list.w).toBeLessThanOrEqual(BIG.w - VIEWPORT_PAD);
  });

  it("never stores a negative offset, from any overshoot", () => {
    for (const at of [
      { left: -400, top: -400 },
      { left: BIG.w + 200, top: BIG.h + 200 },
      { left: -50, top: BIG.h + 50 },
    ]) {
      const p = toPlacement(at, list, BIG);
      expect(p.dx).toBeGreaterThanOrEqual(0);
      expect(p.dy).toBeGreaterThanOrEqual(0);
    }
  });

  it("rounds offsets, so a stored document has no float noise", () => {
    const p = toPlacement({ left: 100.4, top: 200.6 }, list, BIG);
    expect(Number.isInteger(p.dx)).toBe(true);
    expect(Number.isInteger(p.dy)).toBe(true);
  });

  it("holds both panel widths the console actually uses", () => {
    for (const size of [PANEL.list, PANEL.detail]) {
      const panel = { w: size.w, h: size.maxH };
      const at = { left: BIG.w - panel.w - 40, top: 40 };
      const back = fromPlacement(toPlacement(at, panel, BIG), panel, SMALL);
      expect(back.left + panel.w).toBeLessThanOrEqual(SMALL.w - VIEWPORT_PAD);
    }
  });
});

describe("occludes", () => {
  it("is true only for near-total overlap", () => {
    expect(occludes({ left: 100, top: 100 }, { left: 104, top: 103 }, list)).toBe(true);
  });

  it("leaves a deliberate tile alone", () => {
    // Two panels a reader arranged side by side must not be shuffled apart.
    expect(occludes({ left: 100, top: 100 }, { left: 140, top: 100 }, list)).toBe(false);
  });
});
