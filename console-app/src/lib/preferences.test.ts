import { describe, expect, it } from "vitest";
import {
  PREFS_VERSION,
  decode,
  decodePlacement,
  emptyPrefs,
  encode,
  isCustomised,
  prune,
  scopeOf,
  type Prefs,
} from "./preferences";

const SCOPE = scopeOf("588989875114", "ap-southeast-1");
const base = () => emptyPrefs(SCOPE);

const withOrder = (order: Prefs["order"]): Prefs => ({ ...base(), order });

describe("decode", () => {
  it("round-trips a document", () => {
    const p: Prefs = {
      ...base(),
      order: { "vpc:vpc-a": ["subnet:b", "subnet:a"] },
      panels: [{ kind: "list", subject: "box:vpc:vpc-a", place: { corner: "tr", dx: 24, dy: 60 } }],
      places: { "ec2.instance:i-1": { corner: "bl", dx: 10, dy: 10 } },
      traces: ["sg:sg-1"],
      filter: { hidden: ["security.identity"] },
      toggles: { showArtifacts: true },
    };
    expect(decode(encode(p), SCOPE)).toEqual({ ...p, savedAt: "" });
  });

  it("rejects a document from another scope", () => {
    // A fixture session and a live account are different estates whose keys
    // look alike. Applying one's order to the other rebinds every preference.
    expect(decode(encode(base()), "other/region")).toBeNull();
  });

  it("rejects a document from another version", () => {
    const stale = { ...base(), version: PREFS_VERSION + 1 };
    expect(decode(JSON.stringify(stale), SCOPE)).toBeNull();
  });

  it("returns null rather than throwing on junk", () => {
    for (const junk of ["", "{", "null", "[]", '"a string"', "42"]) {
      expect(decode(junk, SCOPE)).toBeNull();
    }
  });

  it("survives every field being the wrong type", () => {
    const p = decode(
      JSON.stringify({
        version: PREFS_VERSION,
        scope: SCOPE,
        order: "not an object",
        panels: "not an array",
        places: 7,
        traces: { nope: true },
        filter: null,
        toggles: "no",
      }),
      SCOPE,
    );
    expect(p).toEqual(base());
  });

  it("drops junk entries but keeps the good ones beside them", () => {
    const p = decode(
      JSON.stringify({
        ...base(),
        order: { good: ["a", 7, "b"], empty: [], alsoGood: ["c"] },
        traces: ["keep", 9, null, "keep2"],
        panels: [
          { kind: "list", subject: "ok" },
          { kind: "nonsense", subject: "x" },
          { kind: "detail" },
          { kind: "detail", subject: "ok2", place: { corner: "zz", dx: 1, dy: 1 } },
        ],
      }),
      SCOPE,
    );
    expect(p?.order).toEqual({ good: ["a", "b"], alsoGood: ["c"] });
    expect(p?.traces).toEqual(["keep", "keep2"]);
    expect(p?.panels).toEqual([
      { kind: "list", subject: "ok" },
      // The bad placement is dropped; the panel it was on survives without it.
      { kind: "detail", subject: "ok2" },
    ]);
  });

  it("fills fields a document written by an older console never had", () => {
    const p = decode(JSON.stringify({ version: PREFS_VERSION, scope: SCOPE }), SCOPE);
    expect(p).toEqual(base());
  });
});

describe("decodePlacement", () => {
  it("accepts the four corners", () => {
    for (const corner of ["tl", "tr", "bl", "br"] as const) {
      expect(decodePlacement({ corner, dx: 1, dy: 2 })).toEqual({ corner, dx: 1, dy: 2 });
    }
  });

  it("rejects anything it cannot fully read", () => {
    for (const bad of [
      null,
      "tr",
      { corner: "middle", dx: 1, dy: 1 },
      { corner: "tr", dx: "1", dy: 1 },
      { corner: "tr", dx: NaN, dy: 1 },
      { corner: "tr", dx: 1 },
    ]) {
      expect(decodePlacement(bad)).toBeUndefined();
    }
  });
});

describe("prune", () => {
  const alive = new Set(["a", "b"]);

  it("keeps a document whose subjects all still exist", () => {
    const p: Prefs = {
      ...base(),
      panels: [{ kind: "list", subject: "box:a", members: ["a"] }],
      traces: ["b"],
    };
    const out = prune(p, alive);
    expect(out.dropped).toBe(0);
    expect(out.prefs).toBe(p); // untouched, not merely equal
  });

  it("drops pins and traces whose subject is gone, and counts them", () => {
    const p: Prefs = {
      ...base(),
      panels: [
        { kind: "detail", subject: "a" },
        { kind: "detail", subject: "ec2.instance:i-scaled-away" },
      ],
      traces: ["b", "eni:gone"],
    };
    const out = prune(p, alive);
    expect(out.dropped).toBe(2);
    expect(out.prefs.panels).toEqual([{ kind: "detail", subject: "a" }]);
    expect(out.prefs.traces).toEqual(["b"]);
  });

  /* The regression: a list's subject is a HOST key — `box:vpc-a`, `flat:...`,
     a service name — which is not a node key and never appears in `alive`.
     Judging both kinds the same way dropped every pinned list on load. */
  it("judges a list by its members, not by its host key", () => {
    const p: Prefs = {
      ...base(),
      panels: [{ kind: "list", subject: "box:vpc:vpc-a", members: ["a", "b"] }],
    };
    const out = prune(p, alive);
    expect(out.dropped).toBe(0);
    expect(out.prefs.panels).toHaveLength(1);
  });

  it("trims a list's dead members but keeps the list", () => {
    const p: Prefs = {
      ...base(),
      panels: [{ kind: "list", subject: "box:vpc:vpc-a", members: ["a", "eni:gone", "b"] }],
    };
    const out = prune(p, alive);
    expect(out.prefs.panels[0]?.members).toEqual(["a", "b"]);
    // The panel survived, so nothing was DROPPED — it was narrowed.
    expect(out.dropped).toBe(0);
  });

  it("drops a list whose every member is gone", () => {
    const p: Prefs = {
      ...base(),
      panels: [{ kind: "list", subject: "box:vpc:gone", members: ["eni:gone"] }],
    };
    const out = prune(p, alive);
    expect(out.dropped).toBe(1);
    expect(out.prefs.panels).toEqual([]);
  });

  it("never prunes order sequences against node keys", () => {
    // Unit keys are not all node keys — a service group is keyed by service, a
    // zone row by its members. Testing them against the scene's node keys would
    // delete valid preferences.
    const p = withOrder({ "vpc:x": ["datastore", "zones:az:a|az:b", "gone"] });
    expect(prune(p, alive).prefs.order).toEqual(p.order);
  });
});

describe("isCustomised", () => {
  it("is false for a fresh document", () => {
    expect(isCustomised(base())).toBe(false);
  });

  it("is true for any single override", () => {
    expect(isCustomised(withOrder({ a: ["b"] }))).toBe(true);
    expect(isCustomised({ ...base(), panels: [{ kind: "list", subject: "a" }] })).toBe(true);
    expect(isCustomised({ ...base(), places: { a: { corner: "tl", dx: 0, dy: 0 } } })).toBe(true);
    expect(isCustomised({ ...base(), traces: ["a"] })).toBe(true);
    expect(isCustomised({ ...base(), filter: { hidden: ["security.identity"] } })).toBe(true);
    expect(isCustomised({ ...base(), toggles: { showArtifacts: true } })).toBe(true);
  });
});
