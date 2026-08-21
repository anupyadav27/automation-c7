import { describe, expect, it } from "vitest";
import {
  factsFor,
  relatedTo,
  relationshipWord,
  rollUp,
  sortRows,
  toTree,
  byService,
  serviceOf,
  countTree,
  typeFromKey,
  type RelatedNode,
  type RelatedRow,
  type SceneEdge,
  type SceneNode,
} from "./related";

/** A scene tree shaped like the real one: `type:id` keys, edges on asset ids. */
function scene(nodes: Array<Partial<SceneNode> & { key: string }>): SceneNode {
  return {
    key: "account:1",
    type: "account",
    id: "1",
    children: nodes.map((n) => ({
      type: n.key.split(":")[0],
      id: n.key.split(":")[1],
      name: n.key.split(":")[1],
      ...n,
    })) as SceneNode[],
  };
}

function edge(
  source: string,
  target: string,
  edge_type: string,
  extra: Partial<SceneEdge> = {},
): SceneEdge {
  return { source_asset_id: source, target_asset_id: target, edge_type, ...extra };
}

const ESTATE = scene([
  { key: "ec2.instance:i-1", name: "web-1" },
  { key: "ec2.volume:vol-1", name: "vol-1", detail: { size_gb: 100, volume_type: "gp3" } },
  { key: "kms.key:key-1", name: "key-1" },
  { key: "ec2.network_interface:eni-1", name: "eni-1" },
  { key: "ec2.security_group:sg-1", name: "sg-1" },
]);

const EDGES = [
  edge("i-1", "vol-1", "attached-to"),
  edge("vol-1", "key-1", "encrypted-by"),
  edge("i-1", "eni-1", "attached-to"),
  edge("eni-1", "sg-1", "protected-by"),
  edge("i-1", "subnet-1", "contained-in"),
];

describe("relatedTo", () => {
  it("walks the chain the user asked for: EC2 to EBS to KMS", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);
    const kms = rows.find((r) => r.type === "kms.key");

    expect(kms).toBeDefined();
    expect(kms?.depth).toBe(2);
    // The chain lives in `via` — this is the whole reason the table is flat.
    expect(kms?.via).toBe("vol-1");
  });

  it("leaves via empty at depth 1", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);
    const vol = rows.find((r) => r.type === "ec2.volume");

    expect(vol?.via).toBe("");
  });

  it("does not let a row inherit a sibling's via", () => {
    // The bug this pins: the SG is reached through the ENI, NOT through the
    // volume that happens to sit beside it in the queue.
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);

    expect(rows.find((r) => r.type === "ec2.security_group")?.via).toBe("eni-1");
  });

  it("respects maxDepth", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES, { maxDepth: 1 });

    expect(rows.every((r) => r.depth === 1)).toBe(true);
    expect(rows.find((r) => r.type === "kms.key")).toBeUndefined();
  });

  it("omits placement — Tier 1 already shows the subnet", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);

    expect(rows.some((r) => r.relationship.includes("contained"))).toBe(false);
  });

  it("reads incoming edges from the other end", () => {
    // A security group's panel must list what it PROTECTS.
    const rows = relatedTo("ec2.security_group:sg-1", ESTATE, EDGES);

    expect(rows[0]?.relationship).toBe("protects");
    expect(rows[0]?.type).toBe("ec2.network_interface");
  });

  it("never walks back into a cycle", () => {
    const cyclic = [edge("i-1", "vol-1", "attached-to"), edge("vol-1", "i-1", "attached-to")];
    const rows = relatedTo("ec2.instance:i-1", ESTATE, cyclic);

    expect(rows).toHaveLength(1);
    expect(rows[0]?.type).toBe("ec2.volume");
  });

  it("carries the facts a panel shows, from the Tier 2 catalog", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);

    expect(rows.find((r) => r.type === "ec2.volume")?.facts).toEqual([
      "size_gb=100",
      "volume_type=gp3",
    ]);
  });

  it("returns nothing for a resource that is not in the scene", () => {
    expect(relatedTo("ec2.instance:nope", ESTATE, EDGES)).toEqual([]);
  });

  it("keeps a dangling target as a row", () => {
    // The target was not collected, but the relationship is still true and
    // hiding it would make the panel claim the resource stands alone.
    const rows = relatedTo("ec2.instance:i-1", ESTATE, [
      edge("i-1", "vol-missing", "attached-to", { target_key: "ec2.volume" }),
    ]);

    expect(rows).toHaveLength(1);
    expect(rows[0]?.name).toBe("vol-missing");
    expect(rows[0]?.type).toBe("ec2.volume");
  });
});

