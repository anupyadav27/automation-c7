/**
 * The renderer's decisions, separated from the rendering.
 *
 * Every function here is pure: values in, values out, no SCENE, no React, no
 * DOM. That is the whole point. Six defects in one week type-checked, passed
 * lint, passed the build and rendered — a wrap drawn before the cluster that
 * owned it, a grey ramp running the wrong way, 371 tags landing on records that
 * never draw. None of those are type errors. All of them are decisions, and a
 * decision can only be tested if something can call it without a browser.
 *
 * `architecture.tsx` keeps the SceneNode adapters — one-liners that pull
 * `category`, `sub`, `kind` off a node and hand them here — so the route still
 * reads the same and the vocabulary of the scene stays in one file.
 */

/* ── the neutral ramp ──────────────────────────────────────────────────
 *
 * Boxes the provider prescribes no colour for: an EKS cluster, a scaling group,
 * a rule wrap. Never a hue — inventing one would assert a convention AWS has
 * not set. A three-step grey that lightens INWARD, so nesting reads without a
 * label:
 *
 *     orchestrator   light grey     EKS, the scaling group
 *       service      lightest grey  the EC2 group inside it
 *         resource   white          the instance itself, with its icon
 *
 * The eye follows the lightening to the thing in focus.
 *
 * An inline style, not a Tailwind class. A class whose arbitrary value is built
 * at runtime is invisible to the JIT, which scans source TEXT for names it can
 * resolve: it type-checked, it rendered, the class appeared in the HTML, and no
 * CSS rule existed. `npm run check` refuses the pattern outright now.
 */
export const grey = (toward: number) => ({
  background:
    `color-mix(in srgb, var(--color-surface) ${toward}%, ` + `var(--color-surface-tertiary))`,
});

/** How far toward white each rung sits. Higher is lighter. */
export const RAMP = { orchestrator: 45, group: 75, resource: 100 } as const;

/* ── provider-prescribed containers ───────────────────────────────────
 *
 * Where AWS DOES prescribe a colour — the five Architecture Group boundaries —
 * the diagram uses AWS's own. The grey ramp is for everything else.
 */
export const CONTAINER_STYLE: Record<
  string,
  { rgb: string; dashed?: boolean; width: number; fill: number }
> = {
  account: { rgb: "231 21 123", width: 2, fill: 0 }, // #E7157B
  region: { rgb: "0 164 166", width: 2, fill: 3, dashed: true }, // #00A4A6
  network: { rgb: "140 79 255", width: 2, fill: 5 }, // #8C4FFF
  zone: { rgb: "0 164 166", width: 1, fill: 0, dashed: true },
  segment: { rgb: "0 164 166", width: 1, fill: 4 },
  // A public subnet is green in AWS's pack — it is the one that faces out.
  "segment:public": { rgb: "122 161 22", width: 1, fill: 5 }, // #7AA116
};

export const containerStyle = (role: string, tier?: string | null) => {
  const spec = CONTAINER_STYLE[tier ? `${role}:${tier}` : role] ?? CONTAINER_STYLE[role];
  if (!spec) return undefined;
  return {
    border: `${spec.width}px ${spec.dashed ? "dashed" : "solid"} rgb(${spec.rgb} / 45%)`,
    background: spec.fill ? `rgb(${spec.rgb} / ${spec.fill}%)` : undefined,
  };
};

/* ── codes, and the arm each one rides ────────────────────────────────── */

export const CODES: Record<string, { code: string; label: string }> = {
  "protected-by": { code: "sg", label: "security group" },
  "routes-through": { code: "rt", label: "route table" },
  "encrypted-by": { code: "kms", label: "kms key" },
  assumes: { code: "iam", label: "iam role" },
  "can-access": { code: "iam", label: "iam role" },
  "accessible-by": { code: "pol", label: "resource policy" },
};

export const CODE_ORDER = ["sg", "rt", "iam", "kms", "pol"];

/* A tag exists so a reader can FIND the thing governing a resource, and
 * "somewhere on one of four borders" is not finding it. Colour carries the
 * direction: an `iam-1` chip and the border it came from are the same hue, so
 * the eye goes to the right arm without reading a word.
 *
 * Deliberately not the semantic ramp — these are wayfinding, not severity, and
 * a reader who has learned that red means critical must not read a red tag as
 * a problem. */
