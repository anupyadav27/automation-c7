/**
 * What a resource is connected to, as panel rows.
 *
 * Pure, so a test can call it without a browser. Everything here is a decision
 * about WHICH rows a panel shows and in what order; the JSX only draws them.
 *
 * `relatedTo` walks the graph and returns flat rows; `toTree` nests them into
 * the hierarchy the panel draws. Both are exported because they answer
 * different questions — the flat form is what a test asserts on, the nested
 * form is what a reader sees.
 *
 * Measured on the live graph: 280 assets reach depth 1, 19 reach depth 2, 11
 * reach 3 and one reaches 4; the median asset has ONE distinct relation. That
 * shallowness is why every branch can afford to open by default and why the
 * indentation never runs away.
 */

export type SceneNode = {
  key: string;
  type: string;
  id: string;
  name?: string | null;
  detail?: Record<string, unknown> | null;
  children?: SceneNode[];
};

export type SceneEdge = {
  source_asset_id?: string;
  target_asset_id?: string;
  source_key?: string;
  target_key?: string;
  edge_type?: string;
  via?: string;
  confidence?: string;
  corroborations?: number | string;
};

export type RelatedRow = {
  relationship: string;
  /**
   * The edge as RECORDED, subject to object, whichever end asked for it.
   *
   * `relationship` is worded from the point of view of the resource whose
   * panel the row sits on — a security group's row says `protects`, and the
   * interface's row for that same edge says `protected-by`. A line on the map
   * has no point of view, so it needs the recorded direction instead.
   *
   * Carried rather than derived by inverting `relationship`, because that
   * inversion is not one-to-one: `routes-to` and `routes-to-internet` share
   * the inverse word `routed from`, so reversing it labelled five ordinary
   * route edges as the one that reaches the open internet. */
  edgeType: string;
  key: string;
  name: string;
  type: string;
  facts: string[];
  /** The resource this was reached THROUGH, for display. */
  via: string;
  /** That resource's key. Names are not unique — two EKS nodes share a Name
      tag — so the tree is assembled on this, never on `via`. */
  viaKey: string;
  depth: number;
  direction: "out" | "in";
  corroborations: number;
  /** Set when this row stands for a group too large to list. */
  rollup?: number;
};

/**
 * The same relationship read from the other end.
 *
 * An edge is directional but relatedness is not: a security group's panel must
 * list the interfaces it PROTECTS, which are all incoming edges. Reusing the
 * outgoing word there would label them "protected-by", claiming the group is
 * protected by the thing it protects — backwards, and the kind of wrong that
 * reads as plausible.
 */
export const INVERSE: Record<string, string> = {
  "protected-by": "protects",
  "attached-to": "attached",
  "encrypted-by": "encrypts",
  "contained-in": "contains",
  "created-from": "source of",
  "accessible-by": "grants access to",
  "constrained-by": "constrains",
  "routes-to": "routed from",
  "routes-to-internet": "routed from",
  assumes: "assumed by",
  references: "referenced by",
  fronts: "fronted by",
};

/**
 * Placement, which Tier 1 already shows.
 *
 * Every resource is contained-in its subnet, VPC, region and account, and the
 * panel header states all four. Repeating them as relations would put four
 * rows nobody reads at the top of every panel in the estate.
 */
const PLACEMENT = new Set(["contained-in"]);

/**
 * A destination is not a resource.
 *
 * `routes-to-internet` carries `0.0.0.0/0` as its target — the CIDR the route
 * matches, which is a FACT about the route table rather than a thing anyone
 * can click. Rendered as a relation it produced a service group headed `0`,
 * because `0.0.0.0/0`.split(".")[0] is `0`.
 *
 * Dangling targets are still kept: an ARN or a prefixed id names a resource we
 * simply did not collect, and hiding those would make a resource look isolated
 * when it is not. This drops only the values that name no resource at all.
 */
const NOT_A_RESOURCE = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$|^::\/0$|^[0-9a-f:]+\/\d{1,3}$/i;

/** Past this, a group becomes one summary row. */
export const GROUP_LIMIT = 5;

