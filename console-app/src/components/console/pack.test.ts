/**
 * Packing a band.
 *
 * The fixture is the SHAPE of the live region — six category lanes, one to three
 * subcategories each, one lane far taller than the rest — with block heights
 * rounded to what a group of n chips measures. It is not a transcript of the
 * live estate: real chips carry attachment rows, so the real band is 792px and
 * packs to 698px. Those are in the spec; these numbers are here because they
 * make the arithmetic checkable by hand.
 *
 * What the fixture has to preserve is the property under test: a lane whose
 * blocks stack tall, beside lanes that do not.
 */
import { describe, expect, it } from "vitest";
import {
  type Block,
  type LaneShape,
  allocate,
  bandHeight,
  columnBudget,
  columnHeight,
  laneHeight,
  packRows,
  splitLane,
} from "./pack";

const b = (key: string, h: number): Block => ({ key, h });
const lane = (key: string, rank: number, ...hs: number[]): LaneShape => ({
  key,
  rank,
  blocks: hs.map((h, i) => b(`${key}.${i}`, h)),
});

/* The six lanes of the live region, at 5 chips per group. */
const DATASTORE = lane("datastore", 50, 222, 222, 62); // object, nosql, file
const INTEGRATION = lane("integration", 20, 130, 190); // messaging, events
const SERVERLESS = lane("serverless", 30, 222, 62); //    serverless, instances
const APPLICATION = lane("application", 25, 198, 62); //  media, communications
const API = lane("api", 10, 62); //                       api
const ANALYTICS = lane("analytics", 60, 62); //           query
const BAND = [API, INTEGRATION, APPLICATION, SERVERLESS, DATASTORE, ANALYTICS];

describe("a column is its blocks plus the gaps between them", () => {
  it("adds a gap for each join, and none for a single block", () => {
    expect(columnHeight([b("a", 100)])).toBe(100);
    expect(columnHeight([b("a", 100), b("b", 100)])).toBe(206);
  });

  it("is zero for nothing", () => {
    expect(columnHeight([])).toBe(0);
  });
});

/* ── splitting one lane ────────────────────────────────────────────────── */
describe("splitLane", () => {
  it("puts datastore's three subcategories side by side", () => {
    // object │ nosql │ file — the case that started this.
    const cols = splitLane(DATASTORE.blocks, 3);
    expect(cols.map((c) => c.map((x) => x.key))).toEqual([
      ["datastore.0"],
      ["datastore.1"],
      ["datastore.2"],
    ]);
    expect(Math.max(...cols.map(columnHeight))).toBe(222);
  });

  it("cuts where the split is most even, not down the middle", () => {
    // [222, 222, 62] into two: the cut after the first leaves 222 | 290,
    // after the second leaves 450 | 62. The first is shorter.
    const cols = splitLane(DATASTORE.blocks, 2);
    expect(cols.map((c) => c.length)).toEqual([1, 2]);
    expect(Math.max(...cols.map(columnHeight))).toBe(290);
  });

  it("keeps blocks contiguous, because subcategory order is reading order", () => {
    // [100, 300, 100] into two. Every contiguous cut costs 406; pulling the
    // 300 out on its own would cost 300 — genuinely shorter, and it reorders
    // the lane. Reading order wins, and the test is only meaningful because
    // the two answers differ.
    const uneven = lane("uneven", 10, 100, 300, 100);
    const cols = splitLane(uneven.blocks, 2);
    expect(cols.flat().map((x) => x.key)).toEqual(["uneven.0", "uneven.1", "uneven.2"]);
    expect(Math.max(...cols.map(columnHeight))).toBe(406);
  });

  it("never takes more columns than it has blocks", () => {
    // A block is indivisible; extra columns would be empty and buy no height.
    expect(splitLane(API.blocks, 5)).toHaveLength(1);
    expect(splitLane(DATASTORE.blocks, 99)).toHaveLength(3);
  });

  it("treats a zero or negative column count as one", () => {
    expect(splitLane(DATASTORE.blocks, 0)).toHaveLength(1);
    expect(splitLane(DATASTORE.blocks, -3)).toHaveLength(1);
  });

  it("loses no block, at any column count", () => {
    for (const cols of [1, 2, 3, 4]) {
      const keys = splitLane(DATASTORE.blocks, cols)
        .flat()
        .map((x) => x.key);
      expect(keys.sort()).toEqual(["datastore.0", "datastore.1", "datastore.2"]);
    }
  });

  it("is empty for an empty lane rather than a column of nothing", () => {
    expect(splitLane([], 3)).toEqual([]);
  });

  it("gets shorter, or stays level, as it gets more columns", () => {
    const heights = [1, 2, 3, 4].map((c) => laneHeight(DATASTORE, c));
    expect(heights).toEqual([...heights].sort((x, y) => y - x));
  });
});

