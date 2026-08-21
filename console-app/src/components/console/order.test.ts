import { describe, expect, it } from "vitest";
import { applyOrder, moveTo, zoneRowKey } from "./order";

const u = (...keys: string[]) => keys.map((key) => ({ key }));
const keys = <T extends { key: string }>(xs: T[]) => xs.map((x) => x.key);

describe("zoneRowKey", () => {
  it("is derived from content, not position", () => {
    expect(zoneRowKey(u("az:a", "az:b"))).toBe(zoneRowKey(u("az:a", "az:b")));
  });

  it("survives its members being reordered", () => {
    // The identity of a row must not change when the reader rearranges the row
    // — that is the whole point of ordering, and a key that moved with it would
    // discard the preference on first use.
    expect(zoneRowKey(u("az:b", "az:a"))).toBe(zoneRowKey(u("az:a", "az:b")));
  });

  it("distinguishes rows holding different zones", () => {
    expect(zoneRowKey(u("az:a", "az:b"))).not.toBe(zoneRowKey(u("az:a", "az:c")));
  });

  it("does not collide across membership counts", () => {
    expect(zoneRowKey(u("az:a"))).not.toBe(zoneRowKey(u("az:a", "az:b")));
  });
});

describe("applyOrder", () => {
  it("is the identity with no preference", () => {
    const units = u("a", "b", "c");
    expect(applyOrder(units)).toBe(units);
    expect(applyOrder(units, [])).toBe(units);
  });

  it("is the identity when nothing in the container is mentioned", () => {
    const units = u("a", "b", "c");
    // Same reference, not merely the same contents: a container the reader has
    // never touched must not pay for a sort.
    expect(applyOrder(units, ["x", "y"])).toBe(units);
  });

  it("reorders to the saved sequence", () => {
    expect(keys(applyOrder(u("a", "b", "c"), ["c", "a", "b"]))).toEqual(["c", "a", "b"]);
  });

  it("ignores saved keys that no longer exist", () => {
    expect(keys(applyOrder(u("a", "c"), ["c", "gone", "a"]))).toEqual(["c", "a"]);
  });

  it("appends new keys after the saved ones, in engine order", () => {
    // `d` and `e` arrived after the order was saved. They keep the order the
    // engine gave them and land behind everything the reader arranged.
    expect(keys(applyOrder(u("a", "b", "c", "d", "e"), ["c", "a"]))).toEqual([
      "c",
      "a",
      "b",
      "d",
      "e",
    ]);
  });

  it("survives a duplicated key in the preference", () => {
    expect(keys(applyOrder(u("a", "b"), ["b", "a", "b"]))).toEqual(["b", "a"]);
  });

  it("never adds or drops a unit", () => {
    const units = u("a", "b", "c", "d");
    const out = applyOrder(units, ["d", "ghost", "b"]);
    expect(out).toHaveLength(units.length);
    expect([...keys(out)].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("leaves a single unit alone", () => {
    const units = u("a");
    expect(applyOrder(units, ["z", "a"])).toBe(units);
  });
});

describe("moveTo", () => {
  it("moves a unit forward", () => {
    expect(moveTo(u("a", "b", "c"), "c", 0)).toEqual(["c", "a", "b"]);
  });

  it("moves a unit backward", () => {
    expect(moveTo(u("a", "b", "c"), "a", 2)).toEqual(["b", "c", "a"]);
  });

  it("returns the full order, not a patch", () => {
    expect(moveTo(u("a", "b", "c"), "b", 1)).toEqual(["a", "b", "c"]);
  });

  it("clamps an out-of-range target", () => {
    expect(moveTo(u("a", "b", "c"), "a", 99)).toEqual(["b", "c", "a"]);
    expect(moveTo(u("a", "b", "c"), "c", -5)).toEqual(["c", "a", "b"]);
  });

  it("is a no-op for a key it does not hold", () => {
    expect(moveTo(u("a", "b"), "ghost", 0)).toEqual(["a", "b"]);
  });

  it("round-trips through applyOrder", () => {
    const units = u("a", "b", "c", "d");
    expect(keys(applyOrder(units, moveTo(units, "d", 1)))).toEqual(["a", "d", "b", "c"]);
  });
});
