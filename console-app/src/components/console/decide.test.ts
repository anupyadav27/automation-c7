/**
 * The decisions the renderer makes, tested without a browser.
 *
 * Every case here is a defect that actually shipped. `tsc` passed, eslint
 * passed, the build passed, the page rendered, and the diagram was wrong — so
 * the cases are written as the SYMPTOM a reader saw, not as the shape of the
 * code that produced it. A test that only restates the implementation cannot
 * fail for the reason the implementation was wrong.
 */
import { describe, expect, it } from "vitest";
import {
  CODES,
  CODE_ARM,
  CODE_ORDER,
  RAIL_TINT,
  RAMP,
  TIERS,
  TIER_OF_DOMAIN,
  alongRank,
  annotateEdges,
  byRank,
  byExposureThenSize,
  clusterRuns,
  codeTone,
  containerStyle,
  familyTitleFor,
  grey,
  isHorizontal,
  laneNoun,
  railToneFor,
  splitLayers,
  tabRun,
  tabShape,
  tierFor,
} from "./decide";

/* ── the grey ramp ─────────────────────────────────────────────────────
   "i want like eks (light gray) — ec2 lightest gray — instances box white".
   Shipped inverted once, and shipped as a Tailwind class that generated no CSS
   at all once. Both were invisible to the toolchain. */
describe("the neutral ramp lightens inward", () => {
  it("goes orchestrator → group → resource, darkest first", () => {
    expect(RAMP.orchestrator).toBeLessThan(RAMP.group);
    expect(RAMP.group).toBeLessThan(RAMP.resource);
  });

  it("mixes toward the surface colour, so a higher rung is lighter", () => {
    expect(grey(RAMP.orchestrator).background).toContain("45%");
    expect(grey(RAMP.group).background).toContain("75%");
  });

  it("produces a real CSS value, not a class name", () => {
    // The defect: `bg-[color-mix(...${n}%...)]` type-checks, renders, and the
    // JIT never sees it because it scans source TEXT. The boxes came out with
    // no background and nothing said a word.
    const style = grey(RAMP.group);
    expect(style.background.startsWith("color-mix(")).toBe(true);
    expect(style.background).not.toContain("bg-[");
  });
});

/* ── provider colours ──────────────────────────────────────────────────
   "Containers should keep csp prescribed colour .. the eks, ec2 or other
   orchestrator can use the gray ramp as csp doesn't prescribe colour for
   these." Shipped once with every box white. */
describe("containers keep the colour AWS prescribes", () => {
  it("gives each Architecture Group boundary its own hue", () => {
    const hues = ["account", "region", "network", "segment"].map((r) => containerStyle(r)?.border);
    expect(hues.every(Boolean)).toBe(true);
    expect(new Set(hues).size).toBeGreaterThan(1);
  });

  it("draws a public subnet green, because it is the one that faces out", () => {
    expect(containerStyle("segment", "public")?.border).toContain("122 161 22");
    expect(containerStyle("segment", "private")?.border).not.toContain("122 161 22");
  });

  it("falls back to the plain role when the tier has no colour of its own", () => {
    expect(containerStyle("segment", "private")).toEqual(containerStyle("segment"));
  });

  it("says nothing for a box the provider prescribes no colour for", () => {
    // An EKS cluster, a scaling group, a rule wrap: these take the grey ramp.
    // Returning a colour here would assert a convention AWS has not set.
    expect(containerStyle("cluster")).toBeUndefined();
    expect(containerStyle("")).toBeUndefined();
  });
});

/* ── tags point at the right arm ───────────────────────────────────────
   A tag exists so a reader can find the thing governing a resource. */