/* ── spending the budget ───────────────────────────────────────────────── */
describe("allocate", () => {
  it("gives every lane a column before giving anyone a second", () => {
    const cols = allocate(BAND, BAND.length);
    expect([...cols.values()]).toEqual([1, 1, 1, 1, 1, 1]);
  });

  it("still gives every lane a column when the budget is too small", () => {
    // A lane with no column does not draw. Overflowing is visible; vanishing
    // is not.
    const cols = allocate(BAND, 2);
    expect([...cols.values()].every((c) => c >= 1)).toBe(true);
  });

  it("spends the spare column on the tallest lane, not the first", () => {
    // datastore is 518px and sorts last by key. Order must not decide this.
    const cols = allocate(BAND, BAND.length + 1);
    expect(cols.get("datastore")).toBe(2);
    expect(cols.get("api")).toBe(1);
  });

  it("breaks a tie on key, so serialisation order cannot change the answer", () => {
    // Two lanes, identical heights, splittable, and one spare column between
    // them. Something has to decide, and it must not be Map insertion order —
    // that is whatever the scene happened to serialise.
    const same = [lane("zeta", 10, 200, 200), lane("alpha", 20, 200, 200)];
    const forward = allocate(same, 3);
    const backward = allocate([...same].reverse(), 3);
    expect(forward.get("alpha")).toBe(2);
    expect(forward.get("zeta")).toBe(1);
    expect([...backward.entries()].sort()).toEqual([...forward.entries()].sort());
  });

  it("stops spending on a lane it cannot split further", () => {
    // api is one block. However large the budget, it stays at one column and
    // the rest goes where it can do some good.
    const cols = allocate(BAND, 40);
    expect(cols.get("api")).toBe(1);
    expect(cols.get("analytics")).toBe(1);
    expect(cols.get("datastore")).toBe(3);
  });

  it("never gives a lane more columns than blocks, however big the budget", () => {
    const cols = allocate(BAND, 500);
    for (const l of BAND) expect(cols.get(l.key)!).toBeLessThanOrEqual(l.blocks.length);
  });

  it("handles a band with no lanes at all", () => {
    expect(allocate([], 8).size).toBe(0);
  });
});

/* ── the point of the exercise ─────────────────────────────────────────── */
describe("the live band gets shorter", () => {
  it("is 518px tall drawn one column per lane", () => {
    // The shape of the defect: one lane carrying the whole band's height.
    expect(bandHeight(BAND, allocate(BAND, BAND.length))).toBe(518);
  });

  it("is 326px at one column more — shorter for one column wider", () => {
    expect(bandHeight(BAND, allocate(BAND, BAND.length + 1))).toBe(326);
  });

  it("never gets taller as the budget grows", () => {
    const heights = [6, 7, 8, 9, 10, 11].map((c) => bandHeight(BAND, allocate(BAND, c)));
    expect(heights).toEqual([...heights].sort((x, y) => y - x));
  });

  it("bottoms out rather than shrinking forever", () => {
    // The floor is the tallest single block anywhere: 222px, S3 truncated.
    // No allocation can beat it, because a block cannot be cut.
    expect(bandHeight(BAND, allocate(BAND, 99))).toBe(222);
  });
});

/* ── wrapping to a second row ──────────────────────────────────────────── */
describe("packRows", () => {
  const cols = allocate(BAND, 7);

  it("fills a row before starting another", () => {
    const rows = packRows(BAND, cols, 7);
    expect(rows).toHaveLength(1);
  });

  it("wraps when the row is full", () => {
    const rows = packRows(BAND, cols, 3);
    expect(rows.length).toBeGreaterThan(1);
  });

  it("keeps lanes in rank order across rows — A1 is not traded for packing", () => {
    // api 10, integration 20, application 25, serverless 30, datastore 50,
    // analytics 60. Reading order IS the traffic path; a later lane is never
    // pulled forward to fill a gap.
    const flat = packRows(BAND, cols, 3).flat();
    expect(flat.map((l) => l.rank)).toEqual([10, 20, 25, 30, 50, 60]);
  });

  it("loses no lane when it wraps", () => {
    const flat = packRows(BAND, cols, 2).flat();
    expect(flat).toHaveLength(BAND.length);
  });

  it("gives a lane wider than a whole row its own row rather than dropping it", () => {
    const wide = [lane("wide", 10, 100, 100, 100), lane("thin", 20, 100)];
    const rows = packRows(wide, allocate(wide, 4), 1);
    expect(rows.flat()).toHaveLength(2);
  });

  it("survives a nonsense row width", () => {
    expect(packRows(BAND, cols, 0).flat()).toHaveLength(BAND.length);
  });
});

/* ── how much width there is to spend ──────────────────────────────────── */
describe("columnBudget", () => {
  it("takes the room the container already has", () => {
    // The region is as wide as its VPC. 1070px of it, at 166px a column.
    expect(columnBudget(1070, 166, 6)).toBe(6);
    expect(columnBudget(1250, 166, 6)).toBe(7);
  });

  it("never returns fewer columns than there are lanes", () => {
    // Every lane draws, even in a container too narrow to hold them all.
    expect(columnBudget(200, 166, 6)).toBe(6);
  });

  it("falls back to one column each when there is nothing to measure", () => {
    expect(columnBudget(0, 166, 6)).toBe(6);
    expect(columnBudget(1070, 0, 6)).toBe(6);
  });
});