describe("relationshipWord", () => {
  it("uses the plain edge type outbound", () => {
    expect(relationshipWord("protected-by", "out")).toBe("protected-by");
  });

  it("inverts inbound so the claim is not backwards", () => {
    expect(relationshipWord("protected-by", "in")).toBe("protects");
    expect(relationshipWord("encrypted-by", "in")).toBe("encrypts");
  });

  it("marks an unmapped inbound type rather than reusing the outbound word", () => {
    expect(relationshipWord("invented-by", "in")).toBe("invented-by (inbound)");
  });
});

describe("rollUp", () => {
  const row = (name: string): RelatedRow => ({
    relationship: "protects",
    edgeType: "protected-by",
    key: `ec2.security_group_rule:${name}`,
    name,
    type: "ec2.security_group_rule",
    facts: [],
    via: "",
    viaKey: "",
    depth: 1,
    direction: "in",
    corroborations: 1,
  });

  it("collapses a group past the limit and states the true total", () => {
    // 356 rules point at one security group. Showing 5 without saying so
    // would be a panel that lies.
    const out = rollUp(
      Array.from({ length: 356 }, (_, i) => row(`r${i}`)),
      5,
    );

    expect(out).toHaveLength(6);
    expect(out[5]?.rollup).toBe(356);
  });

  it("leaves a group at the limit alone", () => {
    const out = rollUp([row("a"), row("b")], 5);

    expect(out).toHaveLength(2);
    expect(out.some((r) => r.rollup)).toBe(false);
  });

  it("groups by relationship and type, not by count alone", () => {
    const mixed = [
      ...Array.from({ length: 6 }, (_, i) => row(`r${i}`)),
      { ...row("vol-1"), relationship: "attached", type: "ec2.volume" },
    ];
    const out = rollUp(mixed, 5);

    expect(out.filter((r) => r.type === "ec2.volume")).toHaveLength(1);
    expect(out.filter((r) => r.rollup)).toHaveLength(1);
  });
});

describe("sortRows", () => {
  it("puts a direct relation before a second-hop one", () => {
    const deep: RelatedRow = {
      relationship: "attached",
      edgeType: "attached-to",
      key: "a:1",
      name: "a",
      type: "a",
      facts: [],
      via: "x",
      viaKey: "x:1",
      depth: 2,
      direction: "out",
      corroborations: 1,
    };
    const shallow: RelatedRow = { ...deep, key: "b:1", name: "b", depth: 1, via: "" };

    expect(sortRows([deep, shallow])[0]?.depth).toBe(1);
  });
});

describe("factsFor", () => {
  it("skips empty values rather than showing a blank column", () => {
    const node = { key: "k", type: "t", id: "i", detail: { a: "", b: null, c: "x" } };

    expect(factsFor(node as SceneNode)).toEqual(["c=x"]);
  });

  it("caps how many facts a related row carries", () => {
    const node = {
      key: "k",
      type: "t",
      id: "i",
      detail: { a: 1, b: 2, c: 3, d: 4, e: 5 },
    };

    expect(factsFor(node as SceneNode)).toHaveLength(3);
  });

  it("is empty when the type has no Tier 2 columns", () => {
    expect(factsFor({ key: "k", type: "t", id: "i" } as SceneNode)).toEqual([]);
  });
});