export const CODE_ARM: Record<string, { arm: string; rgb: string }> = {
  iam: { arm: "n", rgb: "139 92 246" }, // violet — top, who may act
  kms: { arm: "n", rgb: "139 92 246" },
  pol: { arm: "e", rgb: "13 148 136" }, // teal — right, how it is run
  sg: { arm: "w", rgb: "217 119 6" }, //  amber — left, how traffic moves
  rt: { arm: "w", rgb: "217 119 6" },
};

/** The chip style for a code, matching the border its target rides. */
export const codeTone = (code: string) => {
  const spec = CODE_ARM[code.split("-")[0] ?? ""];
  if (!spec) return undefined;
  return {
    background: `rgb(${spec.rgb} / 10%)`,
    borderColor: `rgb(${spec.rgb} / 35%)`,
    color: `rgb(${spec.rgb})`,
  };
};

/**
 * A tint per category group on a rail, so the groups on one arm stop running
 * together into a single list.
 *
 * Keyed on the code family where there is one, so a group and the tags that
 * point at it share a hue: an `iam-1` chip and the identity group it came from
 * look the same. Categories with no code family fall back to a neutral tint —
 * a colour with no tag to match would be decoration.
 */
export const RAIL_TINT: Record<string, string> = {
  identity: "139 92 246",
  encryption: "139 92 246",
  secrets: "139 92 246",
  certificates: "139 92 246",
  firewall: "217 119 6",
  routing: "217 119 6",
  dns: "217 119 6",
  connectivity: "217 119 6",
  audit: "13 148 136",
  config: "13 148 136",
  observability: "13 148 136",
  provisioning: "13 148 136",
  deploy: "13 148 136",
  posture: "13 148 136",
};

/**
 * Fallback by CATEGORY, so no tab is left white.
 *
 * `RAIL_TINT` keys on the subcategory because that is where a code family lives
 * — `identity` and `firewall` have tags pointing at them and must match. But
 * most subcategories have no code family, so most of the west wall came out
 * white: eight tabs reading query, media, workflow, catalog, containers with
 * nothing to say they were all operations. White is not neutral on a rail, it
 * is the absence of a group.
 */
/* Replaced by the provider's own palette — see `railToneFor`. AWS ships a
   category colour for every service it makes, and inventing a second set beside
   it meant a security group's icon was red while the tab naming it was violet. */

/**
 * The rail tint for a domain — from the PROVIDER's palette.
 *
 * `colour` is `colourFor(type)` in `aws-icons`, which is AWS's own category
 * colour for that service: compute orange, storage green, network purple,
 * security red, database magenta. Using it means the tab naming a group and the
 * icons inside that group are the same hue, and there is exactly one colour
 * system on the canvas rather than two that disagree — a security group's icon
 * was AWS red while the tab naming it was a violet nobody prescribed.
 */
export const railToneFor = (colour: string | undefined) => {
  if (!colour) return undefined;
  const rgb = colour.replace(/^rgba?\(|\)$/g, "");
  return { background: `rgb(${rgb} / 10%)`, borderColor: `rgb(${rgb} / 40%)` };
};

/**
 * What a rail tab is called.
 *
 * `training` alone does not say what it is; `ai · training` does. A subcategory
 * is only unique inside its category — `config` is governance, `connectivity`
 * is network, and `transfer` is storage AND migration — so the bare noun asks a
 * reader to already know the taxonomy in order to read the diagram.
 *
 * Dropped where the category adds nothing: `security · identity` is longer than
 * `identity` and no clearer, because nothing else in the model is called
 * identity.
 */
const SELF_EVIDENT = new Set([
  "identity",
  // Nothing else in the model is called policy, and `security · policy` beside
  // a tab reading `identity` makes two halves of one question look like two
  // different questions.
  "policy",
  "encryption",
  "certificates",
  "secrets",
  "firewall",
  "routing",
  "dns",
  "connectivity",
  "observability",
  "audit",
  "posture",
  "provisioning",
]);

export const railLabel = (category: string, sub: string) =>
  SELF_EVIDENT.has(sub) ? sub : `${category} · ${sub}`;

/**
 * How many layers an arm actually needs.
 *
 * Only splits when the tabs will not fit the wall it is on — a second layer on
 * a wall with room is two short columns where one would have read straight
 * down, and it costs the container real width it did not have to spend.
 *
 * `height` is the box's own measured height, which is known before anything
 * draws because sizing is bottom-up. That keeps the answer deterministic and
 * offline: same estate, same layout, on any screen.
 */
