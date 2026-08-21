/**
 * Where a reader put a panel, expressed so it survives a different screen.
 *
 * `placePanel` in `layout-metrics.ts` answers where a panel OPENS — beside the
 * tab that summoned it, flipped if there is no room. This module answers where
 * a panel STAYS, once a reader has dragged it somewhere deliberate and asked
 * for that to be remembered.
 *
 * The two are different problems. An opening position is derived from something
 * on screen right now, so it can be recomputed from scratch every time. A saved
 * position has to outlive the session, the window size, and usually the
 * monitor — and a viewport coordinate does not. A panel dropped at `x: 1900` on
 * a 2560px display restores off-screen on a 1440px laptop, and a reader whose
 * saved layout vanishes once does not save another.
 *
 * So a placement is a CORNER and an OFFSET, which is what window managers store
 * and what people actually mean: "I put it in the top right". A panel placed
 * top-right comes back top-right at any size.
 *
 * The alternative considered was proportional — `x / vw`, restored by
 * multiplication. It is worse for the case this exists to serve: it stretches
 * the GAPS between panels on a wide screen and squashes them on a narrow one,
 * so a reader who arranged three panels side by side to compare them gets them
 * overlapping or scattered. Proportional preserves the arrangement's position;
 * corner-and-offset preserves its shape.
 *
 * Pure arithmetic. No DOM, so the rule is testable — which matters because the
 * failure it guards against only appears on a screen size the author does not
 * have.
 */

import { VIEWPORT_PAD, type Size } from "./layout-metrics";
import type { Corner, Placement } from "@/lib/preferences";

export type { Corner, Placement };

/** A panel's resolved position, in the same vocabulary CSS wants. */
export type At = { left: number; top: number };

/**
 * Which corner a panel at this position belongs to.
 *
 * Decided by the panel's own CENTRE against the middle of the viewport, per
 * axis. Using the centre rather than the top-left is what makes the answer
 * match what the reader sees: a 360px panel whose left edge sits just past the
 * midpoint is visually a right-hand panel, and anchoring it to the left corner
 * would send it sliding leftward every time the window narrowed.
 */
export function cornerFor(at: At, panel: Size, view: Size): Corner {
  const cx = at.left + panel.w / 2;
  const cy = at.top + panel.h / 2;
  const h = cx < view.w / 2 ? "l" : "r";
  const v = cy < view.h / 2 ? "t" : "b";
  return `${v}${h}` as Corner;
}

/**
 * Turn a dropped position into something worth storing.
 *
 * Offsets are measured from the chosen corner to the panel's NEAREST edges, so
 * both numbers stay small and positive for any panel actually on screen. That
 * is what makes the restore stable: a panel 24px from the right edge is 24px
 * from the right edge on every display, whereas its left coordinate is a
 * different number on each one.
 */
export function toPlacement(at: At, panel: Size, view: Size, pad = VIEWPORT_PAD): Placement {
  /* Clamped BEFORE conversion, so a stored offset always describes somewhere
     the panel can actually be. A drag that ends past the right edge otherwise
     stores a negative `dx` — "103px beyond the window" — which `fromPlacement`
     silently clamps back on every restore. Harmless, and still wrong: the
     document is then a record of what the cursor did rather than of where the
     panel went, and the two differ by however far the reader overshot. */
  const left = Math.max(pad, Math.min(at.left, view.w - panel.w - pad));
  const top = Math.max(pad, Math.min(at.top, view.h - panel.h - pad));
  const corner = cornerFor({ left, top }, panel, view);
  const dx = corner.endsWith("l") ? left : view.w - (left + panel.w);
  const dy = corner.startsWith("t") ? top : view.h - (top + panel.h);
  return { corner, dx: Math.round(dx), dy: Math.round(dy) };
}

/**
 * Resolve a stored placement against the window there is now.
 *
 * Clamped exactly the way `placePanel` clamps, and deliberately so: two rules
 * for where a panel may sit would eventually disagree, and the disagreement
 * would show up as a panel that jumps when it is pinned. A panel wider than the
 * window lands at the padding and overflows, which keeps its header — and so
 * its close button and its drag handle — under the cursor.
 *
 * A panel pushed back on screen has lost its anchor. A panel off screen has
 * lost everything.
 */
export function fromPlacement(p: Placement, panel: Size, view: Size, pad = VIEWPORT_PAD): At {
  const left = p.corner.endsWith("l") ? p.dx : view.w - panel.w - p.dx;
  const top = p.corner.startsWith("t") ? p.dy : view.h - panel.h - p.dy;
  return {
    left: Math.max(pad, Math.min(left, view.w - panel.w - pad)),
    top: Math.max(pad, Math.min(top, view.h - panel.h - pad)),
  };
}

/**
 * Whether a restored panel would land essentially on top of another.
 *
 * Used only to decide whether to cascade one out from under another on restore.
 * The reader's arrangement is trusted first — they put those panels where they
 * are — so this asks about near-total occlusion rather than mere overlap. Two
 * panels deliberately tiled with a few pixels of overlap must not be shuffled.
 */
export function occludes(a: At, b: At, panel: Size, slack = 8): boolean {
  return Math.abs(a.left - b.left) <= slack && Math.abs(a.top - b.top) <= slack && panel.w > 0;
}

/** How far a fully-occluded panel steps out, so it is findable rather than lost. */
export const CASCADE = 24;