describe("name collisions", () => {
  it("falls back to the id when a row would repeat the panel's own name", () => {
    // Two EKS nodes share a Name tag. `references onam-eks-node` on the panel
    // of a resource called `onam-eks-node` reads as self-reference.
    const twins = scene([
      { key: "ec2.instance:i-1", name: "eks-node" },
      { key: "ec2.instance:i-2", name: "eks-node" },
    ]);
    const rows = relatedTo("ec2.instance:i-1", twins, [edge("i-1", "i-2", "references")]);

    expect(rows[0]?.name).toBe("i-2");
  });

  it("leaves a distinct name alone", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);

    expect(rows.find((r) => r.type === "ec2.volume")?.name).toBe("vol-1");
  });
});

describe("depth beyond the first hop", () => {
  it("does not expand what else uses a shared dependency", () => {
    // An EC2 panel must not list every other interface in its security group.
    const shared = scene([
      { key: "ec2.instance:i-1", name: "web-1" },
      { key: "ec2.security_group:sg-1", name: "sg-1" },
      { key: "ec2.network_interface:eni-9", name: "eni-9" },
    ]);
    const rows = relatedTo("ec2.instance:i-1", shared, [
      edge("i-1", "sg-1", "protected-by"),
      edge("eni-9", "sg-1", "protected-by"),
    ]);

    expect(rows.map((r) => r.type)).toEqual(["ec2.security_group"]);
  });

  it("still follows what a dependency itself depends on", () => {
    // instance -> volume -> key stays, because both hops are outbound.
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);

    expect(rows.find((r) => r.type === "kms.key")?.via).toBe("vol-1");
  });
});

describe("typeFromKey", () => {
  it("reads the service out of an uncollected ARN", () => {
    // `arn:aws:execute-api:…` under a column headed "type" is not an answer.
    expect(typeFromKey("arn:aws:execute-api:ap-south-1:588:vgs/*/*")).toBe(
      "execute-api (uncollected)",
    );
  });

  it("keeps a normal scene key's type", () => {
    expect(typeFromKey("ec2.volume:vol-1")).toBe("ec2.volume");
  });
});

describe("children are not repeated", () => {
  it("omits a direct child that also has an edge back to the parent", () => {
    // A Lambda draws its 7 versions in the Attached section; the versions all
    // reference the function, which would list them a second time.
    const fn: SceneNode = {
      key: "lambda.function:f",
      type: "lambda.function",
      id: "f",
      name: "f",
      children: [{ key: "lambda.version:f:1", type: "lambda.version", id: "f:1" }],
    };
    const tree: SceneNode = { key: "account:1", type: "account", id: "1", children: [fn] };

    const rows = relatedTo("lambda.function:f", tree, [edge("f:1", "f", "references")]);

    expect(rows).toEqual([]);
  });
});