/**
 * How many layers an arm needs so its tabs fit inside the box's own length.
 *
 * `max` is the model's declared depth for the slot — a PREFERENCE, and it used
 * to be a hard ceiling. An arm with more tabs than `max` layers could hold
 * simply overflowed: five tabs against a 400px wall drew past the bottom of
 * the VPC they named, because the answer was clamped to 2 before it was ever
 * compared with the room available.
 *
 * A container reserves what its rails need, so needing a third layer costs
 * width, not correctness. The declared depth still decides the COMMON case;
 * it no longer overrules arithmetic that says the tabs do not fit.
 */
export function layersNeeded(tabs: number, height: number, max: number, tabLength = 150) {
  if (tabs <= 1) return 1;
  const perLayer = Math.max(1, Math.floor(height / tabLength));
  const needed = Math.ceil(tabs / perLayer);
  return Math.max(Math.min(max, needed), needed);
}

/* ── tiers ─────────────────────────────────────────────────────────────
 *
 *   A structural    what the workload IS
 *   B control       what decides whether you would notice
 *   C operational   how it is run
 *   D provenance    images, snapshots, versions, templates — evidence, not
 *                   architecture
 */
export const TIER_OF_DOMAIN: Record<string, "A" | "B" | "C" | "D"> = {
  compute: "A",
  storage: "A",
  database: "A",
  // A contact centre is not annotation on an architecture; it IS one.
  application: "A",
  "network.delivery": "A",
  "network.loadbalancing": "A",
  "network.connectivity": "A",
  "network.private-link": "A",
  "network.igw": "A",
  "network.nat": "A",
  "network.tgw": "A",
  "network.direct-connect": "A",
  "network.vpn": "A",
  "network.peering": "A",
  "network.interface": "A",
  security: "B",
  // Control-plane network: what decides whether a packet arrives.
  "network.firewall": "B",
  "network.security-group": "B",
  "network.nacl": "B",
  "network.routing": "B",
  "network.dns-zones": "B",
  "network.dns-resolver": "B",
  "network.dns-discovery": "B",
  governance: "C",
  management: "C",
  devops: "C",
  migration: "C",
  integration: "A",
  analytics: "A",
  ai: "A",
};

export const TIERS: { id: "A" | "B" | "C" | "D"; label: string }[] = [
  { id: "A", label: "structural" },
  { id: "B", label: "control" },
  { id: "C", label: "operational" },
  { id: "D", label: "provenance" },
];

/** A record is provenance whatever its domain; otherwise the domain decides. */
export function tierFor(kind: string, cat: string, sub: string): "A" | "B" | "C" | "D" {
  if (kind === "record") return "D";
  return TIER_OF_DOMAIN[`${cat}.${sub}`] ?? TIER_OF_DOMAIN[cat] ?? "C";
}

/* ── families ──────────────────────────────────────────────────────────
 *
 * A rail carries 331 identity resources with nothing saying they are all
 * management concerns, or that CodeBuild and CodeDeploy are devops ones. The
 * family word comes from the CATEGORY, and only for rules — a resident is named
 * for its product, not for the discipline that looks after it.
 *
 * Composed at render time rather than added to the taxonomy: `management` is
 * `kind=rule` plus a domain, and folding that into a category name would undo
 * the separation the whole model rests on. `compute.instances` is residents,
 * rules and records at once; no `management-compute` category could say that.
 */
export const FAMILY_OF: Record<string, string> = {
  security: "management",
  governance: "management",
  management: "management",
  network: "management",
  migration: "management",
  devtools: "devops",
};

/** The fuller name, for a tooltip or a panel heading. */
export const familyTitleFor = (cat: string, sub: string) => `${FAMILY_OF[cat] ?? cat} · ${sub}`;

/**
 * A role name must never reach the screen.
 *
 * Renaming `integration` to `resident.integration` for the kind axis put the
 * role string straight into the services band heading: the page read
 * `resident.api` where it had read "api". The engine's vocabulary is the
 * engine's business.
 */
export const laneNoun = (lane: string) => lane.slice(lane.indexOf(".") + 1);

/* ── codes on nodes, and the legend that expands them ─────────────────── */