describe("a code chip matches the border its target rides", () => {
  it("colours every code family in the order", () => {
    for (const code of CODE_ORDER) expect(CODE_ARM[code]).toBeDefined();
  });

  it("puts identity and encryption on the same arm, traffic on another", () => {
    expect(CODE_ARM["iam"]!.arm).toBe(CODE_ARM["kms"]!.arm);
    expect(CODE_ARM["sg"]!.arm).toBe(CODE_ARM["rt"]!.arm);
    expect(CODE_ARM["iam"]!.arm).not.toBe(CODE_ARM["sg"]!.arm);
  });

  it("tones a numbered code by its family, not the whole string", () => {
    expect(codeTone("iam-12")).toEqual(codeTone("iam-1"));
    expect(codeTone("sg-3")).not.toEqual(codeTone("iam-3"));
  });

  it("leaves an unknown code untinted rather than guessing", () => {
    expect(codeTone("zzz-1")).toBeUndefined();
  });

  it("tints a rail from the PROVIDER's palette, not one of our own", () => {
    // AWS ships a category colour for every service it makes. Inventing a
    // second set beside it put a security group's icon in AWS red inside a tab
    // we had coloured violet — two colour systems on one canvas, disagreeing.
    expect(railToneFor("rgb(221 52 76)")!.borderColor).toContain("221 52 76");
    expect(railToneFor("rgb(140 79 255)")!.borderColor).toContain("140 79 255");
  });

  it("says nothing when the provider prescribes no colour", () => {
    expect(railToneFor(undefined)).toBeUndefined();
  });

  it("no longer matches a code chip to its rail, and that is the trade", () => {
    /* A tag and the rail it points at USED to share a hue, so the eye went to
       the right border without reading a word. Rails now take AWS's category
       colour and codes keep their wayfinding hue, so the two diverge: an `sg-2`
       chip is amber while the firewall rail naming its target is AWS red.

       Recorded as a test rather than left to be rediscovered. Making codes
       follow AWS too would collapse them — `sg` and `iam` are both
       security-red — and the arm distinction is what the codes are FOR. */
    expect(railToneFor("rgb(221 52 76)")!.borderColor).not.toContain(CODE_ARM["sg"]!.rgb);
  });

  it("has an arm for every hue a rail can show", () => {
    const arms = new Set(Object.values(CODE_ARM).map((a) => a.rgb));
    for (const rgb of Object.values(RAIL_TINT)) expect(arms.has(rgb)).toBe(true);
  });
});

/* ── tiers ─────────────────────────────────────────────────────────────── */
describe("tiers", () => {
  it("files a record as provenance whatever its domain", () => {
    // An AMI is compute by domain and evidence by kind. Kind wins.
    expect(tierFor("record", "compute", "instances")).toBe("D");
    expect(tierFor("resident", "compute", "instances")).toBe("A");
  });

  it("lets a subcategory override its category", () => {
    expect(tierFor("resident", "network", "delivery")).toBe("A");
    expect(tierFor("rule", "network", "firewall")).toBe("B");
  });

  it("files a load balancer as structural, like the delivery it split from", () => {
    // network.loadbalancing was split out of network.delivery. A split that
    // silently demoted every ELB to operational would move them on the canvas.
    expect(tierFor("resident", "network", "loadbalancing")).toBe("A");
  });

  it("falls back to operational rather than dropping an unknown domain", () => {
    expect(tierFor("resident", "nonesuch", "nothing")).toBe("C");
  });

  it("uses only tiers the legend can explain", () => {
    const known = new Set(TIERS.map((t) => t.id));
    for (const t of Object.values(TIER_OF_DOMAIN)) expect(known.has(t)).toBe(true);
  });
});

/* ── families ──────────────────────────────────────────────────────────── */
describe("family headings", () => {
  it("reads security and governance as management", () => {
    expect(familyTitleFor("security", "identity")).toBe("management · identity");
    expect(familyTitleFor("governance", "audit")).toBe("management · audit");
  });

  it("reads devtools as devops", () => {
    expect(familyTitleFor("devtools", "deploy")).toBe("devops · deploy");
  });

  it("leaves a category with no family under its own name", () => {
    expect(familyTitleFor("storage", "object")).toBe("storage · object");
  });
});

/* ── the engine's vocabulary stays in the engine ───────────────────────
   Renaming `integration` to `resident.integration` for the kind axis put the
   role string straight into a heading: the page read `resident.api`. */
describe("a role name never reaches the screen", () => {
  it("drops the role prefix from a lane heading", () => {
    expect(laneNoun("resident.integration")).toBe("integration");
    expect(laneNoun("resident.application")).toBe("application");
  });

  it("leaves a lane with no prefix alone", () => {
    expect(laneNoun("artifacts")).toBe("artifacts");
  });
});

/* ── tags land on something a reader can find ──────────────────────────
   371 of 494 tags landed on records — resources that live in a panel and never
   draw — and 27 of 80 governing resources ended up with a code that appeared
   nowhere on the canvas. Most `protected-by` edges come from a security
   group's own RULES, which are records. */