describe("toTree", () => {
  it("hangs a second hop under the resource it came through", () => {
    const rows = relatedTo("ec2.instance:i-1", ESTATE, EDGES);
    const tree = toTree(rows);

    const vol = tree.find((n) => n.type === "ec2.volume");
    expect(vol?.children.map((c) => c.type)).toEqual(["kms.key"]);
    // and the key is NOT also a root
    expect(tree.some((n) => n.type === "kms.key")).toBe(false);
  });

  it("assembles on the key, not the display name", () => {
    // Two nodes share a Name tag; matching on `via` would hang the child
    // under whichever twin sorted first.
    const twins = scene([
      { key: "ec2.instance:i-1", name: "root" },
      { key: "ec2.volume:v-1", name: "same" },
      { key: "ec2.volume:v-2", name: "same" },
      { key: "kms.key:k-1", name: "k" },
    ]);
    const tree = toTree(
      relatedTo("ec2.instance:i-1", twins, [
        edge("i-1", "v-1", "attached-to"),
        edge("i-1", "v-2", "attached-to"),
        edge("v-2", "k-1", "encrypted-by"),
      ]),
    );

    const withKey = tree.filter((n) => n.children.length);
    expect(withKey).toHaveLength(1);
    expect(withKey[0]?.key).toBe("ec2.volume:v-2");
  });

  it("keeps a row whose parent was rolled away", () => {
    // Dropping it would silently lose a real relationship.
    const orphan: RelatedRow = {
      relationship: "encrypted-by",
      edgeType: "encrypted-by",
      key: "kms.key:k",
      name: "k",
      type: "kms.key",
      facts: [],
      via: "gone",
      viaKey: "ec2.volume:missing",
      depth: 2,
      direction: "out",
      corroborations: 1,
    };
    expect(toTree([orphan]).map((n) => n.key)).toEqual(["kms.key:k"]);
  });

  it("rolls up per branch, not across the whole panel", () => {
    const kid = (parent: string, i: number): RelatedRow => ({
      relationship: "protects",
      edgeType: "protected-by",
      key: `eni:${parent}-${i}`,
      name: `eni-${i}`,
      type: "ec2.network_interface",
      facts: [],
      via: parent,
      viaKey: parent,
      depth: 2,
      direction: "in",
      corroborations: 1,
    });
    const sg = (n: string): RelatedRow => ({
      relationship: "protected-by",
      edgeType: "protected-by",
      key: n,
      name: n,
      type: "ec2.security_group",
      facts: [],
      via: "",
      viaKey: "",
      depth: 1,
      direction: "out",
      corroborations: 1,
    });
    const rows = [
      sg("sg-a"),
      sg("sg-b"),
      ...Array.from({ length: 6 }, (_, i) => kid("sg-a", i)),
      ...Array.from({ length: 6 }, (_, i) => kid("sg-b", i)),
    ];

    const tree = toTree(rows, 5);

    // Six under each group becomes 5 + a rollup, twice — not one rollup of 12.
    for (const branch of tree) {
      expect(branch.children).toHaveLength(6);
      expect(branch.children.filter((c) => c.rollup)).toHaveLength(1);
      expect(branch.children.find((c) => c.rollup)?.rollup).toBe(6);
    }
  });

  it("counts every row in the tree, not just the roots", () => {
    const tree = toTree(relatedTo("ec2.instance:i-1", ESTATE, EDGES));
    expect(countTree(tree)).toBe(relatedTo("ec2.instance:i-1", ESTATE, EDGES).length);
  });
});

describe("byService", () => {
  const node = (type: string, name: string, rel = "references"): RelatedNode => ({
    relationship: rel,
    edgeType: rel,
    key: `${type}:${name}`,
    name,
    type,
    facts: [],
    via: "",
    viaKey: "",
    depth: 1,
    direction: "out",
    corroborations: 1,
    children: [],
  });

  it("says the service once, not once per row", () => {
    // The defect: `referenced by / referenced by / referenced by` with the
    // service invisible on every line.
    const out = byService([
      node("iam.role", "r1"),
      node("iam.instance_profile", "p1"),
      node("ec2.volume", "v1"),
    ]);

    expect(out.map((s) => s.service)).toEqual(["IAM", "EC2"]);
    expect(out[0]?.types.map((t) => t.type)).toEqual(["iam.instance_profile", "iam.role"]);
  });

  it("puts the most-entangled service first", () => {
    const out = byService([
      node("iam.role", "r1"),
      node("ec2.volume", "v1"),
      node("ec2.volume", "v2"),
      node("ec2.eni", "e1"),
    ]);

    expect(out[0]?.service).toBe("EC2");
    expect(out[0]?.total).toBe(3);
  });

  it("caps nothing — the view scrolls instead", () => {
    // 356 rule records keep all 356; a heading count plus a scrollable body
    // tells the truth where `+351 more` only hints at it.
    const many = Array.from({ length: 356 }, (_, i) => node("ec2.sgr", `r${i}`));
    const out = byService(many);

    expect(out[0]?.types[0]?.total).toBe(356);
    expect(out[0]?.types[0]?.rows).toHaveLength(356);
  });

  it("carries one verb per type group", () => {
    const out = byService([
      node("ec2.eni", "a", "protects"),
      node("ec2.eni", "b", "protects"),
      node("ec2.eni", "c", "attached"),
    ]);

    expect(out[0]?.types[0]?.relationship).toBe("protects");
  });

  it("shortens a service acronym and leaves a word alone", () => {
    expect(serviceOf("iam.role")).toBe("IAM");
    expect(serviceOf("ec2.volume")).toBe("EC2");
    expect(serviceOf("autoscaling.auto_scaling_group")).toBe("autoscaling");
  });
});