export type Legend = {
  code: string;
  kind: string;
  label: string;
  targetKey: string;
  refs: string[];
};

type Edge = { source_key: string; target_key: string; edge_type: string };

/**
 * Codes per node, plus the legend.
 *
 * `isDrawn` is a parameter rather than a lookup because it is the entire
 * subtlety: a code exists so a reader can FIND it, a record lives in a detail
 * panel and never draws, so a code on one points at nothing. Most `protected-by`
 * edges come from a security group's own RULES, which are records — 371 of 494
 * tags landed there, and 27 of 80 governing resources ended up with a code that
 * appeared nowhere on the canvas.
 *
 * The relationship is not lost: a record's own panel still shows what governs
 * it, which is where a reader of a record is already looking.
 */
export function annotateEdges(edges: Edge[], isDrawn: (key: string) => boolean) {
  const counters: Record<string, number> = {};
  const codeOf: Record<string, string> = {};
  const byNode: Record<string, Record<string, string[]>> = {};
  const selfCode: Record<string, string> = {};
  const legend: Legend[] = [];

  for (const e of edges) {
    const spec = CODES[e.edge_type];
    if (!spec || !e.target_key) continue;
    if (!isDrawn(e.source_key)) continue;

    if (!(e.target_key in codeOf)) {
      counters[spec.code] = (counters[spec.code] ?? 0) + 1;
      const code = `${spec.code}-${counters[spec.code]}`;
      codeOf[e.target_key] = code;
      legend.push({ code, kind: spec.code, label: spec.label, targetKey: e.target_key, refs: [] });
      selfCode[e.target_key] = code;
    }
    const code = codeOf[e.target_key]!;
    legend.find((l) => l.code === code)?.refs.push(e.source_key);
    const bucket = (byNode[e.source_key] ??= {});
    const list = (bucket[spec.code] ??= []);
    // One code per governing resource, however many edges reported it. Three
    // interfaces in the same security group is one `sg-2`, not three.
    if (!list.includes(code)) list.push(code);
  }

  // Sort by kind then NUMBER: a string sort puts iam-10 before iam-2, which
  // defeats the point of a sequence.
  const rank = (c: string): [number, number] => {
    const [kind, n] = c.split("-");
    return [CODE_ORDER.indexOf(kind ?? ""), Number(n) || 0];
  };
  legend.sort((a, b) => {
    const [ka, na] = rank(a.code);
    const [kb, nb] = rank(b.code);
    return ka - kb || na - nb;
  });
  return { byNode, selfCode, legend };
}

/* ── clusters ──────────────────────────────────────────────────────────── */

/**
 * Split siblings into the fleets that own them, plus whatever is unowned.
 *
 * Biggest fleet first, then by name so the answer does not depend on the order
 * the scene happened to serialise in. The unowned run always sorts LAST — it is
 * the remainder, not a fleet.
 */
