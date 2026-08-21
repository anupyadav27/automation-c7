/**
 * Curves from a list row to the resources it names.
 *
 * Pure geometry, so a test can check the path without a browser.
 *
 * This is the one place the diagram measures the DOM, and the distinction
 * matters: measurement for an OVERLAY is not measurement for PLACEMENT. Where
 * a box sits is decided bottom-up from `layout-metrics.ts` and never from the
 * rendered page — that is what makes the same estate draw the same diagram
 * twice. A trace line is drawn over that result and changes nothing about it,
 * so reading rectangles at hover time costs nothing but the read.
 */

export type Rect = { x: number; y: number; w: number; h: number };

/**
 * A cubic bezier between two rectangles, leaving and arriving on facing edges.
 *
 * Orientation comes from the larger centre delta: two boxes side by side get a
 * horizontal curve, one above the other a vertical one. Anchoring on the
 * facing EDGE rather than the centre is what stops the line disappearing under
 * the box it starts from.
 */
export function link(a: Rect, b: Rect): string {
  return curve(a, b).d;
}

type Point = { x: number; y: number };

/**
 * The same curve, plus the point halfway along it.
 *
 * A line now carries a word — `protected-by`, `encrypted-by` — and a word has
 * to sit somewhere. The midpoint of the CURVE, not of the straight line
 * between the two boxes: a cubic that bows out by 100px would leave its label
 * floating off the line it belongs to, which reads as a label for nothing.
 */
export function curve(a: Rect, b: Rect): { d: string; mid: Point } {
  const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
  const bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };

  let p0: Point, p1: Point, p2: Point, p3: Point;
  if (Math.abs(bc.x - ac.x) > Math.abs(bc.y - ac.y)) {
    const x1 = ac.x < bc.x ? a.x + a.w : a.x;
    const x2 = ac.x < bc.x ? b.x : b.x + b.w;
    const dx = (x2 - x1) / 2;
    p0 = { x: x1, y: ac.y };
    p1 = { x: x1 + dx, y: ac.y };
    p2 = { x: x2 - dx, y: bc.y };
    p3 = { x: x2, y: bc.y };
  } else {
    const y1 = ac.y < bc.y ? a.y + a.h : a.y;
    const y2 = ac.y < bc.y ? b.y : b.y + b.h;
    const dy = (y2 - y1) / 2;
    p0 = { x: ac.x, y: y1 };
    p1 = { x: ac.x, y: y1 + dy };
    p2 = { x: bc.x, y: y2 - dy };
    p3 = { x: bc.x, y: y2 };
  }
  return {
    d: `M ${p0.x} ${p0.y} C ${p1.x} ${p1.y}, ${p2.x} ${p2.y}, ${p3.x} ${p3.y}`,
    // A cubic at t=0.5. Averaging the endpoints instead puts the label off a
    // bowed curve by half its bow.
    mid: {
      x: (p0.x + 3 * p1.x + 3 * p2.x + p3.x) / 8,
      y: (p0.y + 3 * p1.y + 3 * p2.y + p3.y) / 8,
    },
  };
}

/**
 * A DOM rect made relative to the host it will be drawn over.
 *
 * `scroll` is the host's own scroll offset, and leaving it out is what broke
 * every line the moment the canvas moved. The overlay is `absolute inset-0`
 * inside a scrolling box, so its origin is the SCROLL CONTENT's top-left — it
 * travels with the diagram. `getBoundingClientRect` answers in VIEWPORT space,
 * whose origin stays put. The two agree only at scroll zero; at 480px down,
 * every arrow was drawn 480px above the resource it pointed at, still dashed,
 * still labelled, still pointing at nothing.
 *
 * A border rail is the case that exposed it, because reaching one nearly
 * always means scrolling first — so the arms of the diagram looked incapable
 * of showing relationships at all.
 */
export function relativeTo(rect: DOMRect, host: DOMRect, scroll = { x: 0, y: 0 }): Rect {
  return {
    x: rect.left - host.left + scroll.x,
    y: rect.top - host.top + scroll.y,
    w: rect.width,
    h: rect.height,
  };
}

/**
 * Every trace to draw from one row, given what the page currently shows.
 *
 * Returns nothing when the row has no rect — the list is portalled and can be
 * scrolled or closed between the hover and the paint, and a curve drawn from a
 * stale rectangle points at nothing.
 */
export type Trace = {
  key: string;
  d: string;
  /** The relationship, worded subject to object. */
  label: string;
  /** Which end of the curve carries the arrowhead. */
  head: "start" | "end";
  /** Where the label sits — halfway along the curve. */
  mid: Point;
};

export function tracesFrom(
  from: Rect | null,
  targets: Array<{ key: string; rect: Rect; direction?: "out" | "in"; label?: string }>,
): Trace[] {
  if (!from) return [];
  return targets.map((t) => {
    const { d, mid } = curve(from, t.rect);
    return {
      key: t.key,
      d,
      label: t.label ?? "",
      /* The head marks the OBJECT, and the hovered row is not always the
         subject. An interface hovered from a list points AT the security group
         that governs it; the same group hovered from its own list is pointed
         at BY the interfaces — same edge, same arrow, drawn from whichever end
         the reader happens to be on. */
      head: t.direction === "in" ? "start" : "end",
      mid,
    };
  });
}