describe("a destination is not a resource", () => {
  it("drops a CIDR target", () => {
    // `routes-to-internet` carries `0.0.0.0/0` — a fact about the route table,
    // not something to click. It rendered as a service group headed `0`.
    const rows = relatedTo(
      "ec2.route_table:rtb-1",
      scene([{ key: "ec2.route_table:rtb-1", name: "rtb-1" }]),
      [edge("rtb-1", "0.0.0.0/0", "routes-to-internet")],
    );

    expect(rows).toEqual([]);
  });

  it("keeps an uncollected resource, which is a real reference", () => {
    const rows = relatedTo(
      "ec2.route_table:rtb-1",
      scene([{ key: "ec2.route_table:rtb-1", name: "rtb-1" }]),
      [
        edge("rtb-1", "arn:aws:ec2:ap-south-1:1:natgateway/nat-9", "routes-to", {
          target_key: "ec2.nat_gateway",
        }),
      ],
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]?.type).toBe("ec2.nat_gateway");
  });
});

/* ── wording an edge for the map ───────────────────────────────────────
   A panel words a relationship from the point of view of the resource whose
   panel it is. A line on the map has no point of view — it is drawn between
   two things and the reader may be at either end — so it carries the edge as
   recorded and reads the same from both. */

describe("edgeType", () => {
  const edges = [
    { source_asset_id: "eni-1", target_asset_id: "sg-1", edge_type: "protected-by" },
    { source_asset_id: "vol-1", target_asset_id: "key-1", edge_type: "encrypted-by" },
    { source_asset_id: "rt-1", target_asset_id: "igw-1", edge_type: "routes-to-internet" },
    { source_asset_id: "rt-1", target_asset_id: "nat-1", edge_type: "routes-to" },
  ];
  const tree = {
    key: "acct",
    type: "account",
    id: "acct",
    children: [
      { key: "eni-1", type: "ec2.network_interface", id: "eni-1" },
      { key: "sg-1", type: "ec2.security_group", id: "sg-1" },
      { key: "vol-1", type: "ec2.volume", id: "vol-1" },
      { key: "key-1", type: "kms.key", id: "key-1" },
      { key: "rt-1", type: "ec2.route_table", id: "rt-1" },
      { key: "igw-1", type: "ec2.internet_gateway", id: "igw-1" },
      { key: "nat-1", type: "ec2.nat_gateway", id: "nat-1" },
    ],
  };

  it("reads the same from the subject's end and the object's end", () => {
    // The interface points at the group; the group's own panel says it
    // PROTECTS the interface. One edge, one arrow, either way round.
    const fromSubject = relatedTo("eni-1", tree, edges).find((r) => r.key === "sg-1");
    const fromObject = relatedTo("sg-1", tree, edges).find((r) => r.key === "eni-1");

    expect(fromSubject!.relationship).toBe("protected-by");
    expect(fromObject!.relationship).toBe("protects");
    expect(fromSubject!.edgeType).toBe("protected-by");
    expect(fromObject!.edgeType).toBe("protected-by");
  });

  it("keeps two edges apart that share one inverse word", () => {
    // `routes-to` and `routes-to-internet` both invert to `routed from`, so
    // deriving the edge back from the wording labelled an ordinary route as
    // the one reaching the open internet.
    const rows = relatedTo("rt-1", tree, edges);

    expect(rows.find((r) => r.key === "igw-1")!.edgeType).toBe("routes-to-internet");
    expect(rows.find((r) => r.key === "nat-1")!.edgeType).toBe("routes-to");
  });

  it("survives a roll-up, so a summary row still names its edge", () => {
    const rolled = rollUp(relatedTo("vol-1", tree, edges), 0);

    expect(rolled.every((r) => r.edgeType)).toBe(true);
  });
});