describe("annotateEdges", () => {
  const edge = (source: string, target: string, edge_type = "protected-by") => ({
    source_key: source,
    target_key: target,
    edge_type,
  });
  const drawn = (...keys: string[]) => {
    const set = new Set(keys);
    return (k: string) => set.has(k);
  };

  it("tags a drawn resource", () => {
    const { byNode, legend } = annotateEdges([edge("i-1", "sg-a")], drawn("i-1"));
    expect(byNode["i-1"]!["sg"]).toEqual(["sg-1"]);
    expect(legend).toHaveLength(1);
  });

  it("does not tag a record, because the tag would point at nothing", () => {
    const { byNode, legend } = annotateEdges([edge("rule-1", "sg-a")], drawn());
    expect(byNode).toEqual({});
    expect(legend).toEqual([]);
  });

  it("never numbers a governing resource whose only members are records", () => {
    // The symptom: a legend reading `sg-5` that a reader cannot find anywhere,
    // in a sequence that skips.
    const { legend } = annotateEdges(
      [edge("rule-1", "sg-a"), edge("rule-2", "sg-a"), edge("i-1", "sg-b")],
      drawn("i-1"),
    );
    expect(legend.map((l) => l.code)).toEqual(["sg-1"]);
    expect(legend[0]!.targetKey).toBe("sg-b");
  });

  it("gives every legend entry at least one drawn reference", () => {
    const { legend } = annotateEdges([edge("i-1", "sg-a"), edge("rule-9", "sg-z")], drawn("i-1"));
    for (const entry of legend) expect(entry.refs.length).toBeGreaterThan(0);
  });

  it("gives one code per governing resource, however many edges report it", () => {
    // Three interfaces in the same security group is one `sg-1`, not three.
    const { byNode } = annotateEdges(
      [edge("i-1", "sg-a"), edge("i-1", "sg-a"), edge("i-1", "sg-a")],
      drawn("i-1"),
    );
    expect(byNode["i-1"]!["sg"]).toEqual(["sg-1"]);
  });

  it("lets one node carry codes from different families at once", () => {
    // An instance is in a security group AND assumes a role. Both must show.
    const { byNode } = annotateEdges(
      [edge("i-1", "sg-a"), edge("i-1", "role-a", "assumes"), edge("i-1", "k-1", "encrypted-by")],
      drawn("i-1"),
    );
    expect(Object.keys(byNode["i-1"]!).sort()).toEqual(["iam", "kms", "sg"]);
  });

  it("sorts the legend by number, not by string", () => {
    // A string sort puts iam-10 before iam-2, which defeats the sequence.
    const edges = Array.from({ length: 12 }, (_, i) => edge("i-1", `role-${i}`, "assumes"));
    const { legend } = annotateEdges(edges, drawn("i-1"));
    const numbers = legend.map((l) => Number(l.code.split("-")[1]));
    expect(numbers).toEqual([...numbers].sort((a, b) => a - b));
  });

  it("sorts families in the declared order", () => {
    const { legend } = annotateEdges(
      [edge("i-1", "k-1", "encrypted-by"), edge("i-1", "sg-a")],
      drawn("i-1"),
    );
    expect(legend.map((l) => l.kind)).toEqual(["sg", "kms"]);
  });

  it("ignores an edge type that carries no code", () => {
    const { legend } = annotateEdges([edge("i-1", "x-1", "created-from")], drawn("i-1"));
    expect(legend).toEqual([]);
  });

  it("labels every code family it can emit", () => {
    for (const spec of Object.values(CODES)) expect(spec.label).toBeTruthy();
  });
});

/* ── clusters ──────────────────────────────────────────────────────────── */
describe("clusterRuns", () => {
  type Node = { key: string; position?: { cluster?: string | null | undefined } };
  const n = (key: string, cluster?: string): Node => ({ key, position: { cluster } });

  it("groups members under the fleet that owns them", () => {
    const runs = clusterRuns([n("a", "asg-1"), n("b", "asg-1"), n("c")]);
    expect(runs[0]!.cluster).toBe("asg-1");
    expect(runs[0]!.members).toHaveLength(2);
  });

  it("puts the unowned remainder last, because it is not a fleet", () => {
    const runs = clusterRuns([n("c"), n("a", "asg-1"), n("b", "asg-1")]);
    expect(runs.at(-1)!.cluster).toBeNull();
  });

  it("orders fleets by size, biggest first", () => {
    const runs = clusterRuns([n("a", "small"), n("b", "big"), n("c", "big")]);
    expect(runs.map((r) => r.cluster)).toEqual(["big", "small"]);
  });

  it("breaks a size tie by name, so the answer does not depend on serialisation", () => {
    const forward = clusterRuns([n("a", "zeta"), n("b", "alpha")]);
    const backward = clusterRuns([n("b", "alpha"), n("a", "zeta")]);
    expect(forward.map((r) => r.cluster)).toEqual(backward.map((r) => r.cluster));
    expect(forward.map((r) => r.cluster)).toEqual(["alpha", "zeta"]);
  });

  it("emits no empty remainder when everything is owned", () => {
    expect(clusterRuns([n("a", "asg-1")])).toHaveLength(1);
  });

  it("handles a node with no position at all", () => {
    const bare: Node[] = [{ key: "a" }];
    expect(clusterRuns(bare)).toEqual([{ cluster: null, members: bare }]);
  });
});