export function clusterRuns<T extends { position?: { cluster?: string | null | undefined } }>(
  nodes: T[],
) {
  const owned = new Map<string, T[]>();
  const free: T[] = [];
  for (const n of nodes) {
    const c = n.position?.cluster;
    if (c) owned.set(c, [...(owned.get(c) ?? []), n]);
    else free.push(n);
  }
  const runs: { cluster: string | null; members: T[] }[] = [...owned.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(([cluster, members]) => ({ cluster, members }));
  if (free.length) runs.push({ cluster: null, members: free });
  return runs;
}

/* ── group order ───────────────────────────────────────────────────────── */

/**
 * Nearest the internet first, then the big ones.
 *
 * Reading order IS the traffic path. A reader scanning a container top to
 * bottom should meet the front door before the things behind it, which is axiom
 * A1 applied one level down from the bands. Size only breaks ties — before
 * this, forty buckets outranked the load balancer in front of them purely by
 * being numerous.
 *
 * Off-path groups (policies, config) carry exposure 0 and sort LAST rather than
 * first, so a 0 does not read as "closer than L1".
 */
export const byExposureThenSize =
  <T>(exposureOf: (n: T) => number) =>
  (a: [string, T[]], b: [string, T[]]) => {
    const rank = (g: T[]) => exposureOf(g[0]!) || 9;
    return rank(a[1]) - rank(b[1]) || b[1].length - a[1].length || a[0].localeCompare(b[0]);
  };

/* ── one pass, one order ───────────────────────────────────────────────
 *
 * Everything drawn inside a container — a sub-container, a fleet, a rule wrap,
 * a plain group of one type — competes in a single ordering on rank, and rank
 * alone. Nothing wins position by being a particular KIND of thing.
 *
 * This was three fixed blocks and then two. Every version had the same defect
 * in a different place: a KMS box round a database jumped ahead of the
 * instances because wraps drew first, and the account's CloudFront — L1, the
 * front door of the estate — drew below its own region because containers drew
 * first. The engine had the order right every time; the view was drawing by
 * category of container instead of by position.
 *
 * Ties break on key so the answer does not depend on the order the scene
 * happened to serialise in.
 */
export const byRank = (a: { rank: number; key: string }, b: { rank: number; key: string }) =>
  a.rank - b.rank || a.key.localeCompare(b.key);

/* ── a tab on a border ─────────────────────────────────────────────────
 *
 * The shape is the same on all four edges and only the open side changes: a tab
 * has no border where it meets the container, and rounded corners on the two
 * outer ones. That is what makes it read as ATTACHED rather than floating —
 * the missing edge says "this is part of that box".
 *
 * North and south run along a horizontal border, so their tabs sit side by side
 * in a row. East and west run down a vertical one and stack. Same component,
 * because they are the same object on four different edges.
 */
export type BorderSide = "n" | "s" | "e" | "w";

export const tabShape = (side: BorderSide, radius = 6) => {
  const r = `${radius}px`;
  switch (side) {
    case "n":
      return { borderRadius: `${r} ${r} 0 0`, open: "border-b-0" as const };
    case "s":
      return { borderRadius: `0 0 ${r} ${r}`, open: "border-t-0" as const };
    case "w":
      return { borderRadius: `${r} 0 0 ${r}`, open: "border-r-0" as const };
    default:
      return { borderRadius: `0 ${r} ${r} 0`, open: "border-l-0" as const };
  }
};

/** Whether an edge runs across the page or down it. */
export const isHorizontal = (side: BorderSide) => side === "n" || side === "s";

/**
 * Which way a tab's label runs.
 *
 * A tab runs ALONG the border it is attached to. On a horizontal edge that is
 * already true and there is nothing to do. On a vertical one the label has to
 * turn, or the tab sticks out sideways from the line — which is a card pinned
 * near a box rather than a tab on it, and costs 132px of canvas per side
 * instead of 28.
 *
 * West reads bottom-to-top and east top-to-bottom. That is not arbitrary: it is
 * what every physical tabbed thing does, because the text faces out of the
 * fold. Reversing either one makes a reader tilt their head the wrong way.
 */
export const tabRun = (side: BorderSide): { writingMode?: "vertical-rl"; transform?: string } => {
  if (isHorizontal(side)) return {};
  return {
    writingMode: "vertical-rl",
    ...(side === "w" ? { transform: "rotate(180deg)" } : {}),
  };
};

/* ── rail slots ────────────────────────────────────────────────────────
 *
 * The engine says WHICH slot a supporting resource draws in; these decide how
 * the slots on one arm are ordered, and how a slot deep enough to need two
 * layers splits between them.
 */

/** Order along an arm: top to bottom on a wall, west to east on a line. */
export const ALONG_ORDER = { start: 0, middle: 1, end: 2 } as const;

export const alongRank = (along: string | undefined) =>
  ALONG_ORDER[(along ?? "middle") as keyof typeof ALONG_ORDER] ?? 1;

/**
 * Split an arm's tabs across its layers, keeping order.
 *
 * Contiguous chunks, not round-robin: the sequence down a wall is a reading
 * order, and dealing alternate tabs into two columns shuffles it. Chunks
 * preserve it — column one reads top to bottom, then column two continues.
 *
 * Balanced by count rather than by height, because every tab on an arm is the
 * same size: a rail tab states a domain and a number, and that is one line
 * whatever the domain. Height balancing would be the same answer with more
 * arithmetic.
 */
export function splitLayers<T>(items: T[], layers: number): T[][] {
  const n = Math.max(1, Math.min(layers, items.length || 1));
  if (n <= 1 || items.length <= 1) return [items];
  const per = Math.ceil(items.length / n);
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += per) out.push(items.slice(i, i + per));
  // A trailing empty column would draw a gap the arm does not need.
  return out.filter((c) => c.length > 0);
}
