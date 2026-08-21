import { describe, expect, it } from "vitest";
import { curve, link, relativeTo, tracesFrom, type Rect } from "./trace";

const box = (x: number, y: number): Rect => ({ x, y, w: 100, h: 40 });

describe("link", () => {
  it("leaves the facing edge, not the centre", () => {
    // Starting at the centre draws the first third of the curve underneath the
    // box it comes from, which reads as a line that starts nowhere.
    const d = link(box(0, 0), box(400, 0));

    expect(d.startsWith("M 100 20")).toBe(true); // right edge of a
    expect(d).toContain("400 20"); // left edge of b
  });

  it("goes the other way when the target is to the left", () => {
    const d = link(box(400, 0), box(0, 0));

    expect(d.startsWith("M 400 20")).toBe(true); // LEFT edge of a
  });

  it("curves vertically when the vertical gap is the larger one", () => {
    const d = link(box(0, 0), box(10, 400));

    expect(d.startsWith("M 50 40")).toBe(true); // bottom edge of a
    expect(d).toContain("60 400"); // top edge of b
  });

  it("is a cubic, so it can leave and arrive at different heights", () => {
    expect(link(box(0, 0), box(400, 300))).toContain(" C ");
  });
});

describe("relativeTo", () => {
  it("subtracts the host origin so a viewport rect lands on the canvas", () => {
    // The list is portalled to body, so its rows are in viewport coordinates
    // while the SVG draws in the canvas's own.
    const rect = { left: 300, top: 200, width: 90, height: 20 } as DOMRect;
    const host = { left: 100, top: 50 } as DOMRect;

    expect(relativeTo(rect, host)).toEqual({ x: 200, y: 150, w: 90, h: 20 });
  });
});

describe("tracesFrom", () => {
  it("draws one curve per target", () => {
    const out = tracesFrom(box(0, 0), [
      { key: "a", rect: box(400, 0) },
      { key: "b", rect: box(400, 200) },
    ]);

    expect(out.map((t) => t.key)).toEqual(["a", "b"]);
    expect(out.every((t) => t.d.startsWith("M "))).toBe(true);
  });

  it("draws nothing from a missing rect", () => {
    // The list is portalled and can scroll or close between hover and paint;
    // a curve from a stale rectangle points at nothing.
    expect(tracesFrom(null, [{ key: "a", rect: box(0, 0) }])).toEqual([]);
  });
});

/* ── direction ─────────────────────────────────────────────────────────
   An arrow's head marks the OBJECT of the relationship, and the hovered row
   is not always the subject. Hovering an interface points AT the group that
   governs it; hovering that group is pointed at BY its interfaces. Same edge,
   same arrow — the head just moves to the other end of the same curve. */

describe("tracesFrom · direction", () => {
  it("puts the head at the far end when the hovered row is the subject", () => {
    const [t] = tracesFrom(box(0, 0), [
      { key: "sg", rect: box(400, 0), direction: "out", label: "protected-by" },
    ]);

    expect(t!.head).toBe("end");
    expect(t!.label).toBe("protected-by");
  });

  it("puts the head at the hovered row when the row is the object", () => {
    // A security group's own list: the interfaces point at IT.
    const [t] = tracesFrom(box(0, 0), [
      { key: "eni", rect: box(400, 0), direction: "in", label: "protected-by" },
    ]);

    expect(t!.head).toBe("start");
  });

  it("defaults to the far end when nothing says otherwise", () => {
    expect(tracesFrom(box(0, 0), [{ key: "a", rect: box(400, 0) }])[0]!.head).toBe("end");
  });

  it("labels nothing rather than labelling it wrong", () => {
    expect(tracesFrom(box(0, 0), [{ key: "a", rect: box(400, 0) }])[0]!.label).toBe("");
  });
});

describe("curve · label anchor", () => {
  it("sits on the curve, not on the straight line between the boxes", () => {
    // A cubic that bows out leaves a midpoint-of-endpoints label off the line
    // it belongs to. t=0.5 of the actual cubic is the only point that is on it.
    const { mid } = curve(box(0, 0), box(400, 300));

    expect(mid.x).toBeCloseTo((100 + 3 * 250 + 3 * 250 + 400) / 8, 6);
    expect(mid.y).toBeCloseTo((20 + 3 * 20 + 3 * 320 + 320) / 8, 6);
  });

  it("draws the same path it always did", () => {
    expect(curve(box(0, 0), box(400, 0)).d).toBe(link(box(0, 0), box(400, 0)));
  });
});

describe("relativeTo · a host that scrolls", () => {
  it("answers in the diagram's space, not the window's", () => {
    // The overlay is absolutely positioned inside the scrolling canvas, so its
    // origin travels with the content while getBoundingClientRect does not.
    const rect = { left: 300, top: 200, width: 90, height: 20 } as DOMRect;
    const host = { left: 100, top: 50 } as DOMRect;

    expect(relativeTo(rect, host, { x: 0, y: 480 })).toEqual({ x: 200, y: 630, w: 90, h: 20 });
  });

  it("is unchanged when nothing has scrolled", () => {
    const rect = { left: 300, top: 200, width: 90, height: 20 } as DOMRect;
    const host = { left: 100, top: 50 } as DOMRect;

    expect(relativeTo(rect, host, { x: 0, y: 0 })).toEqual(relativeTo(rect, host));
  });
});