/* ── reading order is the traffic path ─────────────────────────────────
   Axiom A1, one level down from the bands: cloudfront → igw → lb → compute →
   orchestrated compute → rds. Before this, forty buckets outranked the load
   balancer in front of them purely by being numerous. */
describe("group order runs from the internet inward", () => {
  type G = { exposure: number };
  const order = byExposureThenSize<G>((g) => g.exposure);
  const group = (name: string, exposure: number, size = 1): [string, G[]] => [
    name,
    Array.from({ length: size }, () => ({ exposure })),
  ];

  it("puts the front door before the things behind it", () => {
    const groups = [group("rds", 4), group("lb", 2), group("cloudfront", 1)];
    expect(groups.sort(order).map(([n]) => n)).toEqual(["cloudfront", "lb", "rds"]);
  });

  it("does not let a big internal group outrank a small exposed one", () => {
    const groups = [group("buckets", 4, 40), group("lb", 2, 1)];
    expect(groups.sort(order).map(([n]) => n)).toEqual(["lb", "buckets"]);
  });

  it("sorts an off-path group last, not first", () => {
    // Exposure 0 means "not on the traffic path" — policies, config. Sorting
    // numerically would read a 0 as closer to the internet than L1.
    const groups = [group("policies", 0), group("cloudfront", 1)];
    expect(groups.sort(order).map(([n]) => n)).toEqual(["cloudfront", "policies"]);
  });

  it("breaks a full tie by name, so the order is stable", () => {
    const a = [group("zeta", 2), group("alpha", 2)].sort(order);
    const b = [group("alpha", 2), group("zeta", 2)].sort(order);
    expect(a.map(([n]) => n)).toEqual(b.map(([n]) => n));
  });
});

/* ── reading order is rank, and nothing else ───────────────────────────
   Three fixed render blocks became two, and each version had the same defect
   somewhere new: a KMS wrap jumping ahead of the instances it encloses, and the
   account's CloudFront drawing below its own region. */
describe("everything inside a container competes on rank alone", () => {
  const unit = (key: string, rank: number) => ({ key, rank });

  it("puts the front door above the network that hides behind it", () => {
    // The account holds CloudFront at rank 10 (L1) and its region at rank 20.
    const drawn = [unit("region:ap-south-1", 20), unit("group:edge", 10)].sort(byRank);
    expect(drawn.map((u) => u.key)).toEqual(["group:edge", "region:ap-south-1"]);
  });

  it("gives a container no advantage over a group at the same rank", () => {
    // Being a box is not a reason to come first; that was the whole bug.
    const drawn = [unit("z-container", 20), unit("a-group", 20)].sort(byRank);
    expect(drawn[0]!.key).toBe("a-group");
  });

  it("keeps a rule wrap with the resources it encloses, not ahead of them", () => {
    const drawn = [unit("wrap:kms", 30), unit("group:compute", 20)].sort(byRank);
    expect(drawn.map((u) => u.key)).toEqual(["group:compute", "wrap:kms"]);
  });

  it("sorts unranked things last rather than first", () => {
    const drawn = [unit("unranked", 999), unit("edge", 10)].sort(byRank);
    expect(drawn.map((u) => u.key)).toEqual(["edge", "unranked"]);
  });

  it("is stable, so the order does not depend on serialisation", () => {
    const a = [unit("b", 10), unit("a", 10)].sort(byRank).map((u) => u.key);
    const b = [unit("a", 10), unit("b", 10)].sort(byRank).map((u) => u.key);
    expect(a).toEqual(b);
  });
});

/* ── a tab on a border ─────────────────────────────────────────────────
   The rails carry what governs a box — identity, encryption, firewall, config.
   They used to float over the line as panels, which covered whatever was behind
   them and said nothing about which box they belonged to. */