export function relationshipWord(edgeType: string, direction: "out" | "in"): string {
  if (direction === "out") return edgeType;
  return INVERSE[edgeType] ?? `${edgeType} (inbound)`;
}

/** Flatten the scene tree into a lookup by asset key. */
export function indexNodes(root: SceneNode | null | undefined): Map<string, SceneNode> {
  const out = new Map<string, SceneNode>();
  const walk = (node: SceneNode) => {
    if (node.key) out.set(node.key, node);
    for (const child of node.children ?? []) walk(child);
  };
  if (root) walk(root);
  return out;
}

/**
 * The scene keys nodes as `type:id` but edges carry raw asset ids, so the two
 * cannot be joined directly. Build the bridge once.
 */
export function indexByAssetId(nodes: Map<string, SceneNode>): Map<string, SceneNode> {
  const out = new Map<string, SceneNode>();
  for (const node of nodes.values()) {
    out.set(node.key, node);
    if (node.id) out.set(node.id, node);
    const arn = (node as { arn?: string | null }).arn;
    if (arn) out.set(arn, node);
  }
  return out;
}

/** The Tier 2 columns, as `label=value`, in catalog order. */
export function factsFor(node: SceneNode | undefined, limit = 3): string[] {
  if (!node?.detail) return [];
  const out: string[] = [];
  for (const [label, value] of Object.entries(node.detail)) {
    if (out.length >= limit) break;
    if (value === null || value === undefined || value === "") continue;
    out.push(`${label}=${value}`);
  }
  return out;
}

/**
 * A resource type from whatever the edge could give us.
 *
 * The scene keys nodes `service.type:id`, but an edge to something that was
 * never collected falls back to the raw target string — often an ARN. Printing
 * `arn:aws:execute-api:ap-south-1:588…:vgs6w2yd2d/*` under a column headed
 * "type" is not an answer; `execute-api` is.
 */
export function typeFromKey(key: string): string {
  if (key.startsWith("arn:")) {
    const service = key.split(":")[2];
    return service ? `${service} (uncollected)` : "uncollected";
  }
  const head = key.split(":")[0] ?? "";
  return head.includes(".") ? head : key;
}

type Step = { node: SceneNode; depth: number; viaName: string; viaKey: string };

/**
 * Every resource reachable from `rootKey`, to `maxDepth`.
 *
 * Walks both directions, never revisits a node — the live graph has 34
 * bidirectional pairs, and without that guard an instance appears under its
 * own volume — and skips placement edges.
 */