describe("a rail group is a tab on the border it applies to", () => {
  it("opens toward the box on every edge, which is what says 'attached'", () => {
    // The missing border is the whole trick: a tab with four sides is a card
    // sitting near a box, not a tab on it.
    expect(tabShape("n").open).toBe("border-b-0");
    expect(tabShape("s").open).toBe("border-t-0");
    expect(tabShape("w").open).toBe("border-r-0");
    expect(tabShape("e").open).toBe("border-l-0");
  });

  it("rounds only the two corners facing away from the box", () => {
    expect(tabShape("n").borderRadius).toBe("6px 6px 0 0");
    expect(tabShape("s").borderRadius).toBe("0 0 6px 6px");
    expect(tabShape("w").borderRadius).toBe("6px 0 0 6px");
    expect(tabShape("e").borderRadius).toBe("0 6px 6px 0");
  });

  it("mirrors exactly across opposite edges", () => {
    // border-radius reads top-left, top-right, bottom-right, bottom-left — so
    // flipping vertically reverses the four, while flipping horizontally swaps
    // them in pairs. `w` reversed is `w` again; only the pair swap gives `e`.
    const corners = (side: "n" | "s" | "e" | "w") => tabShape(side).borderRadius.split(" ");
    const [tl, tr, br, bl] = corners("n");
    expect(corners("s")).toEqual([bl, br, tr, tl]);
    const [wtl, wtr, wbr, wbl] = corners("w");
    expect(corners("e")).toEqual([wtr, wtl, wbl, wbr]);
  });

  it("takes a radius, so a heavier boundary can carry a heavier tab", () => {
    expect(tabShape("n", 10).borderRadius).toBe("10px 10px 0 0");
  });

  it("knows which edges run across the page and which run down it", () => {
    expect(isHorizontal("n")).toBe(true);
    expect(isHorizontal("s")).toBe(true);
    expect(isHorizontal("w")).toBe(false);
    expect(isHorizontal("e")).toBe(false);
  });
});

describe("a tab's label runs along the border it is attached to", () => {
  it("turns the label on a vertical edge, where it would otherwise stick out", () => {
    expect(tabRun("w").writingMode).toBe("vertical-rl");
    expect(tabRun("e").writingMode).toBe("vertical-rl");
  });

  it("leaves a horizontal edge alone — it already runs the right way", () => {
    expect(tabRun("n")).toEqual({});
    expect(tabRun("s")).toEqual({});
  });

  it("reads west bottom-to-top and east top-to-bottom, as a folder tab does", () => {
    // The text faces out of the fold. Reverse either and a reader tilts their
    // head the wrong way.
    expect(tabRun("w").transform).toBe("rotate(180deg)");
    expect(tabRun("e").transform).toBeUndefined();
  });
});

/* ── rail slots ────────────────────────────────────────────────────────
   The west wall carries ten tabs at the region. One column of ten is a wall of
   text; two layers halve it to five. */
describe("splitting an arm across its layers", () => {
  const items = ["a", "b", "c", "d", "e", "f", "g"];

  it("keeps reading order, so a wall still reads top to bottom", () => {
    // Round-robin would give [a,c,e,g] and [b,d,f] — the sequence shuffled.
    expect(splitLayers(items, 2)).toEqual([
      ["a", "b", "c", "d"],
      ["e", "f", "g"],
    ]);
  });

  it("halves a ten-tab wall to five deep", () => {
    const ten = Array.from({ length: 10 }, (_, i) => i);
    const cols = splitLayers(ten, 2);
    expect(cols).toHaveLength(2);
    expect(Math.max(...cols.map((c) => c.length))).toBe(5);
  });

  it("uses one layer when one is enough, rather than an empty second", () => {
    expect(splitLayers(["a"], 2)).toEqual([["a"]]);
    expect(splitLayers([], 2)).toEqual([[]]);
  });

  it("never returns an empty column", () => {
    for (const n of [1, 2, 3, 5, 9]) {
      for (const layers of [1, 2, 3]) {
        const cols = splitLayers(
          Array.from({ length: n }, (_, i) => i),
          layers,
        );
        expect(cols.every((c) => c.length > 0)).toBe(true);
      }
    }
  });

  it("loses nothing and duplicates nothing", () => {
    expect(splitLayers(items, 3).flat()).toEqual(items);
  });
});

describe("ordering slots along an arm", () => {
  it("runs start, middle, end — top to bottom, or west to east", () => {
    expect(alongRank("start")).toBeLessThan(alongRank("middle"));
    expect(alongRank("middle")).toBeLessThan(alongRank("end"));
  });

  it("treats an unstated position as the middle", () => {
    expect(alongRank(undefined)).toBe(alongRank("middle"));
    expect(alongRank("nonsense")).toBe(alongRank("middle"));
  });
});