export function relatedTo(
  rootKey: string,
  root: SceneNode | null | undefined,
  edges: SceneEdge[],
  options: { maxDepth?: number; groupLimit?: number } = {},
): RelatedRow[] {
  const maxDepth = options.maxDepth ?? 2;
  const groupLimit = options.groupLimit ?? GROUP_LIMIT;
  const nodes = indexNodes(root);
  const byAsset = indexByAssetId(nodes);
  const start = nodes.get(rootKey);
  if (!start) return [];

  const out = new Map<string, SceneEdge[]>();
  const inn = new Map<string, SceneEdge[]>();
  for (const edge of edges) {
    if (PLACEMENT.has(edge.edge_type ?? "")) continue;
    const s = edge.source_asset_id;
    const t = edge.target_asset_id;
    if (s) out.set(s, [...(out.get(s) ?? []), edge]);
    if (t) inn.set(t, [...(inn.get(t) ?? []), edge]);
  }

  const idsOf = (node: SceneNode) =>
    [node.key, node.id, (node as { arn?: string | null }).arn].filter(Boolean) as string[];

  const rootName = start.name || start.id;
  const seen = new Set(idsOf(start));
  // Direct children already have their own section above the table — a Lambda
  // draws its seven versions there, and `lambda.version -references-> the
  // function` would list all seven again under Related. The same resource
  // twice on one panel reads as fourteen.
  for (const child of start.children ?? []) for (const id of idsOf(child)) seen.add(id);
  const rows: RelatedRow[] = [];
  // The queue carries each node's own `via` label, so a row can never inherit
  // its sibling's path. Parallel arrays got this wrong once and reported the
  // KMS key as reached through the instance rather than through its volume.
  const queue: Step[] = [{ node: start, depth: 0, viaName: "", viaKey: "" }];

  while (queue.length) {
    const step = queue.shift() as Step;
    if (step.depth >= maxDepth) continue;
    const depth = step.depth + 1;

    for (const id of idsOf(step.node)) {
      const outgoing = (out.get(id) ?? []).map((e) => [e, "out"] as const);
      // Inbound edges answer "what uses this", which is a real question about
      // the resource in the panel and a different question about its
      // dependencies. Expanding inbound at the second hop turned an EC2 panel
      // into a list of every other interface sharing its security group — 21
      // rows, 16 of them about the group rather than the instance. Beyond the
      // first hop the walk follows only what a resource DEPENDS ON, which is
      // what keeps `instance → volume → key` while dropping
      // `instance → group → everything else in the group`.
      const incoming = step.depth === 0 ? (inn.get(id) ?? []).map((e) => [e, "in"] as const) : [];
      for (const [edge, direction] of [...outgoing, ...incoming]) {
        const otherId = direction === "out" ? edge.target_asset_id : edge.source_asset_id;
        if (!otherId || seen.has(otherId)) continue;
        if (NOT_A_RESOURCE.test(otherId)) continue;
        const other = byAsset.get(otherId);
        const otherKey = other?.key ?? otherId;
        if (seen.has(otherKey)) continue;
        seen.add(otherId);
        seen.add(otherKey);

        // Two EKS nodes carry the same Name tag, so a row could read
        // `references onam-eks-dedicated-all-node` on the panel of a resource
        // with exactly that name — indistinguishable from self-reference. A
        // row that cannot be told apart from the thing it sits under has to
        // fall back to the id, which is unique by construction.
        const label = other?.name || other?.id || otherId;
        const name = label === rootName ? (other?.id ?? otherId) : label;
        rows.push({
          relationship: relationshipWord(edge.edge_type ?? "references", direction),
          edgeType: edge.edge_type ?? "references",
          key: otherKey,
          name,
          // A dangling edge has no node to read a type from, and the scene's
          // fallback key is sometimes a raw ARN — `arn:aws:execute-api:…` in
          // a column headed "type" is not a type. Recover the service from the
          // ARN rather than printing the whole thing.
          type:
            other?.type ??
            typeFromKey((direction === "out" ? edge.target_key : edge.source_key) ?? otherId),
          facts: factsFor(other),
          // Empty at depth 1: the resource itself is the path, and printing
          // its own name in every row is noise.
          via: step.viaName,
          viaKey: step.viaKey,
          depth,
          direction,
          corroborations: Number(edge.corroborations ?? 1) || 1,
        });
        if (other) queue.push({ node: other, depth, viaName: name, viaKey: otherKey });
      }
    }
  }

  return rollUp(sortRows(rows), groupLimit);
}

/**
 * Shallow before deep, then by relationship, then by name.
 *
 * Depth first because a direct relation is the one being asked about; the
 * second hop is context. Name last so repeated runs of the same kind read as a
 * block rather than as an unsorted pile.
 */
export function sortRows(rows: RelatedRow[]): RelatedRow[] {
  return [...rows].sort(
    (a, b) =>
      a.depth - b.depth ||
      a.relationship.localeCompare(b.relationship) ||
      a.type.localeCompare(b.type) ||
      a.name.localeCompare(b.name),
  );
}

/**
 * Collapse an oversized group of identical-shaped rows into one.
 *
 * A security group is the case that forces this: 356 rule records point at it,
 * and listing them turns its panel into a wall. The group keeps its first few
 * rows and gains a summary row carrying the true total, so the count is never
 * silently truncated — a panel that shows 5 of 356 without saying so is a
 * panel that lies.
 */
export function rollUp(rows: RelatedRow[], limit = GROUP_LIMIT): RelatedRow[] {
  const groups = new Map<string, RelatedRow[]>();
  for (const row of rows) {
    const key = `${row.depth}|${row.relationship}|${row.type}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  const out: RelatedRow[] = [];
  for (const group of groups.values()) {
    const head = group[0];
    if (group.length <= limit || !head) {
      out.push(...group);
      continue;
    }
    out.push(...group.slice(0, limit));
    out.push({ ...head, key: `${head.key}#rollup`, name: "", facts: [], rollup: group.length });
  }
  return out;
}

/** A row with the rows reached THROUGH it hanging beneath. */
export type RelatedNode = RelatedRow & { children: RelatedNode[] };

/**
 * Nest the flat rows into the hierarchy they describe.
 *
 * Assembled on `viaKey`, never on `via`: two EKS nodes share a Name tag, and
 * matching on the display name would hang a key under the wrong volume.
 *
 * A row whose parent is missing — its `viaKey` was rolled up, or the walk
 * stopped short — is promoted to the top rather than dropped. Losing a real
 * relationship because its intermediate hop was summarised would be a silent
 * lie about what the resource touches.
 */
export function toTree(rows: RelatedRow[], limit = GROUP_LIMIT): RelatedNode[] {
  const nodes = new Map<string, RelatedNode>();
  for (const row of rows) nodes.set(row.key, { ...row, children: [] });

  const roots: RelatedNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.viaKey ? nodes.get(node.viaKey) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  // Roll up per branch, not across the whole panel: five interfaces under one
  // security group and five under another are two groups of five, not one of
  // ten.
  const prune = (list: RelatedNode[]): RelatedNode[] => {
    for (const n of list) n.children = prune(n.children);
    return rollUp(sortRows(list) as RelatedNode[], limit) as RelatedNode[];
  };
  return prune(roots);
}

/** Every row in a tree, for counting what the header promises. */
export function countTree(nodes: RelatedNode[]): number {
  return nodes.reduce((n, x) => n + 1 + countTree(x.children), 0);
}

/** A resource type inside a service, with the verb that reaches it. */
export type TypeGroup = {
  type: string;
  /** Read from this resource's end: `protects`, not `protected-by`. */
  relationship: string;
  rows: RelatedNode[];
  total: number;
};

/** A cloud service, and the types of it this resource touches. */
export type ServiceGroup = { service: string; types: TypeGroup[]; total: number };

/**
 * `iam.instance_profile` -> `IAM`. The word a reader groups by.
 *
 * AWS names a service in the type prefix, which is why this needs no table:
 * `ec2.volume` and `ec2.network_interface` are both EC2, and saying so once is
 * the difference between a list of nine rows and a list of three groups.
 */
export function serviceOf(type: string): string {
  const head = (type.split(".")[0] ?? type).replace(/-/g, " ");
  return head.length <= 4 ? head.toUpperCase() : head;
}

/**
 * Group the related set by service, then by type.
 *
 * A flat list repeated the verb on every line — `referenced by`, `referenced
 * by`, `referenced by` — and never said the service at all. The hierarchy was
 * always in the data; this stops throwing it away.
 *
 * Nothing is capped. A type with 356 members keeps all 356 and the VIEW
 * scrolls, because a count on a heading plus a scrollable body tells the truth
 * where `+351 more` only hints at it.
 */
export function byService(nodes: RelatedNode[], _limit?: number): ServiceGroup[] {
  const services = new Map<string, Map<string, RelatedNode[]>>();
  for (const node of nodes) {
    const service = serviceOf(node.type);
    const types = services.get(service) ?? new Map<string, RelatedNode[]>();
    types.set(node.type, [...(types.get(node.type) ?? []), node]);
    services.set(service, types);
  }

  return (
    [...services.entries()]
      .map(([service, types]) => ({
        service,
        total: [...types.values()].reduce((n, r) => n + r.length, 0),
        types: [...types.entries()]
          .map(([type, rows]) => ({
            type,
            // One verb per type group. Where members disagree the commonest
            // wins, because a heading that lists every verb is the flat list again.
            relationship: commonest(rows.map((r) => r.relationship)),
            rows,
            total: rows.length,
          }))
          .sort((a, b) => b.total - a.total || a.type.localeCompare(b.type)),
      }))
      // Biggest service first: what a resource touches most is what it is most
      // entangled with, and that is what an investigation starts from.
      .sort((a, b) => b.total - a.total || a.service.localeCompare(b.service))
  );
}

function commonest(values: string[]): string {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
}
