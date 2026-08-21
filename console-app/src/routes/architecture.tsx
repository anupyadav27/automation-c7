import { createFileRoute } from "@tanstack/react-router";
import { byService, relatedTo, toTree, type RelatedNode } from "@/components/console/related";
import React, { useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { relativeTo, tracesFrom, type Rect, type Trace } from "@/components/console/trace";
import { Network, SlidersHorizontal } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useQuery } from "@tanstack/react-query";
import { assetQuery, relationsQuery } from "@/lib/api";
import { Badge, Chip, Mono, PageHeader } from "@/components/console/primitives";
import { IS_LIVE_SCENE, SCENE, money, type SceneNode } from "@/lib/mock-data";
import { Icon, IconSprite, colourFor } from "@/components/console/aws-icons";
import { SERVICE_LABEL } from "@/components/console/service-labels";
import { SERVICE_FAMILY } from "@/components/console/service-families";
import { AwsIconSprite } from "@/components/console/aws-icon-sprite";
import {
  CHIP_H,
  CHIP_W,
  RAIL_DEPTH,
  railClearance,
  GAP,
  PAD,
  RAIL_TAB_LEN,
  RAIL_LABEL_MAX,
  NAME_FLOOR,
  PANEL,
  PANEL_ROWS,
  PANEL_SCROLL_AT,
  MIN_VIEWPORT,
  placePanel,
  type Side,
  PANEL_GAP,
  VIEWPORT_PAD,
  VISIBLE,
  VISIBLE_TIGHT,
  chooseColumns,
  measureChip,
  measureContainer,
  measureGroup,
  type Size,
} from "@/components/console/layout-metrics";
import { allocate, columnBudget, packRows, splitLane } from "@/components/console/pack";
import { applyOrder, moveTo, zoneRowKey } from "@/components/console/order";
import {
  emptyCells,
  gridCols,
  gridRows,
  layoutGrid,
  SPARE_ROWS,
  moveToCell,
  seedCells,
  step,
  type Cell,
  type Cells,
} from "@/components/console/grid";
import { usePreferences, type PrefsApi } from "@/hooks/use-preferences";
import { scopeOf, type PanelPref, type Placement } from "@/lib/preferences";
import { fromPlacement, toPlacement } from "@/components/console/placement";
import {
  CODES,
  CODE_ARM,
  RAMP,
  TIERS,
  alongRank,
  layersNeeded,
  railLabel,
  annotateEdges,
  byRank,
  tabRun,
  tabShape,
  byExposureThenSize as byExposureThenSizeWith,
  clusterRuns,
  codeTone,
  containerStyle,
  familyTitleFor,
  grey,
  laneNoun,
  railToneFor,
  splitLayers,
  tierFor,
  type Legend,
} from "@/components/console/decide";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/architecture")({
  head: () => ({
    meta: [
      { title: "Architecture Map — Cloud Estate Console" },
      {
        name: "description",
        content:
          "Layered containment map of account, region, VPC, availability zones, subnets and workloads with security, encryption and exposure overlays.",
      },
      { property: "og:title", content: "Architecture Map — Cloud Estate Console" },
      {
        property: "og:description",
        content: "Nested account → region → VPC → AZ → subnet → workload architecture view.",
      },
    ],
  }),
  component: Architecture,
});

/* ── how the scene draws ───────────────────────────────────────────────
   Two axioms carry the whole layout, and everything below is an
   application of them:

     the VERTICAL axis is the traffic path   — above means upstream
     the HORIZONTAL axis is redundancy       — beside means peer or replica

   Placement itself is not decided here. Every node arrives carrying a
   band, lane, rank and anchor computed by the topology engine, so this
   file only has to honour them - and two renderers can never disagree
   about where a load balancer goes.                                      */

const CONTAINER_ROLES = new Set(["org", "account", "region", "network", "zone", "segment"]);

const LAYER_ID: Record<string, string> = {
  account: "L0",
  region: "L1",
  vpc: "L2",
  az: "L3",
  subnet: "L4",
  workload: "L5",
  attached: "L6",
  regional: "R1",
  global: "G0",
};

const CONTAINER_LABEL: Record<string, string> = {
  org: "Organization",
  account: "Account",
  region: "Region",
  network: "VPC",
  zone: "AZ",
  segment: "Subnet",
};

const colourOf = (type: string) => colourFor(type);

/* Edge type → short code. A security group becomes `sg-1`, and every resource
   it governs carries `sg-1` on its border. Lines turn into a hairball past a
   few dozen edges; codes stay legible at any density and survive filtering. */
const railTone = (n: SceneNode) => railToneFor(colourOf(n.type));

/* A door is a way in or out, so it takes the traffic hue — the same amber the
   west-arm codes and the south line use. Every door now sits on the north
   border: an internet gateway, a transit gateway, Direct Connect, a NAT and a
   VPC endpoint all answer the same question, which is how this network reaches
   what is not inside it, and answering it in four different places was the
   reason none of them read as a set. */
/* A door takes its own service colour like everything else — an internet
   gateway is network purple because AWS says so. */
const doorTone = (n: SceneNode) => railToneFor(colourOf(n.type));

/* The filter groups by the SAME categories the engine lays the diagram out
   with, so ticking `datastore` highlights exactly the lane labelled
   datastore. A filter whose vocabulary differs from the picture's makes the
   reader translate between two taxonomies for no benefit. */
const PLANE_OF: Record<string, [plane: string, label: string]> = {
  api: ["application", "api"],
  integration: ["application", "integration"],
  serverless: ["application", "serverless"],
  containers: ["application", "containers"],
  datastore: ["application", "datastore"],
  analytics: ["application", "analytics"],
  ai: ["application", "ai"],

  "flow.compute": ["workload", "compute"],
  "flow.data": ["workload", "data"],
  "flow.balancer": ["workload", "load balancer"],
  "flow.egress": ["workload", "nat"],
  "flow.ingress": ["workload", "ingress"],
  attachment: ["workload", "volumes & interfaces"],

  "boundary.internet": ["boundary", "internet gateway"],
  "boundary.lateral": ["boundary", "transit & peering"],
  "boundary.service": ["boundary", "service endpoint"],
  "boundary.onprem": ["boundary", "on-premises"],
  "flow.edge": ["boundary", "cdn & dns"],

  "plane.identity": ["platform", "identity"],
  "plane.platform": ["platform", "encryption & delivery"],
  "plane.governance": ["governance", "observe & audit"],
  "plane.network": ["network", "security groups & routes"],
  "plane.artifact": ["artifacts", "config & provenance"],
};

const PLANE_ORDER = [
  "boundary",
  "workload",
  "application",
  "network",
  "platform",
  "governance",
  "artifacts",
];

/* Configuration and provenance are not architecture. An image belongs in the
   detail of the instance it launched, not beside it as a peer - so artifacts
   are off the canvas unless asked for. They stay findable: the filter lists
   every one, and a resource's panel names the ones it is linked to. */
const ARTIFACTS_ON_CANVAS = false;

/* What a resource IS, for the sub-group heading inside a container.
   Keyed on the resource TYPE, not the service. Grouping on the service put a
   route table, a network ACL and a spot request all under "instances", because
   every one of them is an `ec2.*` - the same mistake the icons made before
   they were keyed per resource. Anything not named here falls back to the
   type's own noun, so a new service is grouped sensibly the day it appears
   rather than being lumped under its service name. */
const TYPE_LABEL: Record<string, string> = {
  // storage & data - the semantic name beats the product name
  "s3.bucket": "object storage",
  "efs.file_system": "file storage",
  "fsx.file_system": "file storage",
  "dynamodb.table": "key-value",
  "rds.db_instance": "relational",
  "docdb.db_instance": "document",
  "neptune.db_instance": "graph",
  "elasticache.cache_cluster": "in-memory cache",
  "memorydb.cluster": "in-memory cache",
  "redshift.cluster": "data warehouse",
  "opensearch.domain": "search",
  // compute
  "ec2.instance": "instances",
  "ec2.volume": "volumes",
  "ec2.network_interface": "network interfaces",
  "ec2.eip": "elastic ips",
  "ec2.ami": "machine images",
  "ec2.image": "machine images",
  "ec2.spot_instance_request": "spot requests",
  "lambda.function": "functions",
  "ecs.cluster": "container clusters",
  "eks.cluster": "kubernetes clusters",
  "ecr.repository": "image registries",
  "autoscaling.auto_scaling_group": "autoscaling groups",
  // network
  "ec2.route_table": "route tables",
  "ec2.network_acl": "network ACLs",
  "ec2.security_group": "security groups",
  "ec2.internet_gateway": "internet gateways",
  "ec2.nat_gateway": "nat gateways",
  "ec2.vpc_endpoint": "endpoints",
  "ec2.transit_gateway": "transit gateways",
  "ec2.flow_log": "flow logs",
  "ec2.prefix_list": "prefix lists",
  "ec2.vpc": "networks",
  "ec2.subnet": "subnets",
  "elbv2.load_balancer": "load balancers",
  "elb.load_balancer": "load balancers",
  // identity & crypto
  "iam.role": "roles",
  "iam.policy": "policies",
  "iam.user": "users",
  "iam.instance_profile": "instance profiles",
  "kms.key": "encryption keys",
  "secretsmanager.secret": "secrets",
  "acm.certificate": "certificates",
  // integration
  "sqs.queue": "queues",
  "sns.topic": "topics",
  "events.rule": "event rules",
  "stepfunctions.state_machine": "workflows",
};

/* Configuration and backups are NOT the thing they configure. A parameter
   group, an option group and a snapshot all carry an `rds.` prefix, so
   grouping them with the database read as "your database is outside the VPC"
   when the database was in fact inside a subnet. Suffix wins over everything. */
const TYPE_KIND: [RegExp, string][] = [
  [/snapshot/, "snapshots"],
  [/certificate/, "certificates"],
  [/(parameter|option)_group$/, "configuration"],
  [/subnet_group$/, "subnet groups"],
  [/security_group$/, "security groups"],
  [/_group$/, "configuration"],
  [/\.user$/, "users"],
  [/version$/, "versions"],
];

/** `ec2.route_table` -> "route tables". The type already says what it is. */
function nounOf(type: string) {
  const noun = (type.includes(".") ? type.slice(type.indexOf(".") + 1) : type).replace(/_/g, " ");
  if (/(s|sh|ch|x|z)$/.test(noun)) return `${noun}es`;
  return noun.endsWith("y") ? `${noun.slice(0, -1)}ies` : `${noun}s`;
}

const nounFor = (type: string) => {
  const exact = TYPE_LABEL[type];
  if (exact) return exact;
  for (const [re, label] of TYPE_KIND) if (re.test(type)) return label;
  return nounOf(type);
};

/**
 * What to call a group of these — and therefore what groups with what.
 *
 * A resident is named after the service that sells it: seven Lambda functions
 * are a box labelled "Lambda", because that is the word an architect says out
 * loud and the word AWS prints under the icon. Everything else is named after
 * what it does - "security groups", "roles", "route tables" - because AWS
 * sells no product called a security group; it is a feature, and naming its
 * group "EC2" would be less true, not more.
 *
 * The label IS the grouping key, which is the point. Two services that share a
 * name merge: `elb.load_balancer` and `elbv2.load_balancer` become one ELB
 * group rather than two boxes a reader has to know the difference between.
 *
 * Grouping by service was tried once before and rejected, because it put route
 * tables, network ACLs and spot requests all under "EC2". That objection is
 * dead now for two reasons: grouping happens INSIDE a subcategory, so a route
 * table (network.routing) and an instance (compute.instances) never meet; and
 * only residents take the service name at all.
 */
/** Which of the six kinds this is. Boundaries declare it now, so the renderer
    no longer invents a word for the hole where their class used to be null. */
const kindOf = (n: SceneNode) => (n.position as { kind?: string })?.kind ?? "";

const serviceOf = (type: string) => (type.includes(".") ? type.slice(0, type.indexOf(".")) : type);

const groupOf = (n: SceneNode) =>
  (kindOf(n) === "resident" && SERVICE_LABEL[serviceOf(n.type)]) || nounFor(n.type);

/**
 * Which product a service belongs to, when several are one thing.
 *
 * AWS ships Bedrock as five separate service ids and Chime as six. Each drew
 * as its own box in a band, so one product read as five unrelated services.
 * The family is derived from the ids themselves — the longest prefix that is
 * itself a service — so nothing is authored and a service split off next year
 * folds in the day it appears.
 *
 * Only for residents. A rule or a record is named for what it does, not for
 * the product that happens to expose it.
 *
 * Used for the label and the filter, NOT as a nesting level on the canvas. A
 * family box was built and reverted: it rendered in zero cases against the only
 * estate available to test it, and the rule had false positives - `service` and
 * `vpc` are catalog ids, so they absorbed service-quotas and VPC Lattice.
 */
const familyOf = (n: SceneNode) => {
  if (kindOf(n) !== "resident") return null;
  const svc = serviceOf(n.type);
  const family = SERVICE_FAMILY[svc];
  return family ? (SERVICE_LABEL[family] ?? family) : null;
};

/**
 * What each node is linked to, both directions.
 *
 * Provenance runs the way the API reports it - an instance references its
 * launch template, an image is created-from a snapshot - so a panel that only
 * followed one direction would answer half the question.
 */
function relatedIndex() {
  const out: Record<string, { key: string; how: string }[]> = {};
  for (const e of SCENE.edges ?? []) {
    (out[e.source_key] ??= []).push({ key: e.target_key, how: e.edge_type });
    (out[e.target_key] ??= []).push({ key: e.source_key, how: e.edge_type });
  }
  return out;
}

/** Every node by key, so a related edge can be resolved to a real resource. */
function nodeIndex() {
  const out: Record<string, SceneNode> = {};
  const walk = (n: SceneNode) => {
    out[n.key] = n;
    (n.children ?? []).forEach(walk);
  };
  walk(SCENE.tree);
  for (const bucket of Object.values(SCENE.overlays ?? {})) {
    for (const n of bucket) out[n.key] ??= n;
  }
  return out;
}

/**
 * Which container each node draws inside.
 *
 * The tree knows, but a node does not carry its parent, and "where is this"
 * is the first question anyone asks of a row in a list that has been lifted
 * out of the diagram it came from.
 */
function parentIndex() {
  const out: Record<string, SceneNode> = {};
  const walk = (n: SceneNode) => {
    for (const c of n.children ?? []) {
      out[c.key] = n;
      walk(c);
    }
  };
  walk(SCENE.tree);
  return out;
}

/** Codes per node, plus the legend that expands them. */
/**
 * What a code means, in one sentence, for the chip that carries it.
 *
 * The codes used to be explained by a standing legend — 43 rows in the left
 * column, permanently on screen so that a reader could decode `sg-2` on a chip
 * somewhere else. That is a lookup table asking the reader to hold a mapping in
 * their head while their eyes are on the diagram.
 *
 * The same fact fits in the tag's own tooltip: what it points at, how many it
 * governs, and which border it rides. The legend's whole content, delivered
 * where the question is asked rather than in a column that is always there.
 */
function codeTitle(code: string, legend: Legend[]): string {
  const entry = legend.find((l) => l.code === code);
  const arm = CODE_ARM[code.split("-")[0] ?? ""]?.arm;
  if (!entry) return arm ? `${code} — on the ${arm} border` : code;
  const target = entry.targetKey.split(":").slice(1).join(":") || entry.targetKey;
  return [
    `${code} — ${entry.label}`,
    target,
    `governs ${entry.refs.length}`,
    arm ? `on the ${arm} border` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function annotate() {
  return annotateEdges(SCENE.edges ?? [], (key) => {
    const source = NODES[key];
    return !!source && isDrawn(source);
  });
}

/**
 * What to call a resource on the canvas.
 *
 * The shortest string that identifies it to a human, and ONE line of it. Of
 * 652 nodes in a real estate, 492 have no name distinct from their id, so
 * printing name-then-id repeated the same string twice on three chips in four;
 * another 33 carried a bare ARN, which is 90 characters of prefix and about
 * eight of information.
 *
 * The group above the chip already says what kind of thing this is and shows
 * its icon, so the chip does not repeat the type either. Everything omitted
 * here - full id, ARN, placement, codes - is one click away in the panel.
 */
function displayName(n: SceneNode): string {
  const named = n.name && n.name !== n.id && !n.name.startsWith("arn:");
  return tail(named ? n.name : n.id || n.name || "");
}

/** Last meaningful segment of an ARN or path; anything else unchanged. */
function tail(value: string): string {
  if (!value.startsWith("arn:") && !value.startsWith("/")) return value;
  const parts = value.split(/[/:]/).filter(Boolean);
  // Trailing hash-like segments carry no meaning; prefer the name before one.
  const last = parts[parts.length - 1] ?? value;
  if (parts.length > 1 && /^[0-9a-f]{8,}$/i.test(last)) return parts[parts.length - 2]!;
  return last;
}

const service = (t: string) => (t.includes(".") ? t.split(".")[0]! : t);
const anchorOf = (n: SceneNode) => n.position?.anchor ?? "in";
const roleOf = (n: SceneNode) => n.position?.role ?? "";
/** `rail.e` -> "e". Which border a binding rides. */
/** `category.subcategory` — what kind of service, independent of placement. */
const catOf = (n: SceneNode) => (n.position as { category?: string })?.category ?? "unclassified";
const subOf = (n: SceneNode) =>
  (n.position as { subcategory?: string })?.subcategory ?? nounFor(n.type);

/**
 * How far this sits from the internet, and what to call that.
 *
 * The engine declares it per role, so it is the same ladder on every cloud and
 * the renderer only has to name the rungs. L1 is public by definition, L4
 * cannot be reached from outside at all, and L3 is the interesting one: a
 * bucket, an instance or a function is reachable from the internet only if
 * something else grants it - a public address, a balancer in front, a resource
 * policy. That "only if" is where nearly every exposure finding comes from,
 * which is why it gets a rung of its own rather than being split between
 * public and private.
 *
 * Nothing off the traffic path carries a level. A security group is not nearer
 * or further from the internet; it applies.
 */
/** Whether the engine says this draws on the canvas at all. */
/* Which borders order their doors centre-out. From the model via the scene,
   not decided here: `edge_order.centre_out` was declared and never read, so the
   model said one thing and this file decided another. They agreed, but only by
   coincidence, and a coincidence is not a contract. */
const CENTRE_OUT: string[] = (SCENE.meta as { centre_out?: string[] })?.centre_out ?? ["s"];

const isDrawn = (n: SceneNode) => (n.position as { drawn?: boolean })?.drawn !== false;

const exposureOf = (n: SceneNode) => (n.position as { exposure?: number })?.exposure ?? 0;

/**
 * The placement classes, in words a reader has not had to learn.
 *
 * `resident` / `binding` / `component` are the engine's vocabulary and they
 * earn their keep in the model, where precision matters more than familiarity.
 * On screen they are jargon, and the honest translation of "resident" is no
 * label at all: being unlabelled IS the statement that this is the
 * architecture, and everything else is annotation on it.
 */
const KIND_WORD: Record<string, string> = {
  boundary: "",
  resident: "",
  part: "part of",
  rule: "applies to",
  door: "way in / out",
  record: "config",
};

/**
 * What a reviewer looks at first — and it must never move a box.
 *
 * Criticality and placement are different questions, and the reason to keep
 * them apart is that placement has to be reproducible. Position comes from
 * scope and exposure alone; if a tier could move a resource, changing what a
 * reader cares about would change the diagram, and two people would be looking
 * at different pictures of the same estate.
 *
 * So a tier dims and filters. It never relocates.
 *
 *   A structural   boundaries, balancers, compute, storage, databases
 *                  — if these are wrong, nothing else matters
 *   B control      identity, firewall, routing, encryption
 *                  — decides who reaches tier A
 *   C operational  observability, provisioning, config rules
 *                  — decides whether you would notice
 *   D provenance   images, snapshots, versions, templates
 *                  — evidence, not architecture
 */
const tierOf = (n: SceneNode) => tierFor(kindOf(n), catOf(n), subOf(n));

const EXPOSURE: Record<number, { name: string; why: string }> = {
  1: { name: "internet", why: "public by definition — no network to hide behind" },
  2: { name: "entry", why: "terminates inbound traffic at the boundary" },
  3: { name: "conditional", why: "reachable from outside only if something grants it" },
  4: { name: "internal", why: "no path from the internet exists" },
};

/**
 * Group order: nearest the internet first, then the big ones.
 *
 * Reading order IS the traffic path. A reader scanning a container top to
 * bottom should meet the front door before the things behind it, which is
 * axiom A1 applied one level down from the bands. Size only breaks ties -
 * before this, forty buckets outranked the load balancer in front of them
 * purely by being numerous.
 */
const byExposureThenSize = byExposureThenSizeWith<SceneNode>(exposureOf);

/**
 * What to call a rail's contents, above the services on it.
 *
 * A rail carries 331 identity resources with nothing saying they are all
 * management concerns, or that CodeBuild and CodeDeploy are devops ones. The
 * family word comes from the CATEGORY, and only for rules — a resident is
 * named for its product, not for the discipline that looks after it.
 *
 * Composed at render time rather than added to the taxonomy: `management` is
 * `kind=rule` plus a domain, and folding that into a category name would undo
 * the separation the whole model rests on. `compute.instances` is residents,
 * rules and records at once; no `management-compute` category could say that.
 */
/**
 * What a rail group is called: the subcategory, alone.
 *
 * `security.identity` reads as "identity", `security.encryption` as
 * "encryption". Not "management · encryption" — the rail already IS the
 * management surface, so the word is on every chip and distinguishes none of
 * them. And not "KMS": a rail says what applies here, and the service that
 * implements it is one click away. Grouping by brand meant four chips reading
 * KMS / Secrets Manager / ACM where one reading "encryption" says the same
 * thing and leaves room for the count.
 *
 * The family is still used for the tooltip and the filter, where there IS room
 * and where the discipline is what a reader is scanning for.
 */
function familyLabel(n: SceneNode) {
  return subOf(n);
}

/** The fuller name, for a tooltip or a panel heading. */
const familyTitle = (n: SceneNode) => familyTitleFor(catOf(n), subOf(n));

const railSide = (n: SceneNode) => (n.position?.anchor ?? "").split(".")[1] ?? "e";

/* Slot, position along the arm, and depth — all decided by the engine from the
   node's DOMAIN, so the view never has to know which service it came from. */
const slotOf = (n: SceneNode) => (n.position as { slot?: string })?.slot ?? "w-middle";
const alongOf = (n: SceneNode) => (n.position as { slot_along?: string })?.slot_along;
const layersOf = (n: SceneNode) => (n.position as { slot_layers?: number })?.slot_layers ?? 1;

/** How deep an arm actually runs, which is what its container must reserve. */
const layersOn = (nodes: SceneNode[], height: number) => {
  if (!nodes.length) return 0;
  const domains = new Set(nodes.map((n) => `${catOf(n)}.${subOf(n)}`)).size;
  const allowed = Math.max(...nodes.map((n) => layersOf(n)), 1);
  return layersNeeded(domains, height, Math.min(allowed, domains));
};

/** Several domains may share a tab — see `rollup` in the model. */
const rollupOf = (n: SceneNode) => (n.position as { rollup?: string })?.rollup;

/**
 * What a hover can point AT — the `data-members` a drawn thing stands for.
 *
 * A trace is drawn between two rectangles on the page, so a resource that no
 * element claims cannot be lit and cannot be pointed at. Only service tiles
 * and loose chips claimed any, which meant every relation to something on a
 * RAIL — a security group, a KMS key, an IAM role, an ACL, a route table —
 * had nothing to draw to. Those are the governance edges, which is to say
 * most of what anyone hovers a resource to find out.
 *
 * Space-separated for the `[data-members~="key"]` selector, and keys
 * containing a space are dropped because that selector cannot express them.
 */
const memberAttr = (nodes: SceneNode[]) =>
  nodes
    .map((m) => m.key)
    .filter((k) => !k.includes(" "))
    .join(" ");

/**
 * One tab per domain, biggest first, ties broken by name so it is stable.
 *
 * A domain with a rollup groups under that instead: a flow log, an alarm and an
 * X-Ray trace are three things to query and one thing to look at, so the border
 * shows `observability` once rather than three tabs saying the same word. The
 * split survives the click — the panel lists them by their real domain.
 */
function groupByDomain(nodes: SceneNode[]) {
  const by = new Map<string, SceneNode[]>();
  for (const n of nodes) {
    const d = rollupOf(n) ? `${catOf(n)}.${rollupOf(n)}` : `${catOf(n)}.${subOf(n)}`;
    by.set(d, [...(by.get(d) ?? []), n]);
  }
  return [...by.entries()]
    .map(([domain, members]) => ({ domain, members }))
    .sort((a, b) => b.members.length - a.members.length || a.domain.localeCompare(b.domain));
}
const hoistOf = (n: SceneNode) => (n.position as { hoist_to?: string })?.hoist_to;
const edgeRankOf = (n: SceneNode) => (n.position as { edge_rank?: number })?.edge_rank ?? 50;
/** Which END of a border a door takes. `centre` is what every strip did before. */
const edgeAlignOf = (n: SceneNode) =>
  (n.position as { edge_align?: string })?.edge_align ?? "centre";

/** Bindings anywhere below `node` whose scope container IS this node. */
function hoistedInto(node: SceneNode, into: SceneNode[] = [], root = node.key): SceneNode[] {
  for (const c of node.children ?? []) {
    if (hoistOf(c) === root) into.push(c);
    hoistedInto(c, into, root);
  }
  return into;
}
const isContainer = (n: SceneNode) => CONTAINER_ROLES.has(roleOf(n));

/** Nodes occupying more than one zone — lifted out and drawn across them. */
function spannersIn(node: SceneNode, into: SceneNode[] = []): SceneNode[] {
  if ((node.position?.span?.length ?? 0) > 1) into.push(node);
  for (const c of node.children ?? []) spannersIn(c, into);
  return into;
}

/** The same subtree with `drop` removed, so a lifted node never draws twice. */
function without(node: SceneNode, drop: Set<string>): SceneNode {
  return {
    ...node,
    children: (node.children ?? []).filter((c) => !drop.has(c.key)).map((c) => without(c, drop)),
  };
}

/**
 * Nothing is hidden on load.
 *
 * This began as four switches — Network controls, Encryption, Identity,
 * Internet Exposure — sitting above a filter panel that answered the same
 * question in a different vocabulary. Two controls, one job, and they
 * interacted: a category ticked in the panel still would not draw if its
 * switch was off, which is how an identity rail came to read `2` over 146
 * resources with nothing on screen explaining why.
 *
 * The switches also decided, silently, that 384 of 1,033 resources were not
 * worth drawing until asked for. A default that hides a third of the estate is
 * a default that makes the map wrong for anyone who does not know to go
 * looking — and no count on screen could have told them, because there was
 * none. The map now opens as the whole estate and the filter only ever
 * subtracts, which is the one behaviour a filter can have that never misleads.
 */
const QUIET_BY_DEFAULT: string[] = [];

/** An overlay is a visibility TOGGLE over nodes already placed in the tree. */

/**
 * Save, and say what is being saved.
 *
 * Three states, and the reason all three are on screen rather than one:
 *
 * - **unsaved** — something has been changed and would be lost on reload. A
 *   reader who rearranges a diagram and closes the tab should not discover the
 *   loss next week; the button is the promise, and its absence is the truth.
 * - **customised** — a preference is in force. This is the one that matters
 *   most and is easiest to leave out: without it, a reader carrying a saved
 *   order from six months ago sees a diagram that disagrees with the engine and
 *   has no way to find out why. Reset is beside it for exactly that reason.
 * - **dropped** — pins the estate no longer supports. Said once, plainly,
 *   rather than leaving a reader to wonder where a panel went.
 *
 * Nothing renders at all on a fixture scene: a layout saved against invented
 * data would restore against real data the moment a scan lands.
 */
function PreferenceBar({ prefs }: { prefs: PrefsApi }) {
  if (!IS_LIVE_SCENE || !prefs.loaded) return null;
  const quiet = !prefs.customised && !prefs.dirty && !prefs.dropped;
  if (quiet) return null;
  const moved = Object.keys(prefs.prefs.places).length;

  return (
    <span className="flex items-center gap-2 text-xs">
      {prefs.customised && (
        <span className="flex items-center gap-1.5 rounded-md border border-primary/40 px-2 py-1">
          <span className="text-muted-foreground">layout customised</span>
          {/* Two resets, because they undo two different kinds of regret.
              Arranging six panels into a mess should not cost a reader the
              diagram order they spent longer on — so the narrower one is
              offered first, and only when there is something for it to do. */}
          {moved > 0 && (
            <button
              onClick={() => prefs.update((p) => ({ ...p, places: {} }))}
              title={`return ${moved} moved ${moved === 1 ? "panel" : "panels"} to where they open`}
              className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              reset positions
            </button>
          )}
          <button
            onClick={prefs.reset}
            title="restore the engine's own order and clear every pin and position"
            className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            reset all
          </button>
        </span>
      )}
      {prefs.dropped > 0 && (
        <span className="text-muted-foreground">
          <span className="mono tabular-nums">{prefs.dropped}</span> pinned{" "}
          {prefs.dropped === 1 ? "item" : "items"} no longer in this estate
        </span>
      )}
      {prefs.dirty && (
        <button
          onClick={prefs.save}
          className="rounded-md border border-primary bg-primary/10 px-2 py-1 font-medium
                     text-primary hover:bg-primary/20"
        >
          save preferences
        </button>
      )}
      {prefs.failed && (
        <span className="text-sev-high">could not save — browser storage is unavailable</span>
      )}
    </span>
  );
}

/**
 * How many connection sources may be pinned at once by the bulk control.
 *
 * A ceiling on WHAT IS DRAWN, not on what exists. The live estate reaches
 * around a thousand chips, and a line from every one of them is not a diagram —
 * it is a screen of ink with a diagram somewhere underneath. The number is a
 * starting point rather than a measured one, and it is stated on the control
 * because a cap a reader cannot see is indistinguishable from a bug.
 */
const TRACE_CAP = 40;

/**
 * The bulk controls — three toggles rather than one "show everything" button.
 *
 * A single global switch was the original request and is the wrong shape at
 * this size. "Every panel pinned, every list expanded, every connection drawn"
 * on a 513-node estate produces more cards than the screen holds, each covering
 * diagram, and a hairball with no readable path through it. The reader pressed
 * a button asking to see MORE and the thing they were reading disappeared.
 *
 * Three independent toggles keep the same reach and stay honest: each is
 * separately useful, each is capped, and every cap says what it dropped.
 */
function ViewToggles({ ctx, containers }: { ctx: Ctx; containers: SceneNode[] }) {
  const lists = ctx.pinned.filter((p) => p.kind === "list").length;
  const canPin = Math.max(0, PIN_CAP - ctx.pinned.length);
  const traceOn = ctx.pinnedTraces.length > 0;

  /* Sources ranked by how much they actually connect, so a cap of 40 spends
     itself on the resources that explain the estate rather than on the first
     forty in tree order. */
  const pinTraces = () => {
    const ranked = Object.keys(NODES)
      .map((k) => ({ key: k, n: connectionsOf(k).length }))
      .filter((x) => x.n > 0)
      .sort((a, b) => b.n - a.n || a.key.localeCompare(b.key))
      .slice(0, TRACE_CAP)
      .map((x) => x.key);
    ctx.setPinnedTraces(ranked);
  };

  const pinLists = () => {
    for (const c of containers.slice(0, canPin)) {
      const members = descendantsOf(c);
      if (!members.length) continue;
      ctx.togglePin({
        kind: "list",
        subject: `box:${c.key}`,
        label: `${CONTAINER_LABEL[roleOf(c)] ?? c.layer_name ?? "Group"} · ${displayName(c)}`,
        members: members.map((n) => n.key),
      });
    }
  };

  return (
    <span className="flex items-center gap-1.5 text-xs">
      <button
        onClick={() => (traceOn ? ctx.setPinnedTraces([]) : pinTraces())}
        title={
          traceOn
            ? "clear every pinned connection line"
            : `draw connection lines for the ${TRACE_CAP} most-connected resources`
        }
        className="rounded-md border border-border px-2 py-1 text-muted-foreground
                   hover:bg-row-hover hover:text-foreground"
      >
        {traceOn ? `connections · clear (${ctx.pinnedTraces.length})` : "show connections"}
      </button>
      <button
        onClick={pinLists}
        disabled={canPin === 0}
        title={
          canPin === 0
            ? `${PIN_CAP} panels are already pinned — unpin one first`
            : `pin a list for each of the top ${Math.min(containers.length, canPin)} containers`
        }
        className="rounded-md border border-border px-2 py-1 text-muted-foreground
                   hover:bg-row-hover hover:text-foreground disabled:opacity-40"
      >
        pin container lists
      </button>
      {ctx.pinned.length > 0 && (
        <button
          onClick={() => ctx.pinned.forEach((p) => ctx.togglePin(p))}
          title="unpin every panel"
          className="rounded-md border border-border px-2 py-1 text-muted-foreground
                     hover:bg-row-hover hover:text-foreground"
        >
          unpin all ({ctx.pinned.length})
        </button>
      )}
      {/* Every cap, stated. `LIST_CAP` already prints "showing 250 of 1,030"
          rather than stopping quietly, and the same rule applies here: a
          reader must never be able to mistake a ceiling for a total. */}
      {ctx.pinnedTraces.length >= TRACE_CAP && (
        <span className="text-muted-foreground">
          capped at <span className="mono tabular-nums">{TRACE_CAP}</span> sources
        </span>
      )}
      {lists > 0 && canPin === 0 && (
        <span className="text-muted-foreground">
          <span className="mono tabular-nums">{PIN_CAP}</span> panel limit reached
        </span>
      )}
    </span>
  );
}

function Architecture() {
  const [selected, setSelected] = useState<SceneNode | null>(null);
  const [inline, setInline] = useState<Ctx["inline"]>(null);
  const [preview, setPreview] = useState<Ctx["preview"]>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [arranging, setArranging] = useState(false);
  /* Every node key the scene holds, so a stored pin naming a resource the
     estate has since replaced is dropped on load rather than restored onto
     nothing. Autoscaled instances and interfaces are the ones this catches. */
  const alive = useMemo(() => new Set(Object.keys(NODES)), []);
  const prefs = usePreferences(scopeOf(SCENE.account, SCENE.region), IS_LIVE_SCENE, alive);

  /* The filter and the artifact switch live in the preference document rather
     than in state of their own, and they are the RIGHT first consumer: they are
     the two things a reader sets on every visit and loses on every reload, and
     if the substrate cannot carry a set of category keys it has no business
     carrying a layout. Everything else stores into the same document. */
  const hidden = useMemo(() => new Set(prefs.prefs.filter.hidden), [prefs.prefs.filter.hidden]);
  const showArtifacts = prefs.prefs.toggles.showArtifacts;
  /* Kept as a `setHidden`-shaped callback so the four call sites below read
     exactly as they did — the change is where the value lives, not how the
     filter behaves. Sorted on the way in, so an unchanged set never encodes two
     ways and lights the unsaved indicator for nothing. */
  const setHidden = useCallback(
    (next: Set<string> | ((h: Set<string>) => Set<string>)) =>
      prefs.update((p) => {
        const cur = new Set(p.filter.hidden);
        const out = typeof next === "function" ? next(cur) : next;
        return { ...p, filter: { hidden: [...out].sort() } };
      }),
    [prefs],
  );

  const ann = useMemo(annotate, []);
  const counts = SCENE.counts ?? {};

  // The account holds the region alongside everything with no region at all -
  // identity, DNS, CDN. Those are account-wide, so they sit BESIDE the region
  // rather than above it: neither is a step on the way into the other.
  const account = SCENE.tree;
  const regions = (account.children ?? []).filter((c) => c.layer_name === "region");
  const supporting = [
    ...(SCENE.overlays?.["identity"] ?? []),
    ...(SCENE.overlays?.["encryption"] ?? []),
  ];
  // Supporting is drawn from the overlay buckets, and those nodes are also in
  // the tree - so a global IAM role would otherwise appear in both boxes.
  const supportingKeys = new Set(supporting.map((n) => n.key));
  const globals = (account.children ?? []).filter(
    (c) => c.layer_name === "global" && !supportingKeys.has(c.key),
  );

  const groups = useMemo(() => {
    // Grouped by TAXONOMY, not by placement. These are two independent facts
    // and they were one field for a while: a security group is a binding on
    // the network's rail AND a network.firewall service, and using placement
    // to group meant the filter could only ever be as granular as the layout
    // happened to be - which collapsed 354 resources into three rows.
    const tally: Record<string, Record<string, number>> = {};
    const count = (n: SceneNode) => {
      if (!(n.position as { category?: string })?.category) return;
      const c = catOf(n),
        sub = subOf(n);
      (tally[c] ??= {})[sub] = ((tally[c] ?? {})[sub] ?? 0) + 1;
    };
    const walk = (n: SceneNode) => {
      count(n);
      (n.children ?? []).forEach(walk);
    };
    walk(account);
    for (const bucket of Object.values(SCENE.overlays ?? {})) bucket.forEach(count);

    return Object.entries(tally)
      .map(([plane, subs]) => ({
        plane,
        roles: Object.entries(subs)
          .map(([sub, count]) => ({ role: `${plane}.${sub}`, label: sub, count }))
          .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)),
        total: Object.values(subs).reduce((t, c) => t + c, 0),
      }))
      .sort((a, b) => b.total - a.total || a.plane.localeCompare(b.plane));
  }, [account]);

  const ctx: Ctx = {
    hidden,
    ann,
    showArtifacts,
    inline,
    // Re-opening the same list closes it, so a tab is its own toggle.
    openInline: (v) => {
      setHovered(null);
      if (!v) clearRoom();
      // One floating rung at a time. A chip's preview and a tab's list are the
      // same rung of the same ladder, so two of them on screen at once is two
      // answers to one question.
      setPreview(null);
      setInline((cur) => (v && cur?.key === v.key ? null : v));
    },
    preview,
    openPreview: (v) => {
      setHovered(null);
      if (!v) clearRoom();
      setInline(null);
      setPreview((cur) => (v && cur?.node.key === v.node.key ? null : v));
    },
    onHover: setHovered,
    selectedKey: selected?.key ?? null,
    /* The sheet is the rung ABOVE the list and its preview, not beside them.
       Both are portalled at z-40 and the sheet's scrim is z-50, so a list left
       open painted at full brightness over a dimmed page — a panel floating on
       a modal backdrop, which is a z-order accident rather than a design. The
       sheet carries its own breadcrumb, Contained and Connections, so it does
       not need the list behind it to be navigable. */
    onSelect: (n) => {
      setPreview(null);
      setInline(null);
      setSelected(n);
    },
    order: prefs.prefs.order,
    cells: prefs.prefs.cells,
    setCells: (container, cells) =>
      prefs.update((p) => ({ ...p, cells: { ...p.cells, [container]: cells } })),
    arranging,
    reorder: (container, sequence) =>
      prefs.update((p) => ({ ...p, order: { ...p.order, [container]: sequence } })),
    pinnedTraces: prefs.prefs.traces,
    togglePinnedTrace: (key) =>
      prefs.update((p) => ({
        ...p,
        traces: p.traces.includes(key) ? p.traces.filter((k) => k !== key) : [...p.traces, key],
      })),
    setPinnedTraces: (keys) => prefs.update((p) => ({ ...p, traces: keys })),
    places: prefs.prefs.places,
    place: (subject, at, panel) =>
      prefs.update((p) => ({
        ...p,
        places: { ...p.places, [subject]: toPlacement(at, panel, viewport()) },
      })),
    resetPlaces: () => prefs.update((p) => ({ ...p, places: {} })),
    pinned: prefs.prefs.panels,
    isPinned: (id) => prefs.prefs.panels.some((p) => panelId(p) === id),
    togglePin: (panel) =>
      prefs.update((p) => {
        const id = panelId(panel);
        const without = p.panels.filter((x) => panelId(x) !== id);
        if (without.length !== p.panels.length) return { ...p, panels: without };
        /* The cap is a refusal, not a silent drop. Pinning a seventh panel and
           having the first quietly vanish is the behaviour that makes a reader
           distrust the whole feature — they arranged six and got five. */
        if (p.panels.length >= PIN_CAP) return p;
        return { ...p, panels: [...p.panels, panel] };
      }),
  };

  const totals = useMemo(() => {
    let n = 0;
    const walk = (x: SceneNode) => {
      n += 1;
      (x.children ?? []).forEach(walk);
    };
    walk(account);
    return n;
  }, [account]);

  /* What the filter is currently letting through, counted the same way the
     canvas decides it. Stated in the bar because a filter with no readout is a
     filter you have to re-open to understand — the old panel needed a column
     of forty checkboxes to say what one number says here. */
  const shownCount = useMemo(() => {
    let n = 0;
    const walk = (x: SceneNode) => {
      if (!isContainer(x) && hidden.has(`${catOf(x)}.${subOf(x)}`)) return;
      n += 1;
      (x.children ?? []).forEach(walk);
    };
    walk(account);
    return n;
  }, [account, hidden]);

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col p-6">
      <AwsIconSprite />
      <IconSprite />
      <PageHeader
        icon={Network}
        title="Architecture Map"
        subtitle="Layered containment view produced by the build-architecture stage."
        meta={
          <>
            <Chip>
              <Mono>{SCENE.account}</Mono>
            </Chip>
            <Chip>
              <Mono>{SCENE.region}</Mono>
            </Chip>
            <Chip>{totals} nodes</Chip>
            {counts["vpc"] ? (
              <Chip>
                {counts["vpc"]} vpc · {counts["az"]} az · {counts["subnet"]} subnet
              </Chip>
            ) : null}
            {!IS_LIVE_SCENE ? <Chip>fixture — run the scene stage for live data</Chip> : null}
          </>
        }
      />

      {/* One bar, above the canvas rather than beside it. */}
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <FilterBar
          groups={groups}
          hidden={hidden}
          shown={shownCount}
          total={totals}
          onToggle={(role) =>
            setHidden((h) => {
              const next = new Set(h);
              if (next.has(role)) next.delete(role);
              else next.add(role);
              return next;
            })
          }
          onToggleGroup={(roles, on) =>
            setHidden((h) => {
              const next = new Set(h);
              for (const r of roles) {
                if (on) next.delete(r);
                else next.add(r);
              }
              return next;
            })
          }
          onSetAll={(all) =>
            setHidden(all ? new Set() : new Set(groups.flatMap((g) => g.roles.map((r) => r.role))))
          }
        />
        <span className="text-xs text-muted-foreground">
          <span className="mono tabular-nums text-foreground">{shownCount.toLocaleString()}</span>
          {" of "}
          <span className="mono tabular-nums">{totals.toLocaleString()}</span> resources shown
        </span>
        {/* Back to how the map opens, not to everything-on — `all` inside the
            dropdown already does that, and a reader who has hidden three
            categories wants the view they started from, not 300 more
            bindings than they have ever seen. */}
        {!sameAsDefault(hidden) && (
          <button
            onClick={() => setHidden(new Set(QUIET_BY_DEFAULT))}
            className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground
                       hover:bg-row-hover hover:text-foreground"
          >
            reset filter
          </button>
        )}
        {/* The invitation. Everything below it existed before this button did,
            and none of it could be found: the controls were hover-only, 15px,
            and painted under the rails. A mode says the diagram is arrangeable
            before the reader has to guess it. */}
        <button
          onClick={() => setArranging((a) => !a)}
          aria-pressed={arranging}
          title={
            arranging
              ? "stop arranging"
              : "show the reorder handles on every movable box, lane and rail tab"
          }
          className={cn(
            "rounded-md border px-2 py-1 text-xs",
            arranging
              ? "border-primary bg-primary/10 font-medium text-primary"
              : "border-border text-muted-foreground hover:bg-row-hover hover:text-foreground",
          )}
        >
          {arranging ? "done arranging" : "arrange"}
        </button>
        {arranging && (
          <span className="text-xs text-muted-foreground">
            drag <span className="mono">⠿</span> or press <span className="mono">alt</span>+
            <span className="mono">←</span>/<span className="mono">→</span> — boxes, lanes, rails
            and supporting groups
          </span>
        )}
        <ViewToggles ctx={ctx} containers={(account.children ?? []).filter(isContainer)} />
        <PreferenceBar prefs={prefs} />
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        {/* The detail view floats OVER the canvas rather than taking a column
            of its own. A fourth column costs the diagram width permanently to
            show something that is only relevant while a node is selected. */}
        <div data-canvas className="relative min-h-0 flex-1 overflow-auto">
          {/* The account IS a container - drawing it as one is what puts its
              identity bindings on its own west rail and its CDN and DNS in its
              edge band. They used to be lifted into two side boxes, which left
              308 bindings carrying a correct border assignment that nothing
              drew, and KMS appearing twice: once in a box, once on the rail it
              already named. */}
          <HoverLight hovered={hovered} pinned={ctx.pinnedTraces} />
          <HoverTraces
            hovered={hovered}
            pinned={ctx.pinnedTraces}
            onUnpin={ctx.togglePinnedTrace}
          />
          {/* The diagram, wrapped only so a panel can borrow a gutter beside
              it — see `makeRoom`. No width of its own: it is a plain block
              filling the canvas, exactly as the diagram was before the wrapper
              existed. `min-w-max` here laid the estate out at its natural
              width instead — the account box went from 1,308px to 3,188px and
              the canvas gained a permanent 1,880px scrollbar, which is the
              whole single-view advantage spent on a gutter that is needed for
              a few seconds at a time. */}
          <div data-canvas-inner>
            <SceneBox node={account} ctx={ctx} />
          </div>

          {preview && (
            <NodePreview
              node={preview.node}
              at={preview.at}
              ctx={ctx}
              onClose={() => setPreview(null)}
              onOpen={(n) => {
                setPreview(null);
                setSelected(n);
              }}
            />
          )}

          {/* Pinned panels outlive selection, filtering and scroll — that is
              what pinning means. Rendered after the transient rung so a panel
              a reader just opened paints over the ones they parked. */}
          <PinnedPanels ctx={ctx} />

          {selected && <NodeSheet node={selected} onClose={() => setSelected(null)} />}
        </div>
      </div>
    </div>
  );
}

type Ctx = {
  showArtifacts: boolean;
  /** The level-one list, and which container is drawing it. */
  inline: {
    host: string;
    key: string;
    label: string;
    members: SceneNode[];
    /** The resource the list belongs TO, when there is one.
     *
     * A rail tab lists a category and owns nothing — the list IS the object.
     * A container, a fleet and a rule are different: each is a resource in its
     * own right that happens to hold others, so its list carries a ⛶ opening
     * ITS panel. Without this the only way into an account's own detail was
     * that it had none, which is why containers were the one thing on the
     * canvas a reader could not open. */
    owner?: SceneNode | undefined;
    /** Which border the tab rides — the list opens away from it. */
    side?: Side;
    /** Viewport rect of the tab that opened it, measured on click. */
    at?: Anchor;
  } | null;
  openInline: (v: Ctx["inline"]) => void;
  /** One resource's detail, opened straight off the canvas.
   *
   * A chip has no list to sit beside — it IS one row — so it opens the middle
   * rung directly. Same body as the list's preview and the same ⛶ out of it,
   * so "click a thing, read it, open it fully" is one motion everywhere. */
  preview: { node: SceneNode; at: Anchor } | null;
  openPreview: (v: Ctx["preview"]) => void;
  /** Row under the cursor in that list — lights it and its relations. */
  onHover: (key: string | null) => void;
  hidden: Set<string>;
  ann: ReturnType<typeof annotate>;
  selectedKey: string | null;
  onSelect: (n: SceneNode) => void;
  /**
   * Container key -> the sequence its children are drawn in.
   *
   * Read-only to the renderer, and empty for anyone who has never rearranged
   * anything — which is why `applyOrder` being the identity on an absent entry
   * is the property the whole feature rests on.
   */
  order: Record<string, string[]>;
  /** Record a new sequence for one container. Stores the FULL order, not a patch. */
  reorder: (container: string, sequence: string[]) => void;
  /**
   * Container key -> where the reader put each of its children.
   *
   * A cell answers "put it THERE", which a sequence cannot: it carries a column
   * as well as an order, so a reader can leave a deliberate gap or stand two
   * boxes side by side with nothing between them. Empty for any container never
   * arranged, and `layoutGrid` returns null on empty — so the engine's own
   * layout is still what draws for everyone who has not touched it.
   */
  cells: Record<string, Cells>;
  setCells: (container: string, cells: Cells) => void;
  /**
   * Whether the diagram is in arrange mode.
   *
   * A MODE, not a preference — it is never saved. Rearranging is something a
   * reader does for a minute and then stops; restoring a console into it next
   * session would be restoring a half-finished action.
   *
   * It exists because the hover affordance it replaced could not be found. The
   * controls were 15px of grey on white, appeared only under the cursor, and
   * sat at `z-10` beneath the border rails at `z-20` — so on any box with rails
   * they were not merely subtle, they were painted over. Nothing on the page
   * said the diagram could be rearranged at all.
   */
  arranging: boolean;
  /** Resources whose connection lines stay drawn after the cursor leaves. */
  pinnedTraces: readonly string[];
  togglePinnedTrace: (key: string) => void;
  /** Replace the whole pinned set — the bulk control's one move. */
  setPinnedTraces: (keys: string[]) => void;
  /**
   * Where a panel goes when opened for this subject, if the reader has moved it.
   *
   * Keyed by SUBJECT, not by panel, and that distinction is the feature: the
   * memory outlives the panel being closed, so "whenever you show me this VPC's
   * list, it goes here" holds across sessions without the panel having to stay
   * open to hold its own position.
   */
  places: Record<string, Placement>;
  place: (subject: string, at: { left: number; top: number }, panel: Size) => void;
  /** Forget every panel position, without touching order or pins. */
  resetPlaces: () => void;
  /** Panels that stay open. Unpinned panels keep the one-at-a-time rule. */
  pinned: readonly PanelPref[];
  isPinned: (id: string) => boolean;
  togglePin: (panel: PanelPref) => void;
};

/** Pinned panels a reader may have at once. */
const PIN_CAP = 6;

/**
 * Bring a resource into view and say which one it was.
 *
 * A pinned panel is `position: fixed`, so it does not travel with the diagram —
 * which is right for something a reader parked deliberately, and leaves one
 * gap: scroll far enough and the panel floats over a part of the estate it has
 * nothing to do with. This closes it from the panel's side. Nothing else can:
 * the reader knows what the panel is about, and the canvas is 3,000px wide.
 *
 * The flash is a class held for a moment rather than state, for the same reason
 * `HoverLight` is one stylesheet — this touches one element and must not
 * re-render a canvas of a thousand chips to do it.
 */
function locateOnCanvas(key: string) {
  const el = document.querySelector(`[data-canvas] [data-node="${CSS.escape(key)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  el.classList.add("ring-2", "ring-primary", "rounded");
  window.setTimeout(() => el.classList.remove("ring-2", "ring-primary", "rounded"), 1400);
}

/** One panel's identity, for pinning. Lists and details cannot collide. */
const panelId = (p: { kind: "list" | "detail"; subject: string }) => `${p.kind}:${p.subject}`;

/** Whether the filter is still exactly where it started. */
const sameAsDefault = (hidden: Set<string>) =>
  hidden.size === QUIET_BY_DEFAULT.length && QUIET_BY_DEFAULT.every((k) => hidden.has(k));

/** A flat group — globals and supporting have no nesting worth drawing. */
function FlatBox({ label, nodes, ctx }: { label: string; nodes: SceneNode[]; ctx: Ctx }) {
  const shown = nodes.filter((n) => !ctx.hidden.has(`${catOf(n)}.${subOf(n)}`));
  const lanes = new Map<string, SceneNode[]>();
  for (const n of shown) {
    const key = groupOf(n);
    lanes.set(key, [...(lanes.get(key) ?? []), n]);
  }
  if (!shown.length) return null;
  const host = `flat:${label}`;
  return (
    <div className="relative rounded-md border border-border bg-surface p-3">
      <button
        onClick={(e) =>
          ctx.openInline({
            host,
            key: host,
            label,
            members: shown,
            at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
          })
        }
        title={`${label} · ${shown.length}`}
        className={cn(
          "label-caps mb-2 flex items-center gap-1.5 rounded px-1 transition-colors",
          ctx.inline?.host === host ? "bg-row-selected" : "hover:bg-row-hover",
        )}
      >
        {label} · {shown.length}
      </button>
      <InlineHost hostKey={host} ctx={ctx} />
      <div className="space-y-2">
        {(() => {
          /* Supporting services and globals are arranged like everything else.
             They were the one box on the canvas with no reorder at all, which
             made the feature read as "some boxes move" — and a reader cannot
             tell which from looking. */
          const groups = [...lanes.entries()].sort(byExposureThenSize);
          const units = groups.map(([kind]) => ({ key: kind }));
          const arranged = applyOrder(units, ctx.order[`${host}#groups`]);
          const byKind = new Map(groups);
          return arranged.map((u, i) => (
            <Reorderable
              key={u.key}
              ctx={ctx}
              container={`${host}#groups`}
              units={arranged}
              index={i}
              label={laneNoun(u.key)}
            >
              <ServiceGroup kind={u.key} members={byKind.get(u.key)!} ctx={ctx} />
            </Reorderable>
          ));
        })()}
      </div>
    </div>
  );
}

/**
 * The filter, as one control over the canvas rather than a column beside it.
 *
 * It replaced two things that answered the same question in two vocabularies:
 * a 240px standing panel of forty checkboxes, and four switches above it whose
 * state the panel could not see. A category ticked in the panel still would not
 * draw if its switch was off — which is how an identity rail came to read `2`
 * over 146 resources with nothing on screen explaining why.
 *
 * A dropdown costs a click the panel did not, and buys back the whole left
 * column for the diagram. That is the right trade for a control you set once
 * and then read the map for an hour.
 */
function FilterBar({
  groups,
  hidden,
  onToggle,
  onToggleGroup,
  onSetAll,
  shown,
  total,
}: {
  groups: {
    plane: string;
    roles: { role: string; label: string; count: number }[];
    total: number;
  }[];
  hidden: Set<string>;
  onToggle: (role: string) => void;
  onToggleGroup: (roles: string[], on: boolean) => void;
  onSetAll: (all: boolean) => void;
  shown: number;
  total: number;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  /* Collapsed by default so all thirteen categories fit without scrolling.
     Expanded, one category alone can run to nineteen services — open the
     whole list and the reader scrolls to find the heading they wanted. */
  const [shut, setShut] = useState<Set<string>>(() => new Set(groups.map((g) => g.plane)));
  const box = React.useRef<HTMLDivElement>(null);

  // Click anywhere else and it closes — a menu that needs its own button
  // pressed again is a menu that stays open over the thing it filters.
  React.useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const q = query.trim().toLowerCase();
  const match = (g: (typeof groups)[number]) =>
    !q ||
    g.plane.toLowerCase().includes(q) ||
    g.roles.some((r) => r.label.toLowerCase().includes(q));
  const rolesOf = (g: (typeof groups)[number]) =>
    q && !g.plane.toLowerCase().includes(q)
      ? g.roles.filter((r) => r.label.toLowerCase().includes(q))
      : g.roles;

  const on = (role: string) => !hidden.has(role);
  const state = (g: (typeof groups)[number]) => {
    const lit = g.roles.filter((r) => on(r.role)).length;
    return lit === 0 ? "off" : lit === g.roles.length ? "all" : "some";
  };
  const chosen = groups.filter((g) => state(g) !== "off").length;

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs transition-colors",
          open ? "border-primary bg-row-selected" : "border-border bg-surface hover:bg-row-hover",
        )}
      >
        <SlidersHorizontal size={13} className="text-muted-foreground" />
        <span>Categories</span>
        <span className="mono text-muted-foreground">
          {chosen === groups.length ? "all" : `${chosen} of ${groups.length}`}
        </span>
        <span className="text-muted-foreground">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div
          className="absolute left-0 top-full z-40 mt-1 flex flex-col overflow-hidden
                     rounded-lg border border-border bg-surface shadow-xl"
          style={{ width: PANEL.filter.w, maxHeight: `min(70vh, ${PANEL.filter.maxH}px)` }}
        >
          <div className="shrink-0 border-b border-border p-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="search categories or services…"
              className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs
                         outline-none placeholder:text-muted-foreground"
            />
            <div className="mt-2 flex items-center gap-1 text-[11px]">
              <button
                onClick={() => onSetAll(true)}
                className="rounded border border-border px-2 py-0.5 hover:bg-row-hover"
              >
                all
              </button>
              <button
                onClick={() => onSetAll(false)}
                className="rounded border border-border px-2 py-0.5 hover:bg-row-hover"
              >
                none
              </button>
              <span className="ml-auto text-muted-foreground">
                {shown.toLocaleString()} of {total.toLocaleString()} shown
              </span>
            </div>
          </div>

          {/* One scroller for every category, so a long one does not push the
              rest out of reach and the search stays pinned above it. */}
          <div className="min-h-0 flex-1 overflow-y-auto p-1">
            {groups.filter(match).map((g) => {
              const roles = rolesOf(g);
              const mark = state(g);
              // A search that matched service names opens the category holding
              // them; nobody types a filter in order to then expand six rows.
              const collapsed = shut.has(g.plane) && !q;
              return (
                <div key={g.plane} className="mb-0.5">
                  <div className="flex items-center gap-1.5 rounded px-1 hover:bg-row-hover">
                    <TriBox
                      state={mark}
                      onChange={() =>
                        onToggleGroup(
                          g.roles.map((r) => r.role),
                          mark !== "all",
                        )
                      }
                      label={g.plane}
                    />
                    <button
                      onClick={() =>
                        setShut((x) => {
                          const n = new Set(x);
                          if (n.has(g.plane)) n.delete(g.plane);
                          else n.add(g.plane);
                          return n;
                        })
                      }
                      className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
                    >
                      <span className="w-2 text-[10px] text-muted-foreground">
                        {collapsed ? "▸" : "▾"}
                      </span>
                      <span className="label-caps min-w-0 flex-1 truncate">{g.plane}</span>
                      <span className="mono text-[10px] tabular-nums text-muted-foreground">
                        {g.total}
                      </span>
                    </button>
                  </div>
                  {!collapsed &&
                    roles.map((r) => (
                      <label
                        key={r.role}
                        className="flex cursor-pointer items-center gap-2 rounded py-1 pl-7 pr-2
                                   text-xs hover:bg-row-hover"
                      >
                        <input
                          type="checkbox"
                          checked={on(r.role)}
                          onChange={() => onToggle(r.role)}
                          className="size-3 accent-[var(--color-primary)]"
                        />
                        <span className="min-w-0 flex-1 truncate">{r.label}</span>
                        <span className="mono text-[10px] tabular-nums text-muted-foreground">
                          {r.count}
                        </span>
                      </label>
                    ))}
                </div>
              );
            })}
          </div>

          <div className="shrink-0 border-t border-border px-2.5 py-1.5 text-[10px] text-muted-foreground">
            {hidden.size === 0
              ? "every category on"
              : `${hidden.size} service${hidden.size === 1 ? "" : "s"} hidden`}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * A checkbox with a third state, for a category only partly chosen.
 *
 * `indeterminate` is a DOM property with no HTML attribute, so React cannot set
 * it from JSX — it has to be written to the node after render or the half-state
 * silently draws as unchecked, which reads as "none of this category" when the
 * truth is "some of it".
 */
function TriBox({
  state,
  onChange,
  label,
}: {
  state: "all" | "some" | "off";
  onChange: () => void;
  label: string;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={state === "all"}
      onChange={onChange}
      aria-label={`${state === "all" ? "clear" : "select"} every service in ${label}`}
      className="size-3 shrink-0 accent-[var(--color-primary)]"
    />
  );
}

/**
 * A unit the reader may move among its siblings.
 *
 * **Reorder, not reposition.** There is no coordinate to drag to: sizes are
 * computed bottom-up and the grid reflows, so what a reader can change is the
 * SEQUENCE, and `applyOrder` permutes what the engine produced. A dropped box
 * therefore cannot overlap, cannot go stale when the estate grows, and cannot
 * make an export disagree with the screen — none of which is true of a stored
 * `{x, y}`. This is the constraint from §2 of the personalisation spec paying
 * for itself.
 *
 * **Within one parent only.** The drop target is the sibling list and nothing
 * else. Dragging a subnet out of its VPC would assert a containment that is not
 * true, and a diagram that lets a reader draw a false fact is worse than one
 * that will not let them tidy up.
 *
 * **Keyboard first, drag second.** The arrows are the real control and the drag
 * is the discoverable one. A drag-only affordance is not operable without a
 * pointer, and this is the sort of thing an operator does repeatedly while
 * reading — which is a keyboard task, not a mouse task.
 *
 * The handles only exist while the container is hovered or something inside it
 * has focus. A permanent pair of arrows on every box is a permanent 40px of
 * furniture on a canvas whose whole argument is that it fits on one screen.
 */
/**
 * What is currently being dragged, if anything.
 *
 * Module state rather than `dataTransfer`, because the check that matters —
 * "is this from MY container" — has to happen during `dragover`, and the
 * browser deliberately blanks `getData` there. Only `types` survives, and a
 * container key is not expressible as a MIME type. One drag exists at a time
 * per document, so a single slot is the whole requirement.
 */
let dragging: { container: string; key: string } | null = null;

function Reorderable({
  ctx,
  container,
  units,
  index,
  label,
  children,
  cell,
  cols: props_cols,
  placed,
  onSeed,
}: {
  ctx: Ctx;
  container: string;
  units: { key: string }[];
  index: number;
  label: string;
  children: React.ReactNode;
  /** Where this unit sits, once the container is arranged as a grid. */
  cell?: Cell | undefined;
  cols?: number | undefined;
  placed?: { unit: { key: string }; row: number; col: number }[] | undefined;
  /** Freezes the engine's current layout into cells, on the first move. */
  onSeed?: (() => Cells) | undefined;
}) {
  const [over, setOver] = React.useState(false);
  const key = units[index]?.key ?? "";
  const cols = props_cols ?? 1;

  /* Two vocabularies for one gesture. A container the reader has arranged into
     cells moves BY CELL — the arrow walks a column, so a box can be sent down
     into a row of its own. One that has not moves by SEQUENCE, which is all a
     flex run can express. The reader sees the same two arrows either way. */
  const moveCell = (dir: "up" | "down" | "left" | "right") => {
    const here = cell ?? [0, index];
    const [r, c] = step(here, dir, cols);
    if (r === here[0] && c === here[1]) return;
    const grid = placed ?? [];
    if (grid.length) {
      ctx.setCells(container, moveToCell(grid, key, r, c));
      return;
    }
    /* Not yet a grid: freeze what is on screen, then apply the move to it, so
       the first arrow press does not also rearrange every sibling. */
    const seeded = onSeed?.() ?? {};
    const asPlaced = units.map((u) => ({
      unit: u,
      row: seeded[u.key]?.[0] ?? 0,
      col: seeded[u.key]?.[1] ?? 0,
    }));
    ctx.setCells(container, moveToCell(asPlaced, key, r, c));
  };

  const move = (to: number) => {
    if (to < 0 || to >= units.length || to === index) return;
    ctx.reorder(container, moveTo(units, key, to));
  };

  // One sibling is not a sequence, so it gets no controls and no drop zone.
  if (units.length < 2) return <>{children}</>;

  const mine = () => dragging?.container === container && dragging.key !== key;

  return (
    <div
      /* Focusable while arranging, so alt+arrow has somewhere to land. Without
         a tabindex the handler was unreachable by keyboard entirely — the
         control existed and no key could ever reach it. */
      tabIndex={ctx.arranging ? 0 : -1}
      className={cn(
        "group/ord relative min-w-0 rounded outline-none",
        ctx.arranging && "focus-visible:ring-2 focus-visible:ring-primary",
        /* In arrange mode every movable unit is OUTLINED, so "what can I
           rearrange" is answered by looking rather than by hovering each box in
           turn to find out. This was the missing half: the gesture existed, the
           invitation did not. */
        ctx.arranging && "outline-1 outline-dashed outline-primary/40 outline-offset-2",
        // Where it would land, said plainly. A drag with no target feedback is
        // a guess, and these boxes are large enough that "which one am I over"
        // is a real question.
        over && "outline-2 outline-primary outline-offset-2",
      )}
      onDragOver={(e) => {
        /* Only a unit from THIS container may land here. A drag from a sibling
           VPC would otherwise drop into this one's order, where `applyOrder`
           ignores it as an unknown key — a move that silently does nothing is
           worse than one that is visibly refused. */
        if (!mine()) return;
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        if (!over) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        if (!mine()) return;
        e.preventDefault();
        e.stopPropagation();
        /* Landing ON a box swaps the two. In a grid that is the only move that
           conserves the arrangement: shuffling would push every later box along
           and close the gaps the reader deliberately left. */
        if (cell && placed?.length) {
          ctx.setCells(container, moveToCell(placed, dragging!.key, cell[0], cell[1]));
        } else {
          ctx.reorder(container, moveTo(units, dragging!.key, index));
        }
        dragging = null;
      }}
      onKeyDown={(e) => {
        if (!e.altKey) return;
        const dir =
          e.key === "ArrowLeft"
            ? "left"
            : e.key === "ArrowRight"
              ? "right"
              : e.key === "ArrowUp"
                ? "up"
                : e.key === "ArrowDown"
                  ? "down"
                  : null;
        if (!dir) return;
        e.preventDefault();
        e.stopPropagation();
        if (cell || onSeed) moveCell(dir);
        else move(dir === "left" || dir === "up" ? index - 1 : index + 1);
      }}
    >
      <div
        /* z-30, not z-10. The rails are z-20 and paint over everything below
           them, so on a VPC or a region — the boxes most worth rearranging —
           this cluster was not merely subtle, it was covered. */
        className={cn(
          "absolute -top-2.5 -right-1 z-30 items-center gap-px rounded border bg-surface/95 shadow-sm backdrop-blur-[1px]",
          ctx.arranging
            ? "flex border-primary ring-1 ring-primary/30"
            : "hidden border-border group-hover/ord:flex focus-within:flex",
        )}
      >
        <button
          onClick={() => move(index - 1)}
          disabled={index === 0}
          aria-label={`move ${label} earlier`}
          title="move earlier (alt+←)"
          className={cn(
            "leading-none text-muted-foreground hover:bg-row-hover hover:text-foreground",
            "disabled:opacity-25",
            ctx.arranging ? "px-1 py-0.5 text-[11px]" : "px-1 py-0.5 text-[10px]",
          )}
        >
          ‹
        </button>
        {/* The GRIP is the draggable thing, not the box.
         *
         * The box was draggable for one revision and it was wrong twice over.
         * These wrappers nest — a unit inside a VPC inside a region — so a
         * press on any empty pixel picked up whichever container owned that
         * pixel, which from the reader's side was "I tried to drag a subnet and
         * the whole diagram moved". And a `draggable` region suppresses text
         * selection throughout its subtree, so the names inside every box
         * stopped being selectable to buy a gesture nobody could aim.
         *
         * A grip is 14px, unambiguous about what it will move, and leaves the
         * other 99% of the box behaving like a box. */}
        <span
          draggable
          role="button"
          tabIndex={-1}
          aria-label={`drag to reorder ${label}`}
          title="drag to reorder"
          onDragStart={(e) => {
            dragging = { container, key };
            e.dataTransfer.effectAllowed = "move";
            // Some browsers refuse to start a drag with an empty payload.
            e.dataTransfer.setData("text/plain", key);
            e.stopPropagation();
          }}
          onDragEnd={() => {
            dragging = null;
            setOver(false);
          }}
          className={cn(
            "cursor-grab leading-none hover:text-foreground active:cursor-grabbing",
            ctx.arranging
              ? "px-2 py-1 text-sm text-primary"
              : "px-1 py-0.5 text-[10px] text-muted-foreground",
          )}
        >
          ⠿
        </span>
        <button
          onClick={() => move(index + 1)}
          disabled={index === units.length - 1}
          aria-label={`move ${label} later`}
          title="move later (alt+→)"
          className={cn(
            "leading-none text-muted-foreground hover:bg-row-hover hover:text-foreground",
            "disabled:opacity-25",
            ctx.arranging ? "px-1 py-0.5 text-[11px]" : "px-1 py-0.5 text-[10px]",
          )}
        >
          ›
        </button>
      </div>
      {children}
    </div>
  );
}

/**
 * A container's children, laid out as cells the reader can place them in.
 *
 * Two layouts, and which one runs is decided by whether the reader has ever
 * arranged this container:
 *
 * - **Never arranged** — `flex flex-wrap`, exactly as it always was. This is
 *   the determinism contract (§10) holding: `layoutGrid` returns null on an
 *   empty cell map and nothing about the engine's picture changes.
 * - **Arranged** — an explicit grid of `max-content` columns. Intrinsic sizing
 *   survives, because a `max-content` track is still as wide as its widest
 *   member; only WHICH track a box sits in becomes the reader's.
 *
 * The empty cells are the part that makes this "place it there" rather than
 * "reorder it". While arranging, every unoccupied cell is a real drop target —
 * including a spare row past the bottom — so a gap is something a reader can
 * deliberately leave rather than an accident the layout closes up.
 */
function UnitGrid({
  container,
  units,
  ctx,
}: {
  container: string;
  units: { key: string; label?: string; el: React.ReactNode }[];
  ctx: Ctx;
}) {
  const stored = ctx.cells[container];
  /* The engine's own column count, from the same `chooseColumns` that sizes
     every other grid — so a container that has never been arranged and one
     that has been arranged back to its original shape look identical. */
  const engineCols = Math.max(
    1,
    Math.min(units.length, chooseColumns(units.map(() => ({ w: MIN_CELL, h: 1 })))),
  );
  const cols = gridCols(stored, engineCols);

  /* Arranging a container for the first time freezes what is already on screen
     into cells. Without it the first drag would rearrange everything else as a
     side effect, because there would be no arrangement to move WITHIN. */
  const seed = () => seedCells(units, cols);

  /* Entering arrange mode lays the container out as a grid EVEN IF nothing is
     stored yet — otherwise there are no empty cells to aim at, and the mode
     offers no way to make the first placement. The seed is not persisted: it
     reproduces the engine's own reading order, so the picture does not change
     when the mode turns on, and the first real drop is what writes cells. */
  const effective = stored ?? (ctx.arranging ? seed() : undefined);
  const placed = layoutGrid(units, effective, cols);

  if (!placed) {
    return (
      <div className="flex flex-wrap items-start gap-2">
        {units.map((u, i) => (
          <Reorderable
            key={u.key}
            ctx={ctx}
            container={container}
            units={units}
            index={i}
            label={u.label ?? u.key}
            cell={ctx.arranging ? [Math.floor(i / cols), i % cols] : undefined}
            cols={cols}
            onSeed={seed}
          >
            {u.el}
          </Reorderable>
        ))}
      </div>
    );
  }

  const rows = gridRows(placed);
  const holes = ctx.arranging ? emptyCells(placed, cols) : [];
  return (
    <div
      className="grid items-start gap-2"
      style={{
        gridTemplateColumns: `repeat(${cols}, minmax(0, max-content))`,
        /* The spare rows have to be declared here too, or the grid is only as
           tall as its occupied rows and the drop cells below them have nowhere
           to render — the vertical headroom would exist in the model and not on
           the screen, which is the same as not existing. */
        gridTemplateRows: `repeat(${rows + (ctx.arranging ? SPARE_ROWS : 0)}, min-content)`,
      }}
    >
      {placed.map((p) => {
        const u = p.unit;
        return (
          <div
            key={u.key}
            style={{ gridRow: p.row + 1, gridColumn: p.col + 1 }}
            className="min-w-0"
          >
            <Reorderable
              ctx={ctx}
              container={container}
              units={units}
              index={units.findIndex((x) => x.key === u.key)}
              label={u.label ?? u.key}
              cell={[p.row, p.col]}
              cols={cols}
              placed={placed}
            >
              {u.el}
            </Reorderable>
          </div>
        );
      })}
      {holes.map(([r, c]) => (
        <EmptyCell
          key={`hole-${r}-${c}`}
          row={r}
          col={c}
          onDropUnit={(key) => ctx.setCells(container, moveToCell(placed, key, r, c))}
          container={container}
        />
      ))}
    </div>
  );
}

/**
 * An unoccupied cell, while arranging.
 *
 * Drawn at all only in arrange mode: a grid of dashed rectangles is scaffolding,
 * and scaffolding left up permanently reads as part of the building. It accepts
 * a drop only from its own container, for the same reason a unit does — a move
 * that silently does nothing is worse than one visibly refused.
 */
function EmptyCell({
  row,
  col,
  container,
  onDropUnit,
}: {
  row: number;
  col: number;
  container: string;
  onDropUnit: (key: string) => void;
}) {
  const [over, setOver] = React.useState(false);
  const mine = () => dragging?.container === container;
  return (
    <div
      style={{ gridRow: row + 1, gridColumn: col + 1 }}
      onDragOver={(e) => {
        if (!mine()) return;
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        if (!over) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        if (!mine()) return;
        e.preventDefault();
        e.stopPropagation();
        onDropUnit(dragging!.key);
        dragging = null;
      }}
      className={cn(
        "min-h-[44px] min-w-[100px] rounded border border-dashed transition-colors",
        over ? "border-primary bg-primary/10" : "border-border-strong/40",
      )}
      aria-hidden
    />
  );
}

/* ── one recursive box, driven entirely by placement ─────────────────── */

function SceneBox({ node, ctx }: { node: SceneNode; ctx: Ctx }) {
  const spans = spannersIn(node).filter(() => roleOf(node) === "network");
  // A binding governs residents rather than living among them, so it is drawn
  // on the border of the container it is SCOPED to - an ACL that governs four
  // subnets belongs to the VPC, not to whichever subnet a containment edge
  // happened to name.
  const hoistedAll = hoistedInto(node);
  // Hoisting lands in two different places, and conflating them left four
  // artifacts stranded inside subnets with a correct `hoist_to` that nothing
  // acted on: a binding rides this container's RAIL, an artifact belongs in
  // its BAND. Both are "not where containment put you"; only one is a border.
  const hoisted = hoistedAll.filter((c) => anchorOf(c).startsWith("rail."));
  const hoistedBand = hoistedAll.filter((c) => kindOf(c) === "record");
  const spanKeys = new Set([...spans, ...hoistedAll].map((sp) => sp.key));

  const kids = (node.children ?? []).filter(
    // A container is structure, not content: it stays whatever the filter says.
    (c) => !spanKeys.has(c.key) && (isContainer(c) || !ctx.hidden.has(`${catOf(c)}.${subOf(c)}`)),
  );

  // A boundary straddles the border LINE - it is not inside the box, it is the
  // box's edge. North carries the ways out (internet gateway, transit
  // gateway); south carries the ways down (service endpoints, VPN).
  /* The org rides the account's top-left as a TAB, not as a door.
   *
   * It is a spine container — `model.yaml` declares it `rank: 0`, the outermost
   * box the account nests inside — and in an estate with one account it
   * collapses away (§7) and lands here as an ordinary child. So it cannot
   * simply be rebound to a door role: an organization is not a way through the
   * account, it is the thing the account BELONGS TO.
   *
   * Drawn on the border anyway, because that is the honest place for a fact
   * about the box rather than a fact inside it, and left-aligned so the top
   * line reads "who owns this" at one end and "how you get in" at the other.
   *
   * It keeps its own `kind: boundary` throughout — the tab is a rendering
   * decision, not a reclassification, which is what stops the kind taxonomy
   * being bent to buy a position. */
  const orgTabs =
    roleOf(node) === "account"
      ? kids
          .filter((c) => roleOf(c) === "org")
          /* Left-aligned here rather than in the model. `edge_align` is a
             property of a ROLE that rides a border, and `org` is a spine
             container that does not — giving it the field would say the engine
             places it there, which it does not. The view decides, and says so. */
          .map((c): SceneNode =>
            c.position ? { ...c, position: { ...c.position, edge_align: "left" } } : c,
          )
      : [];
  const orgKeys = new Set(orgTabs.map((c) => c.key));
  const northEdge = [...kids.filter((c) => anchorOf(c) === "edge.n"), ...orgTabs];
  const southEdge = kids.filter((c) => ["edge.s", "edge.e", "edge.w"].includes(anchorOf(c)));
  // A rail applies to everything inside equally - drawing it in the flow would
  // claim a position in the traffic path it does not have.
  // A hoisted binding is drawn by its SCOPE container, so its containment
  // parent must not draw it as well - otherwise one ACL appears on both the
  // subnet that happens to contain it and the VPC that actually owns it.
  const railAll = [
    ...kids.filter((c) => anchorOf(c).startsWith("rail.") && (hoistOf(c) ?? node.key) === node.key),
    ...hoisted.filter((c) => !ctx.hidden.has(`${catOf(c)}.${subOf(c)}`)),
  ];
  /* Four arms, four questions — the side is the answer, not decoration:
       west   SUBJECT    who may act
       east   OBJECT     what protects the data
       south  PATH       how traffic moves through
       north  OVERSIGHT  who is watching, and what put this here

     Horizontal arms stack down a tall border, which is why 326 identity rules
     ride the side and not the foot of the account. Horizontal ones lie across
     a wide border, which suits the short lists that govern flow and change. */
  /* One list per arm. East and west used to share a single `railSide_` whose
     side came from whichever node happened to be first — fine when a domain's
     arm came from its role and no box carried both, wrong the moment the arm
     comes from the DOMAIN and a region carries identity east and deploy west. */
  /* The box's own height, measured bottom-up before anything draws, so a wall
     can tell whether its tabs fit without asking the browser. */
  const boxSize = measureNode(node);

  const railS = railAll.filter((c) => anchorOf(c) === "rail.s");
  const railN = railAll.filter((c) => anchorOf(c) === "rail.n");
  const railW = railAll.filter((c) => anchorOf(c) === "rail.w");
  const railE = railAll.filter((c) => anchorOf(c) === "rail.e");
  const flow = kids.filter((c) => anchorOf(c) === "in" && !orgKeys.has(c.key));

  // Rank decides the order, not the kind of thing. Bucketing into
  // zones-then-boxes rendered every region-scoped AZ above the VPC and pushed
  // the network - the thing the page is about - below the fold.
  const ROLE_TIE: Record<string, number> = { network: 0, zone: 1, segment: 2 };
  const ordered = [...flow].sort(
    (a, b) =>
      (a.position?.rank ?? 999) - (b.position?.rank ?? 999) ||
      (ROLE_TIE[roleOf(a)] ?? 9) - (ROLE_TIE[roleOf(b)] ?? 9) ||
      (a.name || a.id).localeCompare(b.name || b.id),
  );

  // Consecutive zones collapse into one grid so they read as parallel copies
  // of a tier (A2) rather than a stack of separate boxes.
  const rows: ({ zones: SceneNode[] } | { box: SceneNode })[] = [];
  for (const child of ordered.filter(isContainer)) {
    const last = rows[rows.length - 1];
    if (roleOf(child) === "zone" && last && "zones" in last) last.zones.push(child);
    else rows.push(roleOf(child) === "zone" ? { zones: [child] } : { box: child });
  }
  /* The ENGINE decides what is drawn, not the view. `model.yaml` has said
     `render: detail` for records all along and no code read it, so this used to
     test the kind and the two agreed only by luck. Now the position carries
     `drawn` and a model change actually changes the picture. */
  const drawable = (c: SceneNode) => ARTIFACTS_ON_CANVAS || ctx.showArtifacts || isDrawn(c);
  const leaves = [
    ...ordered.filter((c) => !isContainer(c)),
    ...hoistedBand.filter((c) => !ctx.hidden.has(`${catOf(c)}.${subOf(c)}`)),
  ].filter(drawable);

  const lanes = new Map<string, SceneNode[]>();
  const loose: SceneNode[] = [];

  for (const leaf of leaves) {
    const lane = leaf.position?.lane;
    if (lane) lanes.set(lane, [...(lanes.get(lane) ?? []), leaf]);
    else loose.push(leaf);
  }

  // Anything a wrapping rule encloses draws inside that rule's box instead of
  // loose in the container.
  const wrapped = new Set((WRAPS[node.key] ?? []).flatMap((w) => [...w.members]));
  const looseUnwrapped = loose.filter((c) => !wrapped.has(c.key));

  // A tier is only shown when the routes proved it. `unknown` means no routing
  // data was collected, and printing that on every subnet header is noise
  // dressed up as information.
  const tier = node.position?.tier;
  const derived = tier && tier !== "unknown" ? tier : null;
  const label = CONTAINER_LABEL[roleOf(node)] ?? node.layer_name ?? "Group";
  const boxHost = `box:${node.key}`;
  const contents = descendantsOf(node);

  return (
    <Box
      label={derived ? `${label} · ${derived}` : label}
      id={displayName(node)}
      count={contents.length}
      listHost={boxHost}
      ctx={ctx}
      onOpenList={(e) =>
        ctx.openInline({
          host: boxHost,
          key: boxHost,
          label: `${label} · ${displayName(node)}`,
          members: contents,
          owner: node,
          at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
        })
      }
      layer={LAYER_ID[node.layer_name ?? ""] ?? "R1"}
      edges={{ n: northEdge.length > 0, s: southEdge.length > 0 }}
      rail={railS.length > 0}
      railN={railN.length > 0}
      railW={layersOn(railW, boxSize.h)}
      railE={layersOn(railE, boxSize.h)}
      tone={containerStyle(roleOf(node), derived)}
      className={cn(
        containerStyle(roleOf(node), derived) ? "" : "bg-surface",
        /* Always drawn. Public reachability is a fact about the estate, not a
           view preference, and a warning behind a switch is a warning someone
           can leave switched off. */
        derived === "public" ? "ring-1 ring-sev-high/40" : "",
      )}
    >
      <SideRail nodes={railW} side="w" ctx={ctx} height={boxSize.h} host={node.key} />
      <SideRail nodes={railE} side="e" ctx={ctx} height={boxSize.h} host={node.key} />
      <RowRail nodes={railN} side="n" ctx={ctx} host={node.key} />
      <EdgeStrip nodes={northEdge} side="n" ctx={ctx} host={node.key} />
      <EdgeStrip
        nodes={southEdge}
        side="s"
        ctx={ctx}
        host={node.key}
        centreOut={CENTRE_OUT.includes("s")}
      />

      {/* Balancers and gateways are peers - none is upstream of the next - so
          they sit side by side (A2) rather than stacking into full-width bars
          that read as a sequence. */}
      {spans.length > 0 && (
        <div className="mb-2.5 flex flex-wrap items-start gap-2">
          {spans.map((sp) => (
            <div
              key={sp.key}
              className="flex flex-col gap-1 rounded-md border border-domain-governance/40 bg-background/40 p-2"
            >
              <NodeChip node={sp} ctx={ctx} compact />
              <span className="label-caps">spans {(sp.position?.span ?? []).join(" · ")}</span>
            </div>
          ))}
        </div>
      )}

      {/* Everything in a container groups by what it is - a subnet holding
          one instance and three interfaces reads as two kinds, not four
          unrelated boxes. Same rule as the category lanes and the rails, so a
          reader learns it once. */}
      {/* Wraps, clusters and plain groups render in ONE rank-ordered pass.
          They used to be three fixed blocks — every wrap, then every cluster,
          then the rest — so a KMS box round a database jumped ahead of the
          instances, and a subnet read database → compute. The engine had the
          order right; the view was drawing by category of container rather
          than by position. */}
      {(() => {
        const rankOf = (ns: SceneNode[]) => Math.min(...ns.map((n) => n.position?.rank ?? 999));
        /* `label` is for the reorder control's accessible name — "move Public
           subnet left" tells a screen-reader user what moved, where `move
           subnet:subnet-0a1b left` does not. Optional, because a unit keyed by
           its service already reads as a word. */
        const units: { key: string; rank: number; label?: string; el: React.ReactNode }[] = [];

        /* Sub-containers join the same pass. They used to render as a fixed
           block BEFORE it, so rank stopped being honoured the moment a
           container was involved: the account holds CloudFront and Route 53 at
           rank 10 (L1, the front door) and the region at rank 20, and the region
           drew first anyway. The most internet-facing thing in the estate sat
           below the network that hides behind it — A1 inverted, in the one
           comparison where it matters most. */
        rows.forEach((row) => {
          if ("zones" in row) {
            units.push({
              /* Content-derived, not `zones-${i}`. An index names a POSITION,
                 so the same row answered to a different name the moment
                 anything before it appeared — fine while nothing remembered it,
                 wrong now that a saved order can. */
              key: zoneRowKey(row.zones),
              rank: rankOf(row.zones),
              label: `${row.zones.length} availability zones`,
              el: (
                <SiblingRow
                  items={row.zones}
                  ctx={ctx}
                  /* Zones reorder WITHIN their row, under the row's own key.
                     A row is one unit to the container above it and a list of
                     peers to the reader inside it, so the two orders are
                     independent and must not share a key. */
                  orderKey={zoneRowKey(row.zones)}
                  render={(z) => <SceneBox node={without(z, spanKeys)} ctx={ctx} />}
                />
              ),
            });
          } else {
            units.push({
              key: row.box.key,
              rank: row.box.position?.rank ?? 999,
              label: displayName(row.box),
              el: <SceneBox node={without(row.box, spanKeys)} ctx={ctx} />,
            });
          }
        });

        for (const { rule, members } of WRAPS[node.key] ?? []) {
          const inside = loose.filter((c) => members.has(c.key));
          if (inside.length) {
            units.push({
              key: rule.key,
              rank: rankOf(inside),
              el: <RuleWrap rule={rule} members={inside} ctx={ctx} />,
            });
          }
        }
        for (const { cluster, members } of clusterRuns(looseUnwrapped)) {
          if (cluster) {
            units.push({
              key: cluster,
              rank: rankOf(members),
              el: <ClusterBox cluster={cluster} members={members} ctx={ctx} />,
            });
            continue;
          }
          for (const [kind, list] of members.reduce((m, n) => {
            const k = groupOf(n);
            return m.set(k, [...(m.get(k) ?? []), n]);
          }, new Map<string, SceneNode[]>())) {
            units.push({
              key: kind,
              rank: rankOf(list),
              el: (
                <div className="min-w-0 flex-1 basis-[200px]">
                  <ServiceGroup kind={kind} members={list} ctx={ctx} />
                </div>
              ),
            });
          }
        }
        if (!units.length) return null;
        // Rank first, then the same tie-break the engine uses, so the view
        // never invents an order the scene did not already have.
        units.sort(byRank);
        /* Then, and only then, whatever the reader arranged. `applyOrder` is
           the identity with no preference, so the line above remains the answer
           for everyone who has never dragged anything — which is what keeps the
           determinism contract (§10) true rather than merely usually true. */
        const seq = ctx.order[node.key];
        const shown = applyOrder(units, seq);
        return <UnitGrid container={node.key} units={shown} ctx={ctx} />;
      })()}

      {lanes.size > 0 &&
        (() => {
          /* A band drawn one column per lane is as tall as its WORST lane while
             its best use a fraction of that: 518px of region because datastore
             stacks object, nosql and file, beside two lanes 62px tall.

             So spend width on the tall ones. The width is not ours to choose —
             the container is already as wide as its widest child, and a band
             narrower than that leaves dead space to its right — so the budget is
             that width, and it goes to whichever lane is currently tallest. */
          const engineShapes = [...lanes.entries()].map(([lane, members]) => ({
            key: lane,
            rank: Math.min(...members.map((n) => n.position?.rank ?? 999)),
            blocks: laneBlocks(lane, members),
          }));
          /* A band's lanes reorder by REWRITING their rank to the reader's
             index, not by pre-sorting. `packRows` sorts by rank internally —
             deliberately, since reading order is the traffic path and a lane
             may never be pulled forward to fill a gap — so a pre-sorted list
             would simply be sorted back. Rewriting rank is how a reader's
             sequence becomes the order packing already respects.
             Only when a preference exists: otherwise this would flatten the
             engine's own ranks to indices and quietly change every tie-break. */
          const laneSeq = ctx.order[`${node.key}#lanes`];
          const shapes = laneSeq
            ? applyOrder(engineShapes, laneSeq).map((s, i) => ({ ...s, rank: i }))
            : engineShapes;
          const widest = Math.max(
            0,
            ...rows.map((r) =>
              "zones" in r
                ? r.zones.reduce((t, z) => t + measureNode(z).w, 0)
                : measureNode(r.box).w,
            ),
          );
          const budget = columnBudget(widest, CHIP_W + PAD * 2, shapes.length);
          const cols = allocate(shapes, budget);
          const byKey = new Map(lanes);
          /* Lanes reorder against the WHOLE band, not against the row they
             happened to be packed into. Packing is a consequence of width — a
             lane moves rows when its neighbours grow — so an index within a row
             is not a stable thing for a reader to arrange against. */
          const laneUnits = shapes.map((sh) => ({ key: sh.key }));
          return packRows(shapes, cols, budget).map((row, i) => (
            <div key={`band-${i}`} className="mb-4 flex flex-wrap items-start gap-4 last:mb-0">
              {row.map((shape) => (
                <Reorderable
                  key={shape.key}
                  ctx={ctx}
                  container={`${node.key}#lanes`}
                  units={laneUnits}
                  index={laneUnits.findIndex((u) => u.key === shape.key)}
                  label={laneNoun(shape.key)}
                >
                  <div className="shrink-0">
                    <Lane
                      lane={shape.key}
                      members={byKey.get(shape.key)!}
                      ctx={ctx}
                      cols={cols.get(shape.key) ?? 1}
                    />
                  </div>
                </Reorderable>
              ))}
            </div>
          ));
        })()}

      {/* ON the border line, and able to stay there because it is ONE line of
          fixed height. The earlier attempt floated a wrapping panel of groups,
          whose height nobody could predict - so a subnet's rail landed on its
          neighbour's header and the VPC's landed on the band below. A strip
          that never wraps has a height the container can reserve, which is what
          makes straddling safe rather than merely intended.

          Names live in the panel: a border is for saying WHAT governs this box
          and HOW MANY, not for listing them. */}
      {/* Which edge a strip takes is a question of room, not taste: a strip
          needs roughly one chip per group, so it goes on a horizontal border
          while that fits and scrolls only past the point where a vertical edge
          would be no better. A container narrow enough that neither works has
          no business carrying a strip - which is why a segment's dangling
          interfaces stay inline instead. */}
      <RowRail nodes={railS} side="s" ctx={ctx} host={node.key} />
    </Box>
  );
}

/**
 * A rule strip lying along a horizontal border.
 *
 * North and south are the same object on opposite edges, and the side is the
 * whole meaning: south governs the flow beneath it, north governs what arrives
 * and what changed. Straddling the line rather than sitting inside it, because
 * a rule is not a resident of the box - it is a condition on it.
 *
 * Counts only, grouped. A border says WHAT applies here and HOW MANY; which
 * ones is a click away.
 */
function RowRail({
  nodes,
  side,
  ctx,
  host,
}: {
  nodes: SceneNode[];
  side: "n" | "s";
  ctx: Ctx;
  host: string;
}) {
  if (!nodes.length) return null;
  /* A horizontal border is wide, so this arm can afford the family name where
     the vertical strip cannot: "management · encryption" rather than six
     separate service chips. */
  const groups = [
    ...nodes
      .reduce((m, r) => {
        const family = rollupOf(r) ?? familyLabel(r);
        return m.set(family, [...(m.get(family) ?? []), r]);
      }, new Map<string, SceneNode[]>())
      .entries(),
  ].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));

  const shape = tabShape(side);
  /* Rail tabs arrange too. The arm's order is a reading order like any other —
     which discipline you meet first going along a border — and leaving it out
     made the feature inconsistent in the one place a reader is most likely to
     want a particular tab first. Applied AFTER the size sort above, so the
     engine's answer still stands for anyone who has not rearranged. */
  const railKey = `${host}#rail.${side}`;
  const ordered = applyOrder(
    groups.map(([kind]) => ({ key: kind })),
    ctx.order[railKey],
  );
  const byKind = new Map(groups);
  const tabs = ordered.slice(0, 8).map(({ key: kind }, ti) => (
    <Reorderable
      key={kind}
      ctx={ctx}
      container={railKey}
      units={ordered.slice(0, 8)}
      index={ti}
      label={kind}
    >
      <TabHost key={kind} hostKey={`${host}:${kind}`} ctx={ctx}>
        <button
          onClick={(e) =>
            ctx.openInline({
              host: `${host}:${kind}`,
              key: `${host}:${kind}`,
              label: kind,
              members: byKind.get(kind)!,
              side,
              at: railAnchor(e, side),
            })
          }
          data-node={byKind.get(kind)![0]!.key}
          data-members={memberAttr(byKind.get(kind)!)}
          title={`${familyTitle(byKind.get(kind)![0]!)} · ${byKind.get(kind)!.length}`}
          className={cn(
            "flex shrink-0 items-center gap-1.5 border border-border px-2 py-0.5 text-[11px]",
            "hover:bg-row-hover",
            shape.open,
          )}
          /* Depth stated, not left to the content — the vertical tabs take theirs
         from `RAIL_DEPTH` and a horizontal one that sized itself came out 21px
         against their 26, so the same object read as two thicknesses depending
         on which border it was on. */
          style={{ ...shape, ...railTone(byKind.get(kind)![0]!), height: RAIL_DEPTH }}
        >
          <Icon resourceKey={byKind.get(kind)![0]!.type} size={12} />
          <span className="truncate font-semibold" style={{ maxWidth: RAIL_LABEL_MAX }}>
            {kind}
          </span>
          <span className="tabular-nums text-muted-foreground">{byKind.get(kind)!.length}</span>
        </button>
      </TabHost>
    </Reorderable>
  ));

  /* Standing ON the border it applies to: a north tab's bottom edge IS the top
     border, a south tab's top edge IS the bottom one. Nothing straddles and
     nothing floats — the open side of each tab is the side facing the box. */
  return (
    <div
      className={cn(
        "absolute left-6 right-6 z-20 flex gap-1.5 overflow-x-auto",
        side === "n"
          ? "top-0 -translate-y-full items-end"
          : "bottom-0 translate-y-full items-start",
      )}
    >
      {tabs}
    </div>
  );
}

/**
 * Boundary objects, drawn ON the border line.
 *
 * An internet gateway is not IN a VPC; it IS the VPC's edge. Drawing it as a
 * row inside the box says something false about where traffic meets the
 * network, so the strip is pulled half outside and straddles the border - the
 * same thing an architect draws by hand.
 */
function EdgeStrip({
  nodes,
  side,
  ctx,
  centreOut,
  host,
}: {
  nodes: SceneNode[];
  side: "n" | "s";
  ctx: Ctx;
  /** The box this strip straddles — what the list will cover. */
  host: string;
  centreOut?: boolean;
}) {
  if (!nodes.length) return null;
  // The south border is where a private network reaches everything outside it,
  // so it reads CENTRE-OUT by how public the destination is: the way to the
  // open internet takes the middle, private service access flanks it, and the
  // links to your own datacentre sit at the ends.
  const ordered = [...nodes].sort(
    (a, b) => edgeRankOf(a) - edgeRankOf(b) || (a.name || a.id).localeCompare(b.name || b.id),
  );
  const laid = centreOut
    ? ordered.reduce<SceneNode[]>((row, n, i) => (i % 2 ? [...row, n] : [n, ...row]), [])
    : ordered;

  /* Presented as tabs, like everything else on a border.
     
     A door used to draw as a floating pill straddling the line while the rails
     beside it drew as attached tabs — two visual languages for two things that
     are both "this is on the boundary", so a transit gateway and a firewall
     rail read as unrelated kinds of object. Same shape now: open on the side
     facing the box, rounded away from it.
     
     They keep their NAMES rather than collapsing to a count. A rail tab answers
     "what applies here"; a door answers "which way out is this", and there is
     usually one of each — a count would hide the only thing worth reading. */
  const shape = tabShape(side);

  /* Grouped by domain and counted, exactly like a rail tab.
     
     A door used to print its own identifier — `igw-0bd70b92d3af8949e` — which
     is the one thing on the border that could not be scanned. Every other tab
     answers "what is here, and how many"; a door answering "here is a
     twenty-character id" made the border two languages. The ids are one click
     away in the same table the rails open. */
  const domainGroups = (ns: SceneNode[]) => [
    ...ns
      .reduce((m, n) => {
        const d = railLabel(catOf(n), subOf(n));
        return m.set(d, [...(m.get(d) ?? []), n]);
      }, new Map<string, SceneNode[]>())
      .entries(),
  ];

  /* Three zones on one line, rather than one centred run.
   *
   * `edge_rank` has always ordered things ALONG an arm and said nothing about
   * where the run begins, so every strip started in the middle. That is right
   * for a segment's south border — the ways out belong together, centre-out by
   * how public the destination is — and wrong for an account's top line, which
   * has two ends and a different question at each: who owns this, and how you
   * get in.
   *
   * The zones are always rendered, empty or not, because `justify-between`
   * collapses toward whichever end has content when one is missing — so an
   * account with a CDN and no org tab would drift its doors to the left and
   * read as though something were missing from the right. */
  const zones: Array<["left" | "centre" | "right", SceneNode[]]> = [
    ["left", laid.filter((n) => edgeAlignOf(n) === "left")],
    ["centre", laid.filter((n) => edgeAlignOf(n) === "centre")],
    ["right", laid.filter((n) => edgeAlignOf(n) === "right")],
  ];

  return (
    <div
      className={cn(
        "absolute left-6 right-6 z-10 flex gap-1.5",
        side === "n"
          ? "top-0 -translate-y-full items-end"
          : "bottom-0 translate-y-full items-start",
        // Centre when nothing asks for an end, so a border that predates
        // alignment draws exactly as it always did.
        zones.some(([z, ns]) => z !== "centre" && ns.length) ? "justify-between" : "justify-center",
      )}
    >
      {zones.map(([zone, ns]) => (
        <div key={zone} className="flex flex-wrap items-end gap-1.5">
          {domainGroups(ns).map(([label, list]) => (
            <TabHost key={label} hostKey={`${host}:${label}`} ctx={ctx}>
              <button
                onClick={(e) =>
                  ctx.openInline({
                    host: `${host}:${label}`,
                    key: `${host}:${label}`,
                    label,
                    members: list,
                    side,
                    at: railAnchor(e, side),
                  })
                }
                data-node={list[0]!.key}
                data-members={memberAttr(list)}
                title={`${label} · ${list.length}`}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 border border-border px-2 py-0.5 text-[11px]",
                  "hover:bg-row-hover",
                  shape.open,
                )}
                style={{ ...shape, ...doorTone(list[0]!), height: RAIL_DEPTH }}
              >
                <Icon resourceKey={list[0]!.type} size={12} />
                <span className="truncate font-semibold" style={{ maxWidth: RAIL_LABEL_MAX }}>
                  {label}
                </span>
                <span className="tabular-nums text-muted-foreground">{list.length}</span>
              </button>
            </TabHost>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ── space allocation ──────────────────────────────────────────────────
   A diagram tool has to hold from a sandbox account to an estate with
   hundreds of subnets, so a single sizing formula is the wrong shape: any
   constant that reads well at four siblings is unreadable at forty. What
   scales is a LADDER, where each rung has a defined behaviour and a stated
   limit, and the rung is chosen from how much room there actually is.

     row      k fits at full width    -> share space by √weight
     grid     k fits when wrapped     -> ceil(√k) columns, capped by capacity
     summary  k exceeds both          -> the heaviest few, rest behind a count

   √weight rather than weight: on this estate a subnet holding 2 things next
   to ones holding 11 gets 12.6% of the row instead of 5.9%, which is the
   difference between a narrow box and an unreadable one. It still concedes
   the ~12% that equal sizing wasted on it.

   MIN_CELL is the floor and it is not negotiable. When siblings × MIN_CELL
   exceeds the room available, the answer is to change rung - never to keep
   dividing until nothing can be read.                                      */
/* ── container hierarchy ───────────────────────────────────────────────
   AWS's own architecture-diagram convention, taken from the Group icons we
   already vendor - their fill colours ARE the language: a VPC is purple, a
   region and an availability zone are teal, an account is magenta. Adopting
   it means anyone who has read an AWS diagram can read this one.

   Two rules carry the depth, and both are true in AWS's diagrams already:

     solid border  = a real boundary. A VPC and a subnet are addressable.
     dashed border = a label for where things are, or a grouping we invented.
                     A region, an availability zone, a category lane.

     weight recedes with depth. Border width, label size and fill opacity
     all step down as you nest, so the eye finds the outermost boundary
     first instead of five identical grey rectangles.                       */
/**
 * How a container is drawn.
 *
 * One rule: **use the provider's colour where the provider prescribes one, and
 * a neutral grey where it does not.**
 *
 * AWS ships Architecture Group icons for exactly these five — AWS Account,
 * Region, VPC, Availability Zone, Subnet — with a colour for each. Those are
 * the boundaries every AWS diagram in the world already draws that way, so a
 * reader arrives knowing them. Repainting them grey would spend recognition
 * for nothing.
 *
 * It ships no colour for an EKS cluster, a scaling group or a security group
 * boundary, so those take the grey ramp instead (see ClusterBox, RuleWrap).
 * Inventing a hue for them would assert a convention that does not exist.
 *
 * Line style carries the rest: solid means an addressable boundary you can be
 * inside of, dashed means a label for where something is — which is why AWS
 * ships no Availability Zone tile and every hand-drawn diagram uses a dashed
 * box for one.
 */
const NEUTRAL_BOX = "rounded-md border border-dashed border-border-strong";
const NEUTRAL_BOX_BG = grey(RAMP.orchestrator);
/** Step 2 — a service group. Lighter, because it sits inside step 1. */
const NEUTRAL_GROUP_BG = grey(RAMP.group);

const MIN_CELL = 160; // px: narrowest box that still shows a resource name
const CHIP = 110; // px: a border-strip chip, for deciding its axis
/* Rungs. 6 is a ~1000px canvas divided by the 160px floor - the point past
   which sharing space stops producing readable boxes. Chosen from the COUNT
   rather than a measurement, so the rung is deterministic and testable
   offline, which a ResizeObserver would not be. */
const ROW_MAX = 6; // beyond this, wrap into a grid
const GRID_MAX = 18; // beyond this, stop drawing and start summarising
const SUMMARY_KEEP = 6; // how many survive into a summary

/**
 * What a node needs, bottom-up.
 *
 * A leaf reports its chip; a group reports the chips it will show; a container
 * reports the grid its children pack into. Nothing consults the window - the
 * same estate measures identically on a laptop, a monitor and in an export.
 */
function measureNode(n: SceneNode): Size {
  const kids = n.children ?? [];
  if (!isContainer(n)) {
    return measureChip();
  }
  const groups = new Map<string, SceneNode[]>();
  const boxes: Size[] = [];
  for (const c of kids) {
    if (isContainer(c)) boxes.push(measureNode(c));
    else groups.set(groupOf(c), [...(groups.get(groupOf(c)) ?? []), c]);
  }
  for (const members of groups.values()) {
    boxes.push(measureGroup(members.map((m) => measureNode(m))));
  }
  return measureContainer(boxes);
}

/** Visible leaves — what actually occupies space, not node count. */
function weightOf(n: SceneNode): number {
  const kids = n.children ?? [];
  return kids.length ? kids.reduce((t, c) => t + weightOf(c), 0) : 1;
}

/** Proportional share, damped and floored. */
function sizing(n: SceneNode) {
  return { flexGrow: Math.sqrt(weightOf(n)), flexBasis: 0, minWidth: MIN_CELL };
}

/**
 * A row of sibling containers, on whichever rung the count calls for.
 *
 *   k <= ROW_MAX    share the row by sqrt(weight)
 *   k <= GRID_MAX   wrap, still sized by weight
 *   k >  GRID_MAX   the heaviest few, and a count for the rest
 *
 * The floor is what forces the ladder: once siblings x MIN_CELL exceeds the
 * room available, dividing further produces boxes too narrow to read a name
 * in. Summarising is the honest answer - shrinking is not.
 */
function SiblingRow({
  items,
  ctx,
  render,
  orderKey,
}: {
  items: SceneNode[];
  ctx: Ctx;
  render: (n: SceneNode) => React.ReactNode;
  /** Where this row's reader-arranged sequence is stored, when it has one. */
  orderKey?: string;
}) {
  const [all, setAll] = useState(false);
  const heavy = [...items].sort(
    (a, b) => weightOf(b) - weightOf(a) || (a.name || a.id).localeCompare(b.name || b.id),
  );
  const summarising = items.length > GRID_MAX && !all;
  /* The reader's order applies to what is DRAWN, so it goes on after
     summarising rather than before. Arranging six zones and then seeing the
     four heaviest is one question; arranging them and seeing a different four
     because the arrangement changed which were "first" is another. */
  const engineShown = summarising ? heavy.slice(0, SUMMARY_KEEP) : items;
  const shown = orderKey ? applyOrder(engineShown, ctx.order[orderKey]) : engineShown;

  // Columns come from the children's own measurements, so `cols` is literally
  // this container's horizontal arm and `ceil(n/cols)` its vertical one.
  const sizes = shown.map(measureNode);
  const cols = chooseColumns(sizes);

  /* Peers of the same kind get equal columns. Two availability zones are the
     same kind of thing, so drawing one wider than the other says something
     untrue - that one holds more, or matters more - when the only difference
     is how long the names inside happened to be. Mixed siblings keep
     `max-content`, because there a box that needs more room should get it. */
  const uniform = shown.length > 1 && new Set(shown.map((n) => n.type)).size === 1;
  const track = Math.max(MIN_CELL, ...sizes.map((z) => z.w));

  /* Uniform peers go side by side as COLUMNS, each as tall as it needs.
     Redundancy is the horizontal axis (A2), so three availability zones beside
     each other say "three copies of the same thing" in a way a stack cannot —
     stacked, the vertical axis says downstream, which is false of a peer.

     Equal fractions rather than max-content, because a zone holding one subnet
     and a zone holding four are still peers: drawing one narrower would say it
     matters less, when the only difference is what happened to land there. */
  const arm = uniform ? shown.length : cols;
  const columns = uniform
    ? `repeat(${arm}, minmax(0, 1fr))`
    : `repeat(${cols}, minmax(0, max-content))`;

  return (
    <div
      className="mb-4 grid items-start gap-4"
      style={{
        gridTemplateColumns: columns,
        // A floor, not a target: `max-content` decides the width, this only
        // stops a container with one short name collapsing to a sliver.
        // Each column needs room for a resource name; below that the columns
        // stop being readable and wrapping is the lesser evil.
        ...(uniform ? { minWidth: Math.min(arm * MIN_CELL, MIN_CELL * 3) } : {}),
      }}
    >
      {shown.map((n, i) =>
        orderKey ? (
          <Reorderable
            key={n.key}
            ctx={ctx}
            container={orderKey}
            units={shown}
            index={i}
            label={displayName(n)}
          >
            {render(n)}
          </Reorderable>
        ) : (
          <div key={n.key} className="min-w-0">
            {render(n)}
          </div>
        ),
      )}
      {summarising && (
        <button
          onClick={() => setAll(true)}
          style={{ minWidth: MIN_CELL }}
          className="self-stretch rounded-md border border-dashed border-border
                           px-3 py-2 text-xs text-muted-foreground hover:bg-row-hover"
        >
          +{items.length - SUMMARY_KEEP} more
          <span className="mt-1 block text-[10px]">show all</span>
        </button>
      )}
    </div>
  );
}

/**
 * A side wall: its slots in order down the border, each split across its layers.
 *
 * Which slot a resource takes comes from its DOMAIN, so a wall is the same wall
 * on every box — the account's east wall is security and so is the region's. A
 * reader learns the compass once.
 *
 * Two layers, on the wall that needs them. The west arm carries the most tabs of
 * any: ten at the region, and one column of ten is a wall of text. Splitting
 * halves it to five, the same arithmetic that took the regional band from 792px
 * to 256px — a tall column is a height problem and a second column is the
 * answer.
 *
 * The layers grow AWAY from the box, never into it, so the open side of every
 * tab still faces the container it names.
 */
function SideRail({
  host,
  nodes,
  side,
  ctx,
  height,
}: {
  nodes: SceneNode[];
  side: "w" | "e";
  ctx: Ctx;
  /** The box's own height, so the wall knows whether its tabs fit. */
  height: number;
  /** The box this wall rides — what the list will cover. */
  host: string;
}) {
  if (!nodes.length) return null;

  const bySlot = new Map<string, SceneNode[]>();
  for (const n of nodes) {
    const slot = slotOf(n);
    bySlot.set(slot, [...(bySlot.get(slot) ?? []), n]);
  }
  const slots = [...bySlot.entries()].sort(
    (a, b) => alongRank(alongOf(a[1][0]!)) - alongRank(alongOf(b[1][0]!)),
  );

  /* Every slot on the wall, flattened into one ordered run of tabs, and only
     THEN split. Splitting per slot would give each its own pair of columns and
     leave a ragged edge wherever a slot held an odd number. */
  const engineTabs = slots.flatMap(([, members]) => groupByDomain(members));
  /* The wall arranges like everything else. Applied to the flattened run
     BEFORE splitting into layers, because the split is a consequence of height
     — a tab changes column when its neighbours grow — so a position within a
     column is not a stable thing for a reader to arrange against. */
  const railKey = `${host}#rail.${side}`;
  const tabOrder = ctx.order[railKey];
  const tabs = tabOrder
    ? applyOrder(
        engineTabs.map((t) => ({ ...t, key: t.domain })),
        tabOrder,
      )
    : engineTabs;
  /* A second layer only when the first will not hold them. A wall with room to
     spare reads straight down; splitting it early gives two short columns and
     charges the container width it did not have to spend. */
  const layers = splitLayers(
    tabs,
    layersNeeded(tabs.length, height, Math.max(...nodes.map((n) => layersOf(n)), 1)),
  );
  const shape = tabShape(side);
  const along = tabRun(side);

  return (
    <div
      /* Bounded by the box, and wrapping into parallel columns when the tabs
         do not fit.
         `layersNeeded` decides the column count from `measureNode`'s height,
         and that number disagreed with the rendered box — 12 tabs at 150px ran
         to 1,866px down the side of a box 1,098px tall, because the model said
         one layer was enough. Rather than trust an arithmetic answer against a
         height that is already wrong, `top-6 bottom-6` bounds the wall to the
         box itself and `flex-wrap` puts the overflow in the next column. The
         browser measures what the browser drew.
         This is layout by the box's OWN height, not by measuring the DOM: no
         JavaScript reads a rectangle, and the diagram still renders the same
         twice. */
      className={cn(
        "absolute inset-y-6 z-20 flex content-start",
        side === "w" ? "left-0 -translate-x-full flex-row-reverse" : "right-0 translate-x-full",
      )}
    >
      {layers.map((column, i) => (
        /* No gaps: a wall is one object, so its tabs meet each other and meet
           the border they name. A gap read as several separate strips.

           Wrap direction follows the side. Items fill the first column before
           overflowing, so the first column is always the fullest — and on the
           west wall, which is translated OUT from the box, normal wrap put that
           fullest column furthest from the border. Reversing it there keeps the
           densest column against the arm it belongs to, on both sides. */
        <div
          key={i}
          className={cn("flex flex-col", side === "w" ? "flex-wrap-reverse" : "flex-wrap")}
          style={{ maxHeight: "100%" }}
        >
          {column.map(({ domain, members }) => (
            /* The wall HOSTS its list, which for a long time it did not.
             *
             * A side tab set `ctx.inline` and no component anywhere rendered
             * that host, so the west wall's 63 identity bindings, the east
             * wall's encryption and every other vertical arm were dead clicks
             * — state changed, nothing appeared. `RowRail` and `EdgeStrip` got
             * their host from `TabHost`; this one was never given one, and the
             * bug was invisible because the north and south arms of the same
             * box worked.
             *
             * A Fragment rather than `TabHost`, because `TabHost`'s wrapping
             * span would become a flex child of the column and take a slot in
             * the wall. `InlineHost` renders either nothing or a portal, so it
             * costs the layout nothing either way. */
            <React.Fragment key={domain}>
              <button
                onClick={(e) =>
                  ctx.openInline({
                    host: `${host}:${domain}`,
                    key: `${host}:${domain}`,
                    label: domain,
                    members,
                    side,
                    at: railAnchor(e, side),
                  })
                }
                data-node={members[0]!.key}
                data-members={memberAttr(members)}
                title={`${familyTitle(members[0]!)} · ${members.length}`}
                className={cn(
                  "flex items-center gap-1.5 overflow-hidden border border-border bg-surface",
                  "px-1 py-1.5 hover:bg-row-hover",
                  shape.open,
                )}
                style={{
                  ...shape,
                  ...along,
                  ...railTone(members[0]!),
                  width: RAIL_DEPTH,
                  height: RAIL_TAB_LEN,
                }}
              >
                <span className="truncate text-[11px] font-semibold">
                  {railLabel(catOf(members[0]!), rollupOf(members[0]!) ?? subOf(members[0]!))}
                </span>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {members.length}
                </span>
              </button>
              <InlineHost hostKey={`${host}:${domain}`} ctx={ctx} />
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  );
}

/* How many chips a group draws before it collapses to a count. Imported, not
   declared: these were 5 and 2 here while `measureGroup` sized every group
   against a VISIBLE of 3, so the model and the picture disagreed by two chips
   on every truncated group and nothing compared them. */
const COLLAPSE_AT = VISIBLE;
const BORDER_COLLAPSE_AT = VISIBLE_TIGHT;

/* Type scale. A border strip runs alongside the box rather than inside it, so
   it has to stay quiet without becoming unreadable: one step down from the
   inline chips, never below 11px, which is the floor for a monospaced id at
   normal viewing distance. Stated once here rather than sprinkled through the
   markup, so "small but visible" is a rule and not a series of guesses. */
const TYPE_SCALE = {
  inline: { label: "text-[11px]", name: "text-[13px]" },
  borderStrip: { label: "text-[10px]", name: "text-[11px]" },
};

/**
 * A category lane, subdivided by what each service actually is.
 *
 * The lane says WHERE something sits in the architecture; the sub-group says
 * WHAT it is. Ninety-four resources under one `datastore` heading is a list
 * you have to read; the same set split into object storage, file storage and
 * key-value is a picture you can scan - and it keeps like with like, so an S3
 * bucket never sits between two unrelated things.
 */
/** Bands the model marks `collapsed` open on demand rather than by default. */
const COLLAPSED_LANES = new Set(["artifacts"]);

/** `resident.integration` -> "integration". A lane is a position; its role name
    is the engine's business, and renaming roles must never rewrite the page. */

/**
 * A lane's subcategory blocks, in reading order, each with its drawn height.
 *
 * The block is the unit a lane splits on: `datastore` becomes object │ nosql │
 * file, and each column keeps a meaning. Splitting on service groups instead
 * would pack marginally tighter and leave columns that are just "some of the
 * datastore", which is not a thing anyone can name.
 */
function laneBlocks(lane: string, members: SceneNode[]) {
  const bySub = new Map<string, SceneNode[]>();
  for (const n of members) {
    const sub = subOf(n);
    bySub.set(sub, [...(bySub.get(sub) ?? []), n]);
  }
  return [...bySub.entries()]
    .sort(
      (a, b) =>
        (a[1][0]!.position?.sub_rank ?? 999) - (b[1][0]!.position?.sub_rank ?? 999) ||
        a[0].localeCompare(b[0]),
    )
    .map(([sub, list]) => {
      const byKind = new Map<string, SceneNode[]>();
      for (const n of list) byKind.set(groupOf(n), [...(byKind.get(groupOf(n)) ?? []), n]);
      const groups = [...byKind.entries()].sort(byExposureThenSize);
      return {
        key: `${lane}/${sub}`,
        sub,
        groups,
        h: measureContainer(
          groups.map(([, g]) => measureGroup(g.map(measureNode))),
          { cols: 1, header: false },
        ).h,
      };
    });
}

function Lane({
  lane,
  members,
  ctx,
  cols = 1,
}: {
  lane: string;
  members: SceneNode[];
  ctx: Ctx;
  /** Columns this lane was allocated, from `allocate()`. */
  cols?: number;
}) {
  // The model marks some bands `collapsed`: provenance and output are real and
  // worth finding, but showing 66 of them by default buries the architecture
  // they are provenance OF.
  const [shut, setShut] = useState(COLLAPSED_LANES.has(lane));
  const blocks = laneBlocks(lane, members);
  const columns = splitLane(blocks, cols);
  const host = `lane:${lane}:${members[0]?.key ?? ""}`;

  return (
    <div className="relative min-w-0 rounded-md border border-border bg-surface p-2">
      {/* Two separate questions, so two separate controls.
       *
       * The heading used to do one thing — collapse — which meant the only way
       * to read a band's 66 members was to expand it and read tiles that give
       * counts rather than names. The NAME now opens the band's list like every
       * other heading on the canvas; the chevron keeps the collapse. */}
      <div className="mb-1.5 flex w-full items-center gap-1.5">
        <button
          onClick={(e) =>
            ctx.openInline({
              host,
              key: host,
              label: laneNoun(lane),
              members,
              at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
            })
          }
          title={`${laneNoun(lane)} · ${members.length}`}
          className={cn(
            "label-caps flex min-w-0 flex-1 items-center gap-1.5 rounded px-1 transition-colors",
            ctx.inline?.host === host ? "bg-row-selected" : "hover:bg-row-hover",
          )}
        >
          <span className="truncate">{laneNoun(lane)}</span>
          <span className="text-muted-foreground">{members.length}</span>
        </button>
        <button
          onClick={() => setShut(!shut)}
          aria-label={shut ? "expand" : "collapse"}
          className="rounded px-1 text-muted-foreground hover:bg-row-hover hover:text-foreground"
        >
          {shut ? "▸" : "▾"}
        </button>
        <InlineHost hostKey={host} ctx={ctx} />
      </div>
      {!shut && (
        /* Every column the same width, whatever it holds — a grid that stays a
           grid. The height a column does not use it simply does not take;
           flowing the next block up into the gap would pack tighter and read as
           misalignment rather than as data. */
        <div
          className="grid items-start gap-1.5"
          style={{
            gridTemplateColumns: `repeat(${columns.length}, ${CHIP_W + PAD * 2}px)`,
          }}
        >
          {columns.map((column, i) => (
            <div key={column[0]?.key ?? i} className="min-w-0 space-y-1.5">
              {column.flatMap((block) =>
                block.groups.map(([kind, list]) => (
                  <ServiceGroup key={kind} kind={kind} members={list} ctx={ctx} />
                )),
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * `L3` — the group's distance from the internet, in one glyph.
 *
 * On the group rather than on every chip: a group is one service in one role,
 * so every member shares the level, and repeating it per resource would spend
 * the diagram's scarcest resource - horizontal space in a chip - restating
 * something already true of the box around it.
 */
function ExposureMark({ level, className }: { level: number; className?: string }) {
  const spec = EXPOSURE[level];
  if (!spec) return null;
  return (
    <span
      title={`L${level} ${spec.name} — ${spec.why}`}
      className={cn(
        "shrink-0 rounded-sm border border-border px-1",
        "font-mono tabular-nums text-muted-foreground",
        className,
      )}
    >
      L{level}
    </span>
  );
}

/**
 * A service and how many of it there are. Not a list of chips.
 *
 * This used to draw five chips and a `+N` button, which made the canvas argue
 * with itself: the same estate rendered as 5 names here and 5 names there
 * while the counts underneath were 26 and 400, and every group was a different
 * height depending on how many of its members happened to fit.
 *
 * The names moved to the list panel, which is the thing built to hold them —
 * it filters, it scrolls, and it previews each row's detail beside it. What a
 * tile has to answer on the canvas is only "what runs here, and how much of
 * it", and that is one line whatever the count.
 *
 * Every tile is therefore the same height, which is what lets the packing
 * arithmetic in `layout-metrics.ts` be exact rather than approximate.
 */
function ServiceGroup({
  kind,
  members,
  ctx,
  tight,
}: {
  kind: string;
  members: SceneNode[];
  ctx: Ctx;
  tight?: boolean;
}) {
  const scale = tight ? TYPE_SCALE.borderStrip : TYPE_SCALE.inline;
  const groupHost = `group:${kind}:${members[0]!.key}`;
  const listOpen = ctx.inline?.host === groupHost;
  // A tile stands for every member, not just the first: carrying only
  // `members[0]` lit a group of 55 buckets when the relation happened to point
  // at bucket number one and left it dark for the other 54.
  const memberKeys = memberAttr(members);
  return (
    <button
      data-node={members[0]!.key}
      data-members={memberKeys}
      onClick={(e) =>
        ctx.openInline({
          host: groupHost,
          key: groupHost,
          label: kind,
          members,
          at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
        })
      }
      title={`${kind} · ${members.length}`}
      className={cn(
        "relative flex items-center gap-1.5 rounded border text-left transition-opacity",
        listOpen
          ? "border-solid border-primary ring-1 ring-primary/40"
          : "border-dashed border-border hover:border-solid hover:bg-row-hover",
        tight ? "px-1.5 py-1" : "px-2 py-1.5",
        scale.label,
      )}
      style={{ ...NEUTRAL_GROUP_BG, ...(tight ? {} : { width: CHIP_W + PAD * 2 }) }}
    >
      <Icon resourceKey={members[0]!.type} size={tight ? 11 : 13} />
      <span className="min-w-0 flex-1 truncate text-foreground">{kind}</span>
      {/* Exposure was a letter-and-number on every tile — a placement
          diagnostic the panel already states in words. It stays in the panel
          and off the canvas, where the question is only what runs here. */}
      <span className="mono shrink-0 tabular-nums text-muted-foreground">Qty {members.length}</span>
      <InlineHost hostKey={groupHost} ctx={ctx} />
    </button>
  );
}

/**
 * A container box.
 *
 * No layer badge. `L0`-`L4` said how deeply this box was nested, which the
 * nesting already says, and it collided head-on with the `L1`-`L4` that now
 * means distance from the internet. Two ladders both spelled L is worse than
 * either alone, so depth moved to the detail panel and L on the canvas means
 * exactly one thing.
 */

/**
 * Split a container's contents into cluster-owned runs and everything else.
 *
 * Unclaimed nodes come back as one run with no cluster, so the caller keeps a
 * single code path and the ordinary case costs nothing.
 */
/**
 * A fleet, drawn as the thing that owns it.
 *
 * Three instances in a subnet are three boxes; three instances an autoscaling
 * group created are ONE decision that happens to have produced three boxes,
 * and a diagram that cannot show the difference cannot show why the estate
 * looks the way it does.
 *
 * Dashed, because a cluster is not a network boundary. It owns its members and
 * decides how many there are, but traffic does not cross into it - solid would
 * put it in the same visual class as a VPC, which is the one thing it is not.
 *
 * It draws per container rather than as one box spanning them. A fleet whose
 * members sit in three zones IS three groups of instances that share an owner,
 * and repeating the labelled box in each zone says exactly that - while a
 * single box stretched across three stacked zones would have to cross the zone
 * boundaries to do it, claiming a containment that runs the wrong way.
 */
function ClusterBox({
  cluster,
  members,
  ctx,
}: {
  cluster: string;
  members: SceneNode[];
  ctx: Ctx;
}) {
  const owner = NODES[cluster];
  const zones = new Set(members.map((m) => PARENTS[m.key]?.key).filter(Boolean));
  /* Keyed by a MEMBER, not just by the fleet.
     A fleet whose instances sit in three zones draws three times — that is the
     point of the component — and a host key naming only the fleet made all
     three draw the same open list, so one click produced three stacked panels.
     The same disambiguation `ServiceGroup` already does for a service tile
     that repeats across containers. */
  const host = `cluster:${cluster}:${members[0]?.key ?? ""}`;
  const name = owner ? displayName(owner) : (cluster.split(":").pop() ?? "fleet");
  return (
    <div className={cn(NEUTRAL_BOX, "min-w-0 flex-1 basis-[240px] p-2")} style={NEUTRAL_BOX_BG}>
      <div className="relative mb-1.5 flex items-center gap-1.5">
        {owner ? <Icon resourceKey={owner.type} size={12} /> : null}
        {/* Its members first, its own panel second.
         *
         * This went straight to the autoscaling group's sheet, which skipped
         * the question a fleet is drawn to raise — which instances did it
         * make — and put the answer behind a scroll in a panel that covers the
         * canvas. The list names them, previews any one beside it, and its ⛶
         * is still the way to the group itself. */}
        <button
          onClick={(e) =>
            ctx.openInline({
              host,
              key: host,
              label: name,
              members,
              owner,
              at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
            })
          }
          title={`${name} · ${members.length}`}
          className={cn(
            "min-w-0 flex-1 truncate rounded px-1 text-left text-[11px] transition-colors",
            ctx.inline?.host === host ? "bg-row-selected" : "hover:bg-row-hover",
          )}
        >
          {name}
        </button>
        <span className="text-[10px] text-muted-foreground">{members.length}</span>
        <InlineHost hostKey={host} ctx={ctx} />
      </div>
      <div className="flex flex-wrap items-start gap-2">
        {[
          ...members
            .reduce((m, n) => {
              const kind = groupOf(n);
              return m.set(kind, [...(m.get(kind) ?? []), n]);
            }, new Map<string, SceneNode[]>())
            .entries(),
        ]
          .sort(byExposureThenSize)
          .map(([kind, list]) => (
            <div key={kind} className="min-w-0 flex-1">
              <ServiceGroup kind={kind} members={list} ctx={ctx} tight />
            </div>
          ))}
      </div>
      {zones.size > 1 && (
        <div className="mt-1 text-[10px] text-muted-foreground">
          also in {zones.size - 1} other zone{zones.size > 2 ? "s" : ""}
        </div>
      )}
    </div>
  );
}

/**
 * A rule drawn AS a box round what it governs.
 *
 * The convention every hand-drawn AWS diagram uses for a security group, and
 * the reason AWS ships one as a GROUP icon rather than a symbol. Dashed,
 * because a rule is a condition on the things inside it and not a boundary
 * they sit within — traffic does not cross into a security group.
 *
 * Rare by construction: the engine only marks a rule when its members are
 * contiguous and the box would be tighter than the rail the rule already
 * rides. A rule spanning three subnets stays a chip, because a box drawn round
 * members in three places would have to cross their borders to do it.
 */
function RuleWrap({ rule, members, ctx }: { rule: SceneNode; members: SceneNode[]; ctx: Ctx }) {
  /* Per drawing, not per rule — a rule wrapping members in two containers
     draws in both, and both would host the same list. See `ClusterBox`. */
  const host = `rule:${rule.key}:${members[0]?.key ?? ""}`;
  return (
    <div className={cn(NEUTRAL_BOX, "relative mb-2.5 p-2")} style={NEUTRAL_BOX_BG}>
      {/* What it protects, listed — then the rule itself through the ⛶. The
          same order as the fleet above it, because they are the same shape of
          object: a decision drawn round the things it decides. */}
      <button
        onClick={(e) =>
          ctx.openInline({
            host,
            key: host,
            label: displayName(rule),
            members,
            owner: rule,
            at: makeRoom(e.currentTarget, undefined, PANEL.list.w, PANEL.list.maxH),
          })
        }
        title={`${displayName(rule)} · protects ${members.length}`}
        className={cn(
          "mb-1.5 flex w-full items-center gap-1.5 rounded px-1 text-left transition-colors",
          ctx.inline?.host === host ? "bg-row-selected" : "hover:bg-row-hover",
        )}
      >
        <Icon resourceKey={rule.type} size={12} />
        <span className="min-w-0 flex-1 truncate text-[11px]">{displayName(rule)}</span>
        <span className="text-[10px] text-muted-foreground">protects {members.length}</span>
      </button>
      <InlineHost hostKey={host} ctx={ctx} />
      <div className="flex flex-wrap items-start gap-2">
        {[
          ...members
            .reduce((m, n) => {
              const kind = groupOf(n);
              return m.set(kind, [...(m.get(kind) ?? []), n]);
            }, new Map<string, SceneNode[]>())
            .entries(),
        ]
          .sort(byExposureThenSize)
          .map(([kind, list]) => (
            <div key={kind} className="min-w-0 flex-1">
              <ServiceGroup kind={kind} members={list} ctx={ctx} tight />
            </div>
          ))}
      </div>
    </div>
  );
}

function Box({
  label,
  id,
  sub,
  layer,
  className,
  edges,
  rail,
  railN,
  railW,
  railE,
  tone,
  count,
  listHost,
  ctx,
  onOpenList,
  children,
}: {
  label: string;
  id: string;
  sub?: string | undefined;
  layer: string;
  className?: string | undefined;
  edges?: { n?: boolean; s?: boolean };
  rail?: boolean;
  railN?: boolean;
  /** How many layers deep each side wall runs. 0 means the arm is empty. */
  railW?: number;
  railE?: number;
  tone?: React.CSSProperties | undefined;
  /** How much this container holds, at any depth — printed on the header. */
  count?: number | undefined;
  /** Identity of the list this header opens, so the header can show it is open. */
  listHost?: string | undefined;
  ctx?: Ctx | undefined;
  onOpenList?: ((e: React.MouseEvent<HTMLElement>) => void) | undefined;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        /* One gap, everywhere. A layer's border needs air on both sides of it:
           inside, so the child's own border does not sit on its parent's; and
           outside, so the tabs hanging off that child's edges have somewhere to
           be. At 12px a rail tab landed on the border of the box containing it,
           which is the difference between "attached to this" and "drawn over
           that". 16px is the smallest value where every arm clears. */
        "relative mb-4 rounded-md border border-border p-4 last:mb-0",
        edges?.n ? "mt-6" : "",
        edges?.s ? "mb-6" : "",
        className,
      )}
      /* Room for the tabs, computed rather than picked. A tab lies wholly
         outside the box it names, so the box reserves the space — and how much
         depends on how many layers that arm runs, which a fixed number cannot
         express. The old `ml-[64px]` was chosen when every wall was one layer
         deep; the west wall now runs two and needs 100px, so the fixed value
         overlapped by 36.

         MARGIN, not padding, and that is what makes nesting work: a child's
         tabs sit outside the child and inside the parent's content box, so the
         child's own reservation is what separates it from its parent's border.
         Nothing has to know how deep the tree goes. */
      style={{
        ...tone,
        marginLeft: railClearance("w", railW ?? 0) || undefined,
        marginRight: railClearance("e", railE ?? 0) || undefined,
        marginTop: railN ? railClearance("n", 1) : undefined,
        marginBottom: rail ? railClearance("s", 2) : undefined,
      }}
    >
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span className="label-caps">{label}</span>
        {/* The container's name IS its tab.
         *
         * Every other object on the canvas — a rail, a door, a service tile —
         * answers a click with its list, and a container answered with
         * nothing: an account, a VPC and a subnet were the only things a
         * reader could look at and not open. Same affordance, same list, same
         * preview beside it, and the ⛶ in the list's header is the way into
         * the container's own panel. */}
        {onOpenList && ctx && listHost ? (
          <span className="relative">
            <button
              onClick={onOpenList}
              title={`what is inside ${id}${count ? ` · ${count}` : ""}`}
              className={cn(
                "flex items-center gap-2 rounded border px-1.5 py-0.5 transition-colors",
                ctx.inline?.host === listHost
                  ? "border-primary bg-row-selected"
                  : "border-transparent hover:border-border hover:bg-row-hover",
              )}
            >
              <Mono className="text-foreground">{id}</Mono>
              {count ? (
                <span className="mono text-[10px] tabular-nums text-muted-foreground">{count}</span>
              ) : null}
            </button>
            <InlineHost hostKey={listHost} ctx={ctx} />
          </span>
        ) : (
          <Mono className="text-foreground">{id}</Mono>
        )}
        {sub ? <Mono className="text-muted-foreground">{sub}</Mono> : null}
      </div>
      {children}
    </div>
  );
}

/**
 * Curves from the hovered list row to the tiles it lights.
 *
 * Measured at hover, never at layout. The canvas has no coordinates — that is
 * the point of `layout-metrics.ts` — so the only way to draw between two boxes
 * is to ask the page where they ended up. Reading rectangles to paint an
 * overlay does not make the layout depend on the DOM, which is the rule that
 * matters.
 *
 * Recomputed on every hover rather than cached: the list is portalled and can
 * scroll or close between the hover and the paint, and a curve drawn from a
 * stale rectangle points at nothing. The reference this copies caches its rect
 * and then has to invalidate on scroll and mouse-leave; not caching is fewer
 * moving parts and the measurement is cheap.
 */
/**
 * How far a hover reaches, and the one place it is decided.
 *
 * `HoverLight` and `HoverTraces` both answer "what is this connected to" and
 * both said they used the same resolver the panel uses — while passing depth 1
 * against the panel's 2. So the lit set and the panel's Connections list
 * disagreed on every resource with a second hop: an instance's volume lit, the
 * key encrypting that volume did not, and the panel listed both.
 *
 * Two is not arbitrary and does not explode: `relatedTo` follows inbound edges
 * only at the first hop, so the second hop is what a resource DEPENDS ON —
 * `instance → volume → key` — and never "everything else sharing its security
 * group". Measured on the live graph, 19 assets reach depth 2 at all.
 */
const HOVER_DEPTH = 2;

/** One connection of the hovered resource: what it reaches, and how. */
type Connection = { key: string; direction: "out" | "in"; word: string };

/** Everything the hovered resource connects to, and the way each edge runs. */
function connectionsOf(key: string): Connection[] {
  return relatedTo(key, SCENE.tree, SCENE.relations ?? SCENE.edges ?? [], {
    maxDepth: HOVER_DEPTH,
    /* No roll-up. `GROUP_LIMIT` exists so a panel does not become a wall of
       356 rule rows — but lighting is not a display list, and capping it
       meant a security group's five slots all went to rules while the
       interfaces it actually protects stayed dark. */
    groupLimit: Number.MAX_SAFE_INTEGER,
  }).map((r) => ({ key: r.key, direction: r.direction, word: r.edgeType }));
}

/** Every key a hover should light: the resource, and all it connects to. */
function litKeysFor(key: string): string[] {
  return [key, ...connectionsOf(key).map((c) => c.key)];
}

/** A drawn curve, plus which source asked for it and whether it was pinned. */
type DrawnTrace = Trace & { source: string; pinned: boolean };

/**
 * Where a trace starts, whichever rung the reader is on.
 *
 * A hover starts from a LIST ROW, which is what `data-row` marks. A pin has to
 * outlive the list that made it — closing the list is the normal way to get a
 * clear look at the lines it drew — so it falls back to the resource's own
 * element on the canvas. Without the fallback, every pinned trace vanished the
 * moment its list closed, which is precisely when it becomes useful.
 */
function sourceEl(key: string): Element | null {
  const esc = CSS.escape(key);
  return (
    document.querySelector(`[data-row="${esc}"]`) ??
    document.querySelector(`[data-canvas] [data-node="${esc}"]`)
  );
}

function HoverTraces({
  hovered,
  pinned,
  onUnpin,
}: {
  hovered: string | null;
  pinned: readonly string[];
  onUnpin: (key: string) => void;
}) {
  const [paths, setPaths] = React.useState<DrawnTrace[]>([]);
  /* Bumped by anything that moves a rectangle without changing what is drawn.
     A hover trace never needed this — it lives for as long as the cursor is
     still — but a pinned one has to survive the reader scrolling to look at
     what it points at, which is the entire reason they pinned it. */
  const [tick, setTick] = React.useState(0);

  /* A stable string, so the effect below re-runs when the SET of pinned
     sources changes rather than on every render of the parent. `pinned` is a
     fresh array each time it comes off the preference document. */
  const pinnedKey = pinned.join("␟");

  React.useEffect(() => {
    const sources = [...new Set([...pinned, ...(hovered ? [hovered] : [])])];
    if (!sources.length) {
      setPaths([]);
      return;
    }
    const host = document.querySelector("[data-canvas]");
    if (!host) {
      setPaths([]);
      return;
    }
    /* VIEWPORT space, not canvas space.
     *
     * The overlay used to live inside `[data-canvas]` and travel with its
     * scroll, which meant every rect needed the scroll subtracted back out. It
     * now renders in a portal at the document root, because a child of the
     * canvas cannot paint above a panel: panels are portalled to `body`, so
     * they are in a different stacking context and win regardless of z-index.
     * A reader who pinned a line and then opened the panel about it watched the
     * line disappear behind the answer.
     *
     * Fixed positioning is the same coordinate system `getBoundingClientRect`
     * already answers in, so the scroll term simply goes away — and the price,
     * re-measuring when the canvas scrolls, is a listener that was already
     * needed for pinned traces. */
    const vis = (r: DOMRect): Rect => ({ x: r.left, y: r.top, w: r.width, h: r.height });

    /* Measured ONCE for all sources rather than once per source. With a hover
       and five pins live, the per-source version read every `data-node` on the
       canvas six times — a thousand-odd `getBoundingClientRect` calls per
       scroll frame, each one a forced layout. */
    const els = [...document.querySelectorAll("[data-canvas] [data-node]")].map((el) => ({
      key: el.getAttribute("data-node") ?? "",
      members: (el.getAttribute("data-members") ?? "").split(" "),
      rect: vis(el.getBoundingClientRect()),
    }));

    const drawn: DrawnTrace[] = [];
    for (const source of sources) {
      const el = sourceEl(source);
      if (!el) continue;
      const from = vis(el.getBoundingClientRect());

      // The lit set is DERIVED, not read back off the page. Reading
      // `getComputedStyle(...).opacity` raced `HoverLight`: both run on the same
      // state change, and the traces measured before the stylesheet applied — so
      // every tile still read as opacity 1 and the curves fanned out to 22
      // targets, most of them dimmed a frame later.
      const lit = new Map(connectionsOf(source).map((c) => [c.key, c]));
      const targets: Array<{ key: string; rect: Rect; direction: "out" | "in"; label: string }> =
        [];
      for (const node of els) {
        /* EVERY connection this element stands for, not the first one found.
         *
         * One border tab carries four interfaces and a service tile carries
         * fifty-five buckets, so a security group protecting all four drew a
         * single unlabelled line — indistinguishable from protecting one. The
         * count is the answer to "how much of this does that thing govern", and
         * it was the part being thrown away. */
        const hits = [...new Set([node.key, ...node.members])]
          .map((k) => lit.get(k))
          .filter((c): c is Connection => !!c);
        if (!hits.length) continue;
        /* One arrowhead per element, so mixed directions have to resolve to one.
           The commonest wins: a tab of four interfaces protected by one group is
           four edges of one kind, and a genuinely mixed tab is rare enough that
           naming the majority beats naming none. */
        const tally = new Map<string, number>();
        for (const h of hits) tally.set(h.word, (tally.get(h.word) ?? 0) + 1);
        const word = [...tally.entries()].sort((a, b) => b[1] - a[1])[0]![0];
        const lead = hits.find((h) => h.word === word)!;
        targets.push({
          key: node.key,
          rect: node.rect,
          direction: lead.direction,
          label: hits.length > 1 ? `${word} ×${hits.length}` : word,
        });
      }
      const isPinned = pinned.includes(source);
      for (const t of tracesFrom(from, targets)) {
        /* Namespaced by source. Two pinned resources reaching the same KMS key
           are two different lines that happen to end in the same place, and a
           bare target key made them one — React kept the first and the second
           silently never drew. */
        drawn.push({ ...t, key: `${source}␟${t.key}`, source, pinned: isPinned });
      }
    }
    setPaths(drawn);
    // `tick` is a measurement trigger, not an input — see the listener below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hovered, pinnedKey, tick]);

  /* Re-measure whenever ANYTHING is drawn. This used to run only for pinned
     traces, on the reasoning that a hover is too transient for the rectangles
     to move underneath it — true while the overlay scrolled with the diagram,
     and false now that it is fixed to the viewport. A hover line would other-
     wise stay where it was drawn while the estate slid out from under it.
     `passive` because this never prevents the scroll it is watching. */
  const anyDrawn = pinned.length > 0 || !!hovered;
  React.useEffect(() => {
    if (!anyDrawn) return;
    const host = document.querySelector("[data-canvas]");
    if (!host) return;
    let frame = 0;
    const bump = () => {
      // Coalesced to one measurement per frame: scroll fires far faster than
      // the layout it is reporting on can meaningfully change.
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setTick((t) => t + 1);
      });
    };
    host.addEventListener("scroll", bump, { passive: true });
    window.addEventListener("resize", bump, { passive: true });
    const ro = new ResizeObserver(bump);
    ro.observe(host);
    return () => {
      host.removeEventListener("scroll", bump);
      window.removeEventListener("resize", bump);
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [anyDrawn]);

  if (!paths.length) return null;
  return (
    <Floating>
      <svg
        /* z-45: above the floating panels at z-40, below the modal sheet's
           scrim at z-50. A connection line belongs over the panel that is
           covering the thing it points at; it does not belong over a modal. */
        className="pointer-events-none fixed inset-0 z-[45] size-full overflow-visible"
      >
        <defs>
          {/* Two markers, because an arrow's head belongs at the OBJECT end and
            the object is not always the far end of the curve. `auto-start-reverse`
            is what lets one shape serve both without a mirrored copy. */}
          <marker
            id="trace-head"
            viewBox="0 0 8 8"
            refX={7}
            refY={4}
            markerWidth={6}
            markerHeight={6}
            orient="auto"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--color-primary)" />
          </marker>
          <marker
            id="trace-head-start"
            viewBox="0 0 8 8"
            refX={7}
            refY={4}
            markerWidth={6}
            markerHeight={6}
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--color-primary)" />
          </marker>
        </defs>
        {paths.map((p) => (
          <React.Fragment key={p.key}>
            {/* A pinned line is CALMER than a hovered one, not louder.
              "What I asked to keep" and "what I am pointing at right now" are
              two different statements, and with both drawn in the same dashed
              accent a reader could not tell which lines were answering the
              cursor. Solid and quieter reads as settled; dashed and bright
              reads as live. */}
            {p.pinned && (
              /* A fat transparent copy under the visible stroke, so unpinning is
               a click at a line rather than a click at 1.5 pixels. The visible
               path stays thin; only the target grows. */
              <path
                d={p.d}
                fill="none"
                stroke="transparent"
                strokeWidth={12}
                className="pointer-events-auto cursor-pointer"
                onClick={() => onUnpin(p.source)}
              >
                <title>unpin these connections</title>
              </path>
            )}
            <path
              d={p.d}
              fill="none"
              stroke="var(--color-primary)"
              strokeWidth={1.5}
              strokeOpacity={p.pinned ? 0.55 : 0.8}
              strokeDasharray={p.pinned ? undefined : "5 4"}
              markerEnd={p.head === "end" ? "url(#trace-head)" : undefined}
              markerStart={p.head === "start" ? "url(#trace-head-start)" : undefined}
            />
            {/* The relationship, named on the line.
             *
             * An arrowhead alone says a direction and nothing about what runs
             * along it — and on this map most edges are governance, not traffic,
             * so a bare arrow from a server to a security group reads as a
             * packet going somewhere it never goes. The word is what stops that.
             *
             * `paintOrder: stroke` draws a halo of the page's own background
             * under the glyphs, so a label stays readable where it crosses a
             * container border or another line. A rect behind it would need
             * measuring; this needs nothing. */}
            {p.label ? (
              <text
                x={p.mid.x}
                y={p.mid.y}
                textAnchor="middle"
                dominantBaseline="middle"
                className="mono"
                fontSize={9}
                fill="var(--color-primary)"
                stroke="var(--color-surface)"
                strokeWidth={3}
                paintOrder="stroke"
              >
                {p.label}
              </text>
            ) : null}
          </React.Fragment>
        ))}
      </svg>
    </Floating>
  );
}

/**
 * Light the hovered resource and its relations; fade the rest.
 *
 * One <style> element rather than per-chip state. The estate draws 1,030
 * chips, and threading a `hovered` prop through all of them would re-render
 * the whole canvas on every mouse move — for an effect that is pure
 * presentation and touches no layout.
 *
 * Chips carry a static `data-node` written once at render. This flips one
 * attribute on the canvas root and swaps one stylesheet, so the cost of a
 * hover is independent of how large the estate is.
 */
function HoverLight({ hovered, pinned }: { hovered: string | null; pinned: readonly string[] }) {
  const pinnedKey = pinned.join("␟");
  /* A pinned line's two ends are never dimmed.
   *
   * Without this, hovering anything while a trace was pinned faded the boxes
   * that trace pointed AT — so the line stayed drawn at full strength across a
   * canvas where both its endpoints had gone to 20%, and read as pointing at
   * nothing. The reader's conclusion is that pinning is broken, when what is
   * broken is that two features each had a correct opinion about opacity and
   * neither knew about the other.
   *
   * Same resolver as the traces and the panel, so the three cannot disagree
   * about what a resource is connected to. */
  const lit = React.useMemo(() => {
    const keys = new Set<string>();
    for (const source of [...(hovered ? [hovered] : []), ...pinned]) {
      for (const k of litKeysFor(source)) keys.add(k);
    }
    return [...keys];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hovered, pinnedKey]);

  // Nothing to dim against: with no hover, pinned endpoints are simply the
  // canvas as it always looks.
  if (!hovered) return null;
  const esc = (k: string) => k.replace(/["\\]/g, "\\$&");
  return (
    <style>
      {`[data-canvas] [data-node]{opacity:.2;transition:opacity .12s}` +
        lit
          .map(
            (k) =>
              `[data-canvas] [data-node="${esc(k)}"],` +
              `[data-canvas] [data-members~="${esc(k)}"]{opacity:1}`,
          )
          .join("")}
    </style>
  );
}

/** Rows one list paints before the filter has to do the narrowing. */
const LIST_CAP = 250;

/**
 * Everything inside a container, at any depth.
 *
 * The canvas DRAWS a container's contents, which is why a box was the one
 * object on the page with no list: the drawing was supposed to be the answer.
 * It is not — the drawing collapses 55 buckets into a tile reading `Qty 55`,
 * hides anything a filter switched off, and cannot be searched. A container
 * now answers "what is in here" the same way a rail tab does.
 *
 * Unfiltered on purpose, and this is the one place the list and the picture
 * disagree. The overlay switches decide what the DIAGRAM shows — identity and
 * encryption are off by default because 326 bindings drawn at once is not a
 * diagram — but they are still inside the account whether or not they are
 * drawn, and a list that hid them would be answering a different question than
 * the one its heading asks.
 *
 * Containers lead, because a list of an account that opens with 900 leaves has
 * buried the four boxes that give them their shape.
 */
function descendantsOf(node: SceneNode): SceneNode[] {
  const out: SceneNode[] = [];
  const walk = (n: SceneNode) => {
    for (const c of n.children ?? []) {
      out.push(c);
      walk(c);
    }
  };
  walk(node);
  return out.sort(
    (a, b) =>
      Number(isContainer(b)) - Number(isContainer(a)) ||
      (a.position?.rank ?? 999) - (b.position?.rank ?? 999) ||
      a.type.localeCompare(b.type) ||
      (a.name || a.id).localeCompare(b.name || b.id),
  );
}

/**
 * Level one: the resources behind a tab or a group heading, over the box.
 *
 * Overlaid on the container it came from — `absolute inset-0` inside the box
 * the tab rides — rather than docked beside it. That is a deliberate
 * simplification of the pattern this copies: docking beside needs the box's
 * coordinates, and this diagram has none. Covering the box needs no
 * measurement at all, because the overlay IS a child of the thing it covers.
 *
 * Hovering a row lights that resource and its relations everywhere else on the
 * canvas; clicking one opens its panel.
 */
function InlineList({
  label,
  members,
  owner,
  ctx,
  onClose,
  side,
  at,
  pinnedAs,
}: {
  label: string;
  members: SceneNode[];
  /** The resource this list belongs to, when the list has one. */
  owner?: SceneNode | undefined;
  ctx: Ctx;
  onClose: () => void;
  side?: Side | undefined;
  at?: Anchor | undefined;
  /** Set when this list IS a pinned one, rather than the transient rung. */
  pinnedAs?: PanelPref | undefined;
}) {
  const [q, setQ] = React.useState("");
  /* Hovering a row TRACES it; opening it is a click.
   *
   * The preview used to follow the cursor down the list, which meant reading
   * the list at all threw a 360px panel over the canvas — over the very
   * connection lines the same hover had just drawn. Hover and click now answer
   * two different questions: where does this reach, and what is it. */
  const [preview, setPreview] = React.useState<SceneNode | null>(null);
  const shown = q
    ? members.filter((n) => `${n.name ?? ""} ${n.id}`.toLowerCase().includes(q.toLowerCase()))
    : members;
  /* Every list is now openable from every object, and an account's is 1,030
     rows long — a thousand buttons is a scroll bar with no bottom and a paint
     the browser feels. The cap is stated in the footer rather than applied
     quietly, because a list that silently stops at 250 reads as "that is all
     there is", which is the one thing it must not say. The filter is the way
     past it, which is why the box appears well below this number. */
  const rows = shown.slice(0, LIST_CAP);
  const head = members[0] ?? owner;
  /* Keyed by the LIST, not by the resource it happens to be showing. A rail
     tab's list and its owner's detail panel are two different things a reader
     positions independently, and sharing a key would make moving one move the
     other next time it opened. */
  const subject = `list:${ctx.inline?.key ?? label}`;
  const [listRef, listStyle, listAt] = useAnchored(
    at,
    PANEL.list.w,
    PANEL.list.maxH,
    side,
    ctx.places[subject],
  );
  const [drag, dragHandlers] = useDraggable(
    (dropped) => ctx.place(subject, dropped, { w: listAt.w, h: listAt.h }),
    listAt,
  );
  return (
    <Floating>
      <div
        ref={listRef}
        className="fixed z-40 flex flex-col overflow-hidden rounded-lg
                 border border-primary/40 bg-surface shadow-xl"
        /* Size from the metrics, position from the placer — the two numbers
           that used to be written here are the same two the placer needs, and
           a panel measured one way and placed another lands beside nothing. */
        style={{
          ...listStyle,
          width: PANEL.list.w,
          maxHeight: `min(70vh, ${PANEL.list.maxH}px)`,
          ...(drag ? { transform: `translate(${drag.dx}px, ${drag.dy}px)` } : {}),
        }}
        onMouseLeave={() => ctx.onHover(null)}
        /* A portal moves the DOM but NOT the React tree, so every click in here
         still bubbles to the tab this list is rendered inside — which re-opened
         the list the instant the X closed it. Stopping here is what makes the
         close button, and every row, behave like what they look like. */
        onClick={(e) => e.stopPropagation()}
      >
        <div
          {...dragHandlers}
          className="flex shrink-0 cursor-grab select-none items-center gap-1.5 border-b
                     border-border px-2.5 py-1.5 active:cursor-grabbing"
        >
          {head ? <Icon resourceKey={head.type} size={12} /> : null}
          <span className="min-w-0 flex-1 truncate text-[11px] font-semibold">{label}</span>
          <span className="mono text-[10px] text-muted-foreground">{members.length}</span>
          {/* The container's OWN panel, from the list it opened. A fleet, a
              rule and an account are resources as much as the things they
              hold, and this is the one door to their detail. */}
          {owner ? (
            <button
              onClick={() => ctx.onSelect(owner)}
              title={`open the full panel for ${displayName(owner)}`}
              aria-label={`open the full panel for ${displayName(owner)}`}
              className="rounded border border-border px-1 text-[11px] leading-none
                       text-muted-foreground hover:bg-row-hover hover:text-foreground"
            >
              ⛶
            </button>
          ) : null}
          <PinToggle
            ctx={ctx}
            panel={
              pinnedAs ?? {
                kind: "list",
                subject,
                label,
                /* The members are captured at PIN time, because that is what
                   the reader pinned — this list, holding these. Recomputing
                   them on restore would need to know which of a dozen kinds of
                   tab opened it, which the host key does not say. */
                members: members.map((n) => n.key),
              }
            }
          />
          <button
            onClick={onClose}
            aria-label={pinnedAs ? "unpin and close list" : "close list"}
            className="rounded px-1 text-muted-foreground hover:bg-row-hover hover:text-foreground"
          >
            ✕
          </button>
        </div>

        {members.length > 12 && (
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="filter…"
            className="mono shrink-0 border-b border-border bg-transparent px-2.5 py-1
                     text-[11px] outline-none placeholder:text-muted-foreground"
          />
        )}

        <div className="min-h-0 flex-1 overflow-y-auto" onScroll={() => ctx.onHover(null)}>
          {rows.map((n) => (
            <button
              key={n.key}
              onMouseEnter={() => ctx.onHover(n.key)}
              onFocus={() => ctx.onHover(n.key)}
              // Clicking the open row closes it, so a row is its own toggle —
              // the same rule the tabs and headings follow.
              onClick={() => setPreview((cur) => (cur?.key === n.key ? null : n))}
              data-row={n.key}
              className={cn(
                "flex w-full items-center gap-1.5 px-2.5 py-1 text-left hover:bg-row-hover",
                preview?.key === n.key ? "bg-row-selected" : "",
              )}
            >
              <Icon resourceKey={n.type} size={11} />
              <span className="mono min-w-0 flex-1 truncate text-[11px]">{displayName(n)}</span>
              {ctx.ann.selfCode[n.key] ? (
                <Badge className="mono !text-[9px]">{ctx.ann.selfCode[n.key]}</Badge>
              ) : null}
            </button>
          ))}
          {!shown.length && (
            <p className="px-2.5 py-2 text-[11px] text-muted-foreground">nothing matches.</p>
          )}
        </div>

        <div className="shrink-0 border-t border-border px-2.5 py-1 text-[10px] text-muted-foreground">
          {shown.length > rows.length
            ? `showing ${rows.length} of ${shown.length} — filter to narrow`
            : "hover to trace · click to open"}
        </div>

        {preview && (
          /* Beside the LIST, not beside the tab, and on the side the list is
             already travelling. A west wall's list sits left of the arm, so its
             preview goes further left; anything else reads left to right. */
          <NodePreview
            node={preview}
            at={listAt}
            side={side === "w" ? "w" : "e"}
            ctx={ctx}
            onClose={() => setPreview(null)}
            onOpen={ctx.onSelect}
          />
        )}
      </div>
    </Floating>
  );
}

/**
 * The detail, beside the list rather than over the canvas.
 *
 * Reading a list and reading one row's detail is one motion, so the two sit
 * side by side: the list keeps its place and the cursor never leaves it. The
 * full sheet is still there for a resource picked off the canvas — this is the
 * same body, docked to the list that produced it.
 */
function NodePreview({
  node,
  at,
  side,
  onClose,
  onOpen,
  ctx,
}: {
  node: SceneNode;
  at?: Anchor | undefined;
  /** Which way to open. A list's preview clears the list by sitting beside it;
      one opened straight off a chip has nothing to clear and opens ON it. */
  side?: Side | undefined;
  onClose: () => void;
  onOpen: (n: SceneNode) => void;
  /** Lets the preview pin its subject's connection lines. Absent on rungs that
      have no canvas behind them to draw on. */
  ctx?: Ctx | undefined;
}) {
  const subject = `detail:${node.key}`;
  const [boxRef, boxStyle, boxAt] = useAnchored(
    at,
    PANEL.detail.w,
    PANEL.detail.maxH,
    side,
    ctx?.places[subject],
  );
  const pinned = ctx?.pinnedTraces.includes(node.key) ?? false;
  const [drag, dragHandlers] = useDraggable(
    (dropped) => ctx?.place(subject, dropped, { w: boxAt.w, h: boxAt.h }),
    boxAt,
  );
  return (
    <Floating>
      <div
        ref={boxRef}
        className="fixed z-40 flex flex-col overflow-hidden rounded-lg
                 border border-border bg-surface shadow-xl"
        // Beside the list when one opened it, over the chip when one did not —
        // unless the reader has moved it, in which case where they put it.
        style={{
          ...boxStyle,
          width: PANEL.detail.w,
          maxHeight: `min(80vh, ${PANEL.detail.maxH}px)`,
          ...(drag ? { transform: `translate(${drag.dx}px, ${drag.dy}px)` } : {}),
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          {...(ctx ? dragHandlers : {})}
          className={cn(
            "flex shrink-0 items-center gap-1.5 border-b border-border px-2.5 py-1.5",
            ctx && "cursor-grab active:cursor-grabbing select-none",
          )}
        >
          <Icon resourceKey={node.type} size={12} />
          {/* The name is the locate control. A parked panel and the resource it
              names can end up a long way apart, and this is the only thing on
              screen that knows they belong together. */}
          <button
            onClick={() => locateOnCanvas(node.key)}
            title={`scroll the diagram to ${displayName(node)}`}
            className="min-w-0 flex-1 text-left"
          >
            <Mono truncate className="text-[11px] font-semibold hover:underline">
              {displayName(node)}
            </Mono>
          </button>
          {/* Pin from HERE, because this is the rung where a reader has just
              decided a resource matters. A hover already draws the lines; the
              pin is only the decision to keep them while looking at something
              else, so it belongs beside the thing being looked at rather than
              on a toolbar above the canvas. */}
          {ctx ? <PinToggle ctx={ctx} panel={{ kind: "detail", subject: node.key }} /> : null}
          {ctx ? (
            <button
              onClick={() => ctx.togglePinnedTrace(node.key)}
              title={
                pinned
                  ? "stop keeping this resource's connection lines drawn"
                  : "keep this resource's connection lines drawn"
              }
              aria-label={pinned ? "unpin connections" : "pin connections"}
              aria-pressed={pinned}
              className={cn(
                "rounded border px-1 text-[11px] leading-none",
                pinned
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-row-hover hover:text-foreground",
              )}
            >
              ⚯
            </button>
          ) : null}
          <button
            onClick={() => onOpen(node)}
            title="open the full panel"
            aria-label="open the full panel"
            className="rounded border border-border px-1 text-[11px] leading-none
                     text-muted-foreground hover:bg-row-hover hover:text-foreground"
          >
            ⛶
          </button>
          <button
            onClick={onClose}
            aria-label="close preview"
            className="rounded px-1 text-muted-foreground hover:bg-row-hover hover:text-foreground"
          >
            ✕
          </button>
        </div>
        {/* What it is and how it stands, on the rung below the sheet as well
            as on it. The preview used to name the resource and nothing else,
            so state, region and account only existed one click further in. */}
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-border px-2.5 py-1.5">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
            {node.type}
          </span>
          <HeaderChips node={node} />
        </div>
        {/* Literally the sheet's body, not a shortened copy of it.
         *
         * This claimed to be "the same body" while rendering three of the
         * sheet's seven sections: a security group previewed with no rules, an
         * autoscaling group with no members, and nothing anywhere showed its
         * scope path or its tags. One component now serves both rungs, so a
         * section added to the panel cannot go missing from the preview. */}
        <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
          <NodeBody node={node} onOpen={onOpen} compact />
        </div>
      </div>
    </Floating>
  );
}

/**
 * Render at the document root, escaping the transformed subtree.
 *
 * The rail tabs sit in containers with `translate-y-full`, and a `transform`
 * ancestor makes `position: fixed` resolve against THAT box rather than the
 * viewport — so a list anchored at the tab's measured point landed at roughly
 * double its coordinates. A portal is the only way out: the measurement was
 * always right, the containing block was not.
 */
function Floating({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);
  React.useEffect(() => setReady(true), []);
  if (!ready || typeof document === "undefined") return null;
  return createPortal(children, document.body);
}

/** The window, as the pure placer wants it. */
const viewport = (): Size =>
  typeof window === "undefined"
    ? { w: MIN_VIEWPORT.w, h: MIN_VIEWPORT.h }
    : { w: window.innerWidth, h: window.innerHeight };

/** `placePanel`, with the window filled in. The rule itself is in the metrics. */
function place(at: Anchor | undefined, w: number, h: number, side?: Side): React.CSSProperties {
  if (typeof window === "undefined" || !at) return { left: 24, top: 88 };
  return placePanel(at, { w, h }, side, viewport());
}

/**
 * Anchor a floating panel to a point, clamped by what it MEASURES rather than
 * by what it might grow to.
 *
 * `place` was clamping every list against its 460px maximum, so a list of two
 * rows — 103px tall — opened near the foot of the page was shoved 170px up to
 * make room for 357px it was never going to use. The panel then sat nowhere
 * near the tile that opened it, which is the one thing the anchor exists to
 * guarantee. Measuring after mount costs one extra paint and only ever moves
 * the panel back DOWN toward its anchor.
 *
 * Layout effect, so the correction lands before the browser paints and the
 * panel does not visibly jump. `Floating` renders nothing until it is on the
 * client, but this hook lives in the component ABOVE that gate — hence the
 * isomorphic pick rather than an unconditional `useLayoutEffect`, which would
 * warn on every server render of the page.
 *
 * A callback ref in STATE, not `useRef`, and that is the whole reason this
 * works. `Floating` mounts nothing on its first pass and only portals the
 * panel after its own `ready` flips — a commit this component takes no part
 * in. A `useRef` was therefore still null when the only layout effect ran, and
 * nothing ever re-ran it: every list kept the 460px fallback and landed 250px
 * off its anchor while appearing to measure itself. Holding the node in state
 * makes mounting the panel a render of this hook's owner, which is what gives
 * the measurement something to measure.
 */
const useIsoLayoutEffect = typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

function useAnchored(
  at: Anchor | undefined,
  w: number,
  maxH: number,
  side?: Side,
  /** A position the reader chose for this subject, which overrules the anchor. */
  saved?: Placement | undefined,
) {
  const [el, setEl] = React.useState<HTMLDivElement | null>(null);
  const [h, setH] = React.useState(maxH);
  /* No dependency array on purpose: the panel's height changes with its
     CONTENT — filtering a list shortens it, a preview's config block arrives
     when the API answers — and every one of those is a render of this owner.
     The equality guard is what stops it looping; one `offsetHeight` read per
     render of one small element is not worth a dependency list that would have
     to name every input to the height. */
  useIsoLayoutEffect(() => {
    if (el && el.offsetHeight && el.offsetHeight !== h) setH(el.offsetHeight);
  });
  /* A saved placement WINS over the anchor, and that is the whole point of
     saving one: a reader who moved this panel out of the way has said, in the
     only way the interface offers, that they do not want it back over the thing
     that opened it. Resolved against the CURRENT window, so a position stored
     on one screen lands somewhere reachable on another. */
  const style = saved ? fromPlacement(saved, { w, h }, viewport()) : place(at, w, h, side);
  return [
    (node: HTMLDivElement | null) => {
      setEl(node);
    },
    style,
    /* Where it actually landed, so a panel docked to THIS one can be placed
       against the result rather than against the anchor. A preview beside a
       west-wall list has to clear the list, and the list is not where the tab
       was — it is 296px to the left of it. */
    { x: Number(style.left) || 0, y: Number(style.top) || 0, w, h },
  ] as const;
}

/**
 * Drag a panel by its header, and report where it was let go.
 *
 * Pointer events rather than HTML5 drag-and-drop: a drag image is exactly what
 * this must not have — the panel itself moves, live, and the reader is aiming
 * it at a gap in a diagram they can see. `setPointerCapture` is what keeps the
 * gesture alive when the cursor outruns the header, which at speed it does.
 *
 * The offset is held in state and applied on TOP of the resolved position, so
 * nothing about anchoring or clamping has to know a drag is happening. On
 * release the total is converted to a corner-and-offset and handed up; the
 * offset then resets, because the saved placement now carries it.
 */
function useDraggable(
  onDrop: (at: { left: number; top: number }) => void,
  base: { x: number; y: number },
) {
  const [drag, setDrag] = React.useState<{ dx: number; dy: number } | null>(null);
  const from = React.useRef<{ x: number; y: number } | null>(null);

  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      // Left button only, and never from a control inside the header — the
      // close and pin buttons live there and must stay clickable.
      if (e.button !== 0 || (e.target as HTMLElement).closest("button,input")) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      from.current = { x: e.clientX, y: e.clientY };
      setDrag({ dx: 0, dy: 0 });
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      if (!from.current) return;
      setDrag({ dx: e.clientX - from.current.x, dy: e.clientY - from.current.y });
    },
    onPointerUp: (e: React.PointerEvent<HTMLElement>) => {
      if (!from.current) return;
      const dx = e.clientX - from.current.x;
      const dy = e.clientY - from.current.y;
      from.current = null;
      setDrag(null);
      /* A click is a drag of zero, and a reader clicking a header expects
         nothing to happen — saving a placement identical to the anchor would
         pin the panel in place and light the unsaved indicator for it. */
      if (Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
      onDrop({ left: base.x + dx, top: base.y + dy });
    },
  };
  return [drag, handlers] as const;
}

/**
 * Where a list should open: the viewport point of the thing that was clicked.
 *
 * Measured at CLICK, not at layout — the distinction the layout rules draw.
 * Positioning by CSS alone could not clamp: a tab on a south border opened its
 * list below the fold, and one near the top of the canvas was clipped by the
 * canvas's own `overflow-auto`. A fixed overlay placed from this point is
 * always on screen and always over what was clicked.
 *
 * The element's own top-left, not the point beneath it. Anchoring to `bottom`
 * dropped every list a tile-height south of its tile, so the reader clicked
 * one thing and the answer appeared next to a different one — and on a
 * 150px-tall rail tab the gap was the length of the whole tab.
 */
/** The rectangle a panel opens from — the thing that was clicked. */
type Anchor = { x: number; y: number; w: number; h: number };

/**
 * Scroll the diagram so the panel has somewhere to go, then say where the
 * thing that was clicked ended up.
 *
 * The account's own walls ride the outermost box, so on a full-width estate
 * they sit hard against the edge of the window: an east tab at x=1612 has 68px
 * to its right and needs 296. Clamping put the panel back over the tab — the
 * one place the reader is looking — and no arrangement of the panel could fix
 * that, because the room genuinely was not there.
 *
 * The canvas already scrolls, so take the room from the scroller rather than
 * from the anchor. Scrolling moves the tab too, which is why this returns the
 * adjusted rect: the caller measured before the scroll and would otherwise
 * open the panel against a position the tab has since left.
 *
 * Never more than the scroller actually has. A canvas already at its end
 * simply cannot make room, and the viewport clamp remains the last resort.
 */
const GUTTER = ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"] as const;

const canvasEl = () =>
  typeof document === "undefined" ? null : document.querySelector<HTMLElement>("[data-canvas]");
const canvasInner = () =>
  typeof document === "undefined"
    ? null
    : document.querySelector<HTMLElement>("[data-canvas-inner]");

/**
 * Give the diagram back the room it lent.
 *
 * Cleared on every open and on every close, so a gutter never outlives the
 * panel that needed it — otherwise closing a list would leave the estate
 * sitting 300px off-centre with nothing on screen to explain why.
 */
function clearRoom() {
  const inner = canvasInner();
  if (!inner) return;
  for (const side of GUTTER) inner.style[side] = "";
  inner.style.width = "";
  inner.style.boxSizing = "";
}

/** An element's viewport rectangle. */
const rectOf = (el: HTMLElement): Anchor => {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
};

/**
 * Scroll the diagram so the panel has somewhere to go, and say where the thing
 * that was clicked ended up.
 *
 * The account's own walls ride the outermost box, so on a full-width estate
 * they sit hard against the edge of the window: an east tab at x=1612 has 68px
 * to its right and needs 296. Clamping put the panel back over the tab — the
 * one place the reader is looking — and no arrangement of the panel could fix
 * it, because the room genuinely was not there.
 *
 * Two sources of room, in order. The canvas already scrolls, so take it from
 * the scroller first. Where the scroller has none — and on the outermost walls
 * it never does, because that box IS the end of the content — the diagram
 * lends it as a temporary gutter, which lengthens the scroller, which the
 * scroll then uses.
 *
 * It returns a FRESH measurement rather than the arithmetic of what it did.
 * Lending on a left or top edge shifts the content immediately, scrolling
 * shifts it again, and a caller that trusted a computed offset would open the
 * panel against a position the tab had already left twice over.
 */
function makeRoom(el: HTMLElement, side: Side | undefined, w: number, h: number): Anchor {
  const host = canvasEl();
  const inner = canvasInner();
  if (!host) return rectOf(el);
  clearRoom();

  const at = rectOf(el);
  const pad = VIEWPORT_PAD;
  const gap = PANEL_GAP;
  let dx = 0;
  let dy = 0;

  // How far past the window the panel would land, and which way to give.
  if (side === "e") dx = at.x + at.w + gap + w + pad - window.innerWidth;
  else if (side === "w") dx = -(pad - (at.x - gap - w));
  else if (side === "s") dy = at.y + at.h + gap + h + pad - window.innerHeight;
  else if (side === "n") dy = -(pad - (at.y - gap - h));
  else {
    // Opened ON the thing: it still has to fit down and to the right of it.
    dx = at.x + w + pad - window.innerWidth;
    dy = at.y + h + pad - window.innerHeight;
  }

  /* Room is added OUTSIDE the diagram's own box, never taken from inside it.
   *
   * The wrapper is a plain block, so it is as wide as the canvas and padding
   * on it would eat into that width — squeezing every box in the estate to
   * make space beside it, which is a re-layout, not a gutter. Pinning the
   * width to what it already measures and switching to `content-box` makes the
   * padding add to the outside instead: the diagram keeps the exact geometry
   * it had, and the scroller gets longer by precisely the shortfall.
   *
   * Nothing is pinned until something is actually short, so a canvas with room
   * to spare is never touched at all. */
  const lend = (prop: (typeof GUTTER)[number], need: number, have: number) => {
    const short = need - have;
    if (!inner || short <= 0) return;
    if (!inner.style.width) {
      inner.style.boxSizing = "content-box";
      inner.style.width = `${inner.offsetWidth}px`;
    }
    inner.style[prop] = `${Math.ceil(short)}px`;
  };
  if (dx > 0) lend("paddingRight", dx, host.scrollWidth - host.clientWidth - host.scrollLeft);
  else if (dx < 0) lend("paddingLeft", -dx, host.scrollLeft);
  if (dy > 0) lend("paddingBottom", dy, host.scrollHeight - host.clientHeight - host.scrollTop);
  else if (dy < 0) lend("paddingTop", -dy, host.scrollTop);

  host.scrollLeft += dx;
  host.scrollTop += dy;
  return rectOf(el);
}

/** A rail tab's anchor: measured, then given room on the side it opens. */
const railAnchor = (e: React.MouseEvent<HTMLElement>, side: Side) =>
  makeRoom(e.currentTarget, side, PANEL.list.w, PANEL.list.maxH);

/**
 * A tab and the list it opens, anchored together.
 *
 * The list used to be hosted by the BOX the tab rides, which put it at that
 * box's far edge — a security-group tab on a VPC's south border opened a list
 * against the VPC's right wall, a long way from the thing that was clicked.
 * Anchoring to the tab is what makes it open where the reader is looking.
 */
function TabHost({
  hostKey,
  ctx,
  children,
}: {
  hostKey: string;
  ctx: Ctx;
  children: React.ReactNode;
}) {
  return (
    <span className="relative shrink-0">
      {children}
      <InlineHost hostKey={hostKey} ctx={ctx} />
    </span>
  );
}

/**
 * The pin toggle, on whichever panel header carries it.
 *
 * One control for both rungs, because pinning means the same thing on each:
 * this panel stops obeying the one-at-a-time rule and stays until dismissed.
 * Two separately-written toggles would eventually disagree about what pinned
 * looks like, which is how a reader learns that two things are different when
 * they are not.
 */
function PinToggle({ ctx, panel }: { ctx: Ctx; panel: PanelPref }) {
  const on = ctx.isPinned(panelId(panel));
  const full = !on && ctx.pinned.length >= PIN_CAP;
  return (
    <button
      onClick={() => ctx.togglePin(panel)}
      disabled={full}
      aria-pressed={on}
      aria-label={on ? "unpin this panel" : "pin this panel"}
      title={
        full
          ? `${PIN_CAP} panels are already pinned — unpin one first`
          : on
            ? "unpin — this panel will close with the others"
            : "pin — this panel stays open"
      }
      className={cn(
        "rounded border px-1 text-[11px] leading-none",
        on
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-row-hover hover:text-foreground",
        full && "cursor-not-allowed opacity-40",
      )}
    >
      ⊙
    </button>
  );
}

/**
 * Every pinned panel, drawn beside whatever the reader is doing now.
 *
 * Rendered from the preference document rather than from open-panel state, so
 * "these came back when I reloaded" and "these are pinned right now" are the
 * same list — there is no second copy to drift. A list's members are resolved
 * through the scene on the way out, which is what stops a pinned panel showing
 * a resource as it was when it was pinned rather than as it is.
 */
function PinnedPanels({ ctx }: { ctx: Ctx }) {
  return (
    <>
      {ctx.pinned.map((p) => {
        if (p.kind === "detail") {
          const node = NODES[p.subject];
          if (!node) return null;
          return (
            <NodePreview
              key={panelId(p)}
              node={node}
              ctx={ctx}
              onClose={() => ctx.togglePin(p)}
              onOpen={ctx.onSelect}
            />
          );
        }
        const members = (p.members ?? []).map((k) => NODES[k]).filter((n): n is SceneNode => !!n);
        if (!members.length) return null;
        return (
          <InlineList
            key={panelId(p)}
            label={p.label ?? p.subject}
            members={members}
            ctx={ctx}
            pinnedAs={p}
            onClose={() => ctx.togglePin(p)}
          />
        );
      })}
    </>
  );
}

/** Render the list over this container when it is the one that opened it. */
function InlineHost({ hostKey, ctx }: { hostKey: string; ctx: Ctx }) {
  if (ctx.inline?.host !== hostKey) return null;
  return (
    <InlineList
      label={ctx.inline.label}
      members={ctx.inline.members}
      owner={ctx.inline.owner}
      ctx={ctx}
      side={ctx.inline.side}
      at={ctx.inline.at}
      onClose={() => ctx.openInline(null)}
    />
  );
}

function NodeChip({
  node,
  ctx,
  compact,
  bare,
  tight,
}: {
  node: SceneNode;
  ctx: Ctx;
  compact?: boolean;
  /** Inside a group of one type the heading already carries the icon, so
      repeating it on every row is a column of identical glyphs paying for
      itself in width. */
  bare?: boolean;
  /** Rendered on a border strip, which runs one step down the type scale. */
  tight?: boolean;
}) {
  const p = node.position;
  const attached = node.children ?? [];
  const selected = ctx.selectedKey === node.key || ctx.preview?.node.key === node.key;
  // Codes describe the UNIT, so they sit on the box border rather than on the
  // chip: a security group governs the instance and its interfaces together.
  const codes = Object.values(ctx.ann.byNode[node.key] ?? {}).flat();
  const self = ctx.ann.selfCode[node.key];
  return (
    <button
      /* The same rung a list row opens, anchored at the chip instead of at a
         list. A chip used to jump straight to the sheet, so one resource read
         two different ways depending on whether the reader found it on the
         canvas or in a list — and the sheet covers the canvas it was clicked
         on. The preview carries the whole body and its ⛶ is the way up. */
      onClick={(e) =>
        ctx.openPreview({
          node,
          at: makeRoom(e.currentTarget, undefined, PANEL.detail.w, PANEL.detail.maxH),
        })
      }
      data-node={node.key}
      className={cn(
        "group flex min-w-0 flex-col justify-center overflow-hidden rounded-md border",
        "border-border bg-surface text-left transition-colors",
        bare ? "gap-1 px-2 py-1" : "gap-1.5 p-2",
        tight ? "px-1.5 py-0.5" : "",
        // Grow into the column, shrink when it is narrow, never force it wider.

        selected ? "border-primary bg-row-selected" : "hover:bg-row-hover",
      )}
      /* Both dimensions fixed, not just width. Height was left to the content
         and the content disagreed: a bare name came out 29px, a name with code
         tags 31px, a name with a Badge 37px — so five chips were never the same
         five chips, and `measureGroup` could only ever be approximately right.
         Stating it here makes the model true by construction rather than by
         inspection. */
      style={{ width: CHIP_W, height: tight ? undefined : CHIP_H }}
    >
      {/* ONE line: what it is called, and what governs it. Nothing else.
       *
       * A chip used to grow downward — a badge row, then up to four attachment
       * lines with their own icons — so a Lambda showing `$LATEST` and its
       * aliases was three times the height of an S3 bucket showing nothing.
       * Groups of the same size came out different heights, columns could not
       * align, and no amount of packing could fix it because the raggedness was
       * inside the cells.
       *
       * The composition claim survives in the `N attached` badge: an instance,
       * its volumes and its interfaces are still one thing, and the panel still
       * names them. What is gone is enumerating them on the canvas, where the
       * only question a chip has to answer is "which resource is this". */}
      <div className="flex min-w-0 items-center gap-1.5" title={node.arn || node.id}>
        {!bare && <Icon resourceKey={node.type} size={15} />}
        <span
          className={cn(
            "flex-1 truncate",
            tight ? TYPE_SCALE.borderStrip.name : TYPE_SCALE.inline.name,
          )}
          style={{ minWidth: NAME_FLOOR }}
        >
          {displayName(node)}
        </span>
        {/* Never wrapping, at either level. Letting the badge STRIP shrink was
            not enough: squeezed below their content the badges wrapped their own
            text, so `iam-4` became two lines and the chip went back to 44px.
            The badges keep their width and the name gives — it is the one thing
            here that can lose characters and still be recognised. */}
        <span className="flex shrink-0 items-center gap-1 whitespace-nowrap">
          {self ? <Badge className="mono !text-[11px]">{self}</Badge> : null}
          {/* Coloured by the arm its target rides, so the chip and the border
              it came from are the same hue and a reader goes to the right one
              without reading a word.

              A span, not a Badge: `Badge` carries SEMANTIC tone — red means
              critical — and a reader who has learned that must not read a
              wayfinding tag as a problem. */}
          {codes.slice(0, 2).map((c) => (
            <span
              key={c}
              style={codeTone(c)}
              title={codeTitle(c, ctx.ann.legend)}
              /* Tight, because a code shares a line with the name and the name
                 is what a reader came for. At 11px with a border and 6px of
                 padding two codes took 80 of a chip's 174px and `onam-eks-...`
                 became `onam-ek...`. No border, 10px, 3px of padding: the same
                 four characters, forty pixels back, still legible and still
                 unmistakably the hue of the arm they point at. */
              className="mono shrink-0 whitespace-nowrap rounded px-1 py-[1px]
                         text-[10px] font-bold leading-[14px]"
            >
              {c}
            </span>
          ))}
          {(p as { dangling?: boolean })?.dangling ? <Badge tone="orange">unattached</Badge> : null}
          {p?.entry ? <Badge tone="orange">Entry point</Badge> : null}
          {p?.assumed ? <Badge tone="red">assumed</Badge> : null}
          {attached.length > 0 && (
            <Badge className="mono !text-[11px]" title={`${attached.length} attached`}>
              {attached.length}
            </Badge>
          )}
        </span>
      </div>
    </button>
  );
}

/**
 * A whole category, opened from a border strip.
 *
 * A strip shows two names and a count, so "what else is in here" needs an
 * answer that is not "make the strip taller". Clicking the heading lists the
 * lot; clicking a row drills into that one resource.
 */
function memberIndex() {
  const out: Record<string, SceneNode[]> = {};
  for (const n of Object.values(NODES)) {
    const c = (n.position as { cluster?: string })?.cluster;
    if (c) out[c] = [...(out[c] ?? []), n];
  }
  return out;
}

type Rule = { egress: boolean; ports: string; peer: string };

/**
 * Security group rules, read off the collected rule resources.
 *
 * A rule names its group in `GroupId`, so the index is built by walking every
 * rule once rather than by asking each group for its rules. `-1` is AWS for
 * "all", in both the protocol and the port, which is worth spelling out - a
 * table of `-1` reads as missing data rather than as "everything".
 */
function ruleIndex() {
  const out: Record<string, Rule[]> = {};
  for (const n of Object.values(NODES)) {
    if (n.type !== "ec2.security_group_rule") continue;
    const d = (n as unknown as { detail?: Record<string, unknown> }).detail;
    const group = d ? String(d["group"] ?? "") : "";
    if (!group) continue;
    const proto = String(d!["protocol"] ?? "-1");
    const from = Number(d!["from_port"] ?? -1);
    const to = Number(d!["to_port"] ?? -1);
    // `-1` is AWS for "all", in both the protocol and the port. Printed raw it
    // reads as missing data; spelled out it reads as the finding it usually is.
    const ports =
      proto === "-1"
        ? "all traffic"
        : from === -1
          ? proto
          : from === to
            ? `${proto}/${from}`
            : `${proto}/${from}-${to}`;
    const peer = String(
      d!["cidr_v4"] ?? d!["cidr_v6"] ?? d!["peer_group"] ?? d!["prefix_list"] ?? "—",
    );
    const key = `ec2.security_group:${group}`;
    out[key] = [...(out[key] ?? []), { egress: Boolean(d!["egress"]), ports, peer }];
  }
  return out;
}

/**
 * Container key -> the rules drawn AS a box inside it, with what each encloses.
 *
 * The engine decides which rules qualify: contiguous members, and a box tighter
 * than the rail the rule already rides. Six rules in this estate govern anything
 * drawn at all and two of those are contiguous, so this is rare by nature — a
 * security group scoped to one subnet, not the usual one spanning a VPC.
 */
function wrapIndex() {
  const out: Record<string, { rule: SceneNode; members: Set<string> }[]> = {};
  const GOV = new Set([
    "protected-by",
    "encrypted-by",
    "accessible-by",
    "constrained-by",
    "routes-through",
  ]);
  for (const n of Object.values(NODES)) {
    const w = (n.position as { wrap?: string })?.wrap;
    if (!w) continue;
    const members = new Set(
      (SCENE.edges ?? [])
        .filter((e) => GOV.has(e.edge_type) && e.target_key === n.key)
        .map((e) => e.source_key),
    );
    out[w] = [...(out[w] ?? []), { rule: n, members }];
  }
  return out;
}

const RELATED = relatedIndex();
const NODES = nodeIndex();
const PARENTS = parentIndex();
const WRAPS = wrapIndex();
const MEMBERS = memberIndex();
const RULES = ruleIndex();

/* Edges that say something GOVERNS this resource, and what to call each. The
   second hop matters: a role is only half the answer, the policies attached to
   it are the other half, and that is the question anyone actually opens a
   panel to ask. */
const GOVERNS: Record<string, { label: string; hop?: string }> = {
  assumes: { label: "IAM role", hop: "references" },
  "can-access": { label: "IAM role", hop: "references" },
  "protected-by": { label: "security group" },
  "encrypted-by": { label: "encryption key" },
  "accessible-by": { label: "resource policy" },
  "constrained-by": { label: "constraint" },
  "routes-through": { label: "route table" },
};

/**
 * What this orchestrator drives.
 *
 * The mirror of Governance: that section answers "what applies to me", this
 * one answers "what do I decide". An autoscaling group's members are the
 * clearest case - the group is a rule about how many instances should exist,
 * and the instances are its output.
 */
function MembersSection({ node }: { node: SceneNode }) {
  const members = MEMBERS[node.key] ?? [];
  if (!members.length) return null;
  const zones = new Set(members.map((m) => PARENTS[m.key]?.key).filter(Boolean));
  return (
    <PanelSection title={`Members · ${members.length}`}>
      {zones.size > 1 && (
        <p className="mb-2 text-[11px] text-muted-foreground">across {zones.size} zones</p>
      )}
      <ul className="space-y-1">
        {members.map((m) => (
          <li key={m.key} className="flex items-center gap-1.5">
            <Icon resourceKey={m.type} size={11} />
            <Mono truncate className="min-w-0 flex-1 text-muted-foreground">
              {displayName(m)}
            </Mono>
          </li>
        ))}
      </ul>
    </PanelSection>
  );
}

/**
 * A security group's rules, in the direction traffic moves.
 *
 * 228 of these were being collected and thrown away because the ARN recipe
 * read a field AWS does not return. They are the answer to the only question
 * anyone opens a security group to ask, so they get the panel's plainest
 * treatment: what may reach it, and where it may reach.
 */
function RulesSection({ node }: { node: SceneNode }) {
  const rules = RULES[node.key] ?? [];
  if (!rules.length) return null;
  const inbound = rules.filter((r) => !r.egress);
  const outbound = rules.filter((r) => r.egress);
  const row = (r: Rule, i: number) => (
    <li key={i} className="flex items-baseline gap-2 text-[11px]">
      <Mono className="w-24 shrink-0 text-muted-foreground">{r.ports}</Mono>
      <Mono truncate className="min-w-0 flex-1">
        {r.peer}
      </Mono>
    </li>
  );
  return (
    <PanelSection title={`Rules · ${rules.length}`}>
      {inbound.length > 0 && (
        <>
          <div className="mb-1 text-[10px] text-muted-foreground">inbound from</div>
          <ul className="mb-2 space-y-0.5">{inbound.map(row)}</ul>
        </>
      )}
      {outbound.length > 0 && (
        <>
          <div className="mb-1 text-[10px] text-muted-foreground">outbound to</div>
          <ul className="space-y-0.5">{outbound.map(row)}</ul>
        </>
      )}
    </PanelSection>
  );
}

/**
 * Everything this resource reaches, grouped by the service that provides it.
 *
 * This replaced two sections that answered halves of one question -
 * `Governance` listed what governs the resource and `Related` listed the rest,
 * and a reader had to join them by eye to see that the security group arrives
 * through the interface rather than directly.
 *
 * Drawn as a tree because the hierarchy IS the answer: a key sits under the
 * volume it encrypts, and an interface under the group that protects it. Every
 * branch opens by default - the estate is shallow enough that nothing runs
 * away, and a collapsed branch hides the very thing the panel was opened for -
 * but each one collapses, because a security group with ten interfaces should
 * not push the rest of the panel off screen.
 *
 * `relatedTo` and `toTree` decide the rows and the nesting; this only draws.
 */
function RelatedTree({ node, onOpen }: { node: SceneNode; onOpen: (n: SceneNode) => void }) {
  // `relations`, not `edges`: the canvas list drops containment and attachment
  // because nesting says them, which left a listener's own panel claiming it
  // was attached to nothing.
  const groups = React.useMemo(
    () =>
      byService(
        toTree(
          relatedTo(node.key, SCENE.tree, SCENE.relations ?? SCENE.edges ?? []),
          // Nothing is rolled up. Each type group scrolls instead, so a
          // truncation placeholder would render as a blank row carrying only
          // a chevron — which is what it was doing.
          Number.MAX_SAFE_INTEGER,
        ),
      ),
    [node.key],
  );
  if (!groups.length) return null;
  const total = groups.reduce((n, g) => n + g.total, 0);

  return (
    <PanelSection title={`Connections · ${total}`}>
      <div className="space-y-3">
        {groups.map((g) => (
          <div key={g.service}>
            {/* The service, once. A flat list said `referenced by` on every
                line and never said IAM at all. */}
            <div className="mb-1 flex items-baseline gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-widest">
                {g.service}
              </span>
              <span className="mono text-[10px] text-muted-foreground">{g.total}</span>
              <span className="h-px flex-1 bg-border" />
            </div>

            {g.types.map((t) => (
              <div key={t.type} className="mb-1.5 last:mb-0">
                <div className="flex items-baseline gap-1.5 px-0.5 py-0.5">
                  <span className="text-[10px] text-foreground">
                    {t.type.split(".").pop()?.replace(/_/g, " ")}
                  </span>
                  <span className="mono text-[10px] text-muted-foreground">— {t.relationship}</span>
                  {t.total > 6 && (
                    <span className="mono ml-auto text-[10px] text-muted-foreground">
                      {t.total}
                    </span>
                  )}
                </div>
                {/* Nothing is truncated. A security group's 356 rule records
                    scroll in their own cell rather than pushing the rest of
                    the panel off the screen — and the count above says 356,
                    which `+351 more` only hinted at. */}
                <div
                  className={cn(
                    "overflow-hidden rounded border border-border",
                    t.total > PANEL_ROWS ? "overflow-y-auto" : "",
                  )}
                  style={t.total > PANEL_ROWS ? { maxHeight: PANEL_SCROLL_AT } : undefined}
                >
                  {t.rows.map((r) => (
                    <RelatedRow key={r.key} row={r} onOpen={onOpen} depth={0} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </PanelSection>
  );
}

/** One related resource, and anything reached through it. */
function RelatedRow({
  row,
  onOpen,
  depth,
}: {
  row: RelatedNode;
  onOpen: (n: SceneNode) => void;
  depth: number;
}) {
  return (
    <>
      <button
        onClick={() => {
          const target = NODES[row.key];
          if (target) onOpen(target);
        }}
        title={row.key}
        style={{ paddingLeft: 8 + depth * 14 }}
        className="flex w-full items-center gap-1.5 border-b border-border/50 py-1 pr-2
                   text-left last:border-b-0 hover:bg-row-hover"
      >
        {depth > 0 && <span className="text-[9px] text-muted-foreground">↳</span>}
        <Icon resourceKey={row.type} size={11} />
        <Mono truncate className="min-w-0 flex-1 text-[11px]">
          {row.name}
        </Mono>
        {row.facts.length > 0 && (
          <Mono truncate className="max-w-[38%] shrink-0 text-[10px] text-muted-foreground">
            {row.facts[0]}
          </Mono>
        )}
        <span className="shrink-0 text-[10px] text-muted-foreground">↗</span>
      </button>
      {row.children.map((c) => (
        <RelatedRow key={c.key} row={c} onOpen={onOpen} depth={depth + 1} />
      ))}
    </>
  );
}
function DetailSection({ node, compact }: { node: SceneNode; compact?: boolean | undefined }) {
  // The scene's copy paints immediately; the API's refines it when it lands.
  // Seeded rather than awaited, because a panel that opens empty and fills in
  // half a second reads as broken even when it is working.
  const live = useQuery(assetQuery(node.arn || node.id || null));
  const detail =
    (live.data?.metadata as Record<string, unknown> | undefined) ??
    (node as unknown as { detail?: Record<string, unknown> }).detail;
  // Scalars only. The scene's `detail` is already catalog-filtered, but the
  // API returns the whole `metadata` column — including `raw`, the entire
  // collector payload, which rendered as a cell reading `[object Object]`.
  const rows = Object.entries(detail ?? {}).filter(
    ([k, v]) => k !== "raw" && v !== null && v !== undefined && v !== "" && typeof v !== "object",
  );
  if (!rows.length) return null;

  return (
    <PanelSection
      title={`Configuration · ${rows.length}${live.data ? "" : live.isFetching ? " · syncing" : ""}`}
    >
      {/* Two columns of key|value, not two columns of stacked cells. A cell
          that puts the label above the value spends a whole line naming a
          thing — at 17 fields that is 17 lines of label. Paired left-to-right
          reads as a spec sheet and fits the same 17 in nine rows, which is
          what leaves room for Related without scrolling. */}
      <dl
        className={cn(
          `grid gap-x-4 gap-y-0 overflow-hidden rounded-md
           border border-border bg-surface px-3 py-1.5`,
          /* Two columns need ~360px of content box; the preview has 335. Paired
             left-to-right in that width the value had 90px and every one of
             them truncated, so the spec sheet became a column of ellipses. */
          compact ? "grid-cols-1" : "grid-cols-2",
        )}
      >
        {rankFields(rows).map(([k, v]) => (
          <div
            key={k}
            className="flex items-baseline justify-between gap-2 border-b border-border/50
                       py-1 last:border-b-0"
          >
            <dt className="shrink-0 text-[11px] text-muted-foreground">{k}</dt>
            <dd className="mono min-w-0 truncate text-right text-[11px] text-foreground">
              {typeof v === "boolean" ? (v ? "yes" : "no") : String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </PanelSection>
  );
}

/**
 * One related resource, as a row.
 *
 * The shape the reference design uses everywhere it lists a resource: a tinted
 * icon tile, the name over what it is, and a chevron saying the row goes
 * somewhere. Reused by every list in the panel so scope, composition and
 * attachment read as one vocabulary rather than three.
 *
 * The right-hand slot carries STATE, not utilisation or cost. The design this
 * copies puts a health dot and a dollar figure there; we have neither — its
 * utilisation is `Math.random()`, and 0 of 1,030 assets carry a cost. What we
 * do have is the resource's own `state`, which 42 types report, so that is
 * what the slot shows and nothing is invented to fill it.
 */
function ResourceRow({
  node,
  onOpen,
  indent = 0,
  meta,
}: {
  node: SceneNode;
  onOpen: (n: SceneNode) => void;
  indent?: number;
  meta?: string;
}) {
  const detail = (node as unknown as { detail?: Record<string, unknown> }).detail ?? {};
  const state = String(detail["state"] ?? detail["status"] ?? detail["life_cycle_state"] ?? "");
  return (
    <button
      onClick={() => onOpen(node)}
      style={{ paddingLeft: 10 + indent * 16 }}
      className="flex w-full items-center gap-2 border-b border-border/60 py-1.5 pr-2.5
                 text-left last:border-b-0 hover:bg-row-hover"
    >
      {indent > 0 && <span className="text-[10px] text-muted-foreground">↳</span>}
      <span
        className="grid size-6 shrink-0 place-items-center rounded"
        style={{ background: "var(--color-surface-tertiary)" }}
      >
        <Icon resourceKey={node.type} size={12} />
      </span>
      <span className="min-w-0 flex-1">
        <Mono truncate className="block text-[11px] text-foreground">
          {displayName(node)}
        </Mono>
        <span className="block truncate text-[10px] text-muted-foreground">
          {meta ?? `${resourceWord(node.type)}${node.layer_name ? ` · ${node.layer_name}` : ""}`}
        </span>
      </span>
      {state && <Mono className="shrink-0 text-[10px] text-muted-foreground">{state}</Mono>}
      <span className="shrink-0 text-[10px] text-muted-foreground">›</span>
    </button>
  );
}

/** `ec2.network_interface` -> `network interface`, for a row's second line. */
function resourceWord(type: string): string {
  return (type.split(".").pop() ?? type).replace(/_/g, " ");
}

/** The containers this node sits inside, outermost first. */
function ancestryOf(node: SceneNode): SceneNode[] {
  const out: SceneNode[] = [];
  let parent = PARENTS[node.key];
  while (parent && out.length < 8) {
    out.unshift(parent);
    parent = PARENTS[parent.key];
  }
  return out;
}

/**
 * What a reader looks for first, whatever the resource.
 *
 * A panel that lists 17 fields in payload order gives `ami_launch_index` the
 * same weight as `state`. These four questions are the ones someone opens an
 * inventory to ask — is it running, how big, is it exposed, is it encrypted —
 * so the fields answering them lead and the rest keep their order behind.
 *
 * Prefix-matched rather than enumerated: `state`, `life_cycle_state` and
 * `status` are the same question asked by three services, and a list of exact
 * names would need every one of 703 catalog columns classified by hand.
 */
const LEADS = [
  "state",
  "status",
  "life_cycle", // is it running
  "instance_type",
  "instance_class",
  "engine",
  "runtime",
  "size",
  "memory",
  "allocated_storage",
  "volume_type",
  "node_type", // how big, what kind
  "public",
  "publicly",
  "encrypted",
  "encryption", // exposed, protected
];

function rankFields(rows: [string, unknown][]): [string, unknown][] {
  const score = (k: string) => {
    const i = LEADS.findIndex((lead) => k.startsWith(lead));
    return i === -1 ? LEADS.length : i;
  };
  return [...rows].sort((a, b) => score(a[0]) - score(b[0]));
}

/** A section heading and its body, one shape for every block in the panel. */
function PanelSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="px-5 py-4">
      <h3 className="label-caps mb-2">{title}</h3>
      {children}
    </section>
  );
}

/**
 * State, region, account — the three the reference design puts under the name.
 *
 * Region and account come from the API, not the scene: the diagram bakes
 * placement into its tree and drops the fields, so a panel reading only the
 * scene could not say which account a resource was in.
 */
function HeaderChips({ node }: { node: SceneNode }) {
  const live = useQuery(assetQuery(node.arn || node.id || null));
  const detail = (node as unknown as { detail?: Record<string, unknown> }).detail ?? {};
  const state = String(detail["state"] ?? detail["status"] ?? detail["life_cycle_state"] ?? "");
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {state && (
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span
            className={cn(
              "size-2 rounded-full",
              /running|available|active|in-use|healthy/i.test(state)
                ? "bg-fresh"
                : "bg-muted-foreground",
            )}
          />
          {state}
        </span>
      )}
      {live.data?.region && <Badge className="mono !text-[10px]">{live.data.region}</Badge>}
      {live.data?.account_id && (
        <Badge className="mono !text-[10px]">acct {live.data.account_id}</Badge>
      )}
      {exposureOf(node) ? (
        <Badge className="mono !text-[10px]">
          L{exposureOf(node)} {EXPOSURE[exposureOf(node)]!.name}
        </Badge>
      ) : null}
    </div>
  );
}

/**
 * The detail panel: right-docked, over the canvas.
 *
 * Docked rather than centred because the canvas is the other half of the
 * answer — hovering a related row lights resources on the map, and a centred
 * panel covered the thing it was lighting.
 *
 * The stack is what makes a related resource clickable: opening one pushes
 * rather than replaces, so there is always a way back to where the reader
 * started. Reset whenever the selection changes from the outside, or the
 * breadcrumb would grow across unrelated selections.
 */
function NodeSheet({ node, onClose }: { node: SceneNode; onClose: () => void }) {
  const [stack, setStack] = React.useState<SceneNode[]>([node]);
  React.useEffect(() => setStack([node]), [node]);
  const current = stack[stack.length - 1] ?? node;

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="flex w-full flex-col gap-0 border-border bg-surface p-0 sm:max-w-lg">
        <SheetHeader className="shrink-0 gap-2 space-y-0 border-b border-border p-5 text-left">
          {stack.length > 1 && (
            <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
              <button
                onClick={() => setStack((st) => st.slice(0, -1))}
                className="rounded px-1 text-primary hover:bg-row-hover"
              >
                ‹ back
              </button>
              {stack.map((n, i) => (
                <React.Fragment key={n.key}>
                  {i > 0 && <span className="text-border-strong">›</span>}
                  <button
                    onClick={() => setStack((st) => st.slice(0, i + 1))}
                    className="max-w-[9rem] truncate hover:text-foreground"
                  >
                    {displayName(n)}
                  </button>
                </React.Fragment>
              ))}
            </div>
          )}
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-foreground">
            <Icon resourceKey={current.type} size={12} />
            <span>{current.layer_name ?? "—"}</span>
            <span className="text-border-strong">›</span>
            <span>{current.type}</span>
          </div>
          <SheetTitle className="mono break-all text-base font-semibold">
            {current.name || current.id}
          </SheetTitle>
          <HeaderChips node={current} />
          <Mono className="block break-all text-[11px] text-muted-foreground">
            {current.arn || current.id}
          </Mono>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border">
          <NodeBody node={current} onOpen={(n) => setStack((st) => [...st, n])} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

function NodeBody({
  node,
  onOpen,
  compact,
}: {
  node: SceneNode;
  onOpen: (n: SceneNode) => void;
  /** Rendered in the 360px preview rather than the sheet — the field grid
      drops to one column, which is the only thing that does not fit. */
  compact?: boolean | undefined;
}) {
  const attached = node.children ?? [];
  const crumbs = ancestryOf(node);
  // Tags and region live on the asset, not the scene node — one more reason
  // the panel fetches rather than reading only what the diagram baked in.
  const live = useQuery(assetQuery(node.arn || node.id || null));
  const tags = Object.entries(live.data?.tags ?? {});

  return (
    <>
      <DetailSection node={node} compact={compact} />

      {attached.length > 0 && (
        <PanelSection title={`Contained · ${attached.length}`}>
          {/* Grouped by type for the same reason Connections is grouped by
              service: an instance with one volume and three interfaces read as
              four undifferentiated rows, and the reader had to infer the
              shape from the names. */}
          <div className="space-y-1.5">
            {[
              ...attached
                .reduce(
                  (m, a) => m.set(a.type, [...(m.get(a.type) ?? []), a]),
                  new Map<string, SceneNode[]>(),
                )
                .entries(),
            ]
              .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
              .map(([type, list]) => (
                <div key={type}>
                  <div className="flex items-baseline gap-1.5 px-0.5 py-0.5">
                    <span className="text-[10px] text-foreground">
                      {type.split(".").pop()?.replace(/_/g, " ")}
                    </span>
                    <span className="mono text-[10px] text-muted-foreground">{list.length}</span>
                  </div>
                  <div
                    className={cn(
                      "overflow-hidden rounded border border-border",
                      list.length > PANEL_ROWS ? "overflow-y-auto" : "",
                    )}
                    style={list.length > PANEL_ROWS ? { maxHeight: PANEL_SCROLL_AT } : undefined}
                  >
                    {list.map((a) => (
                      <ResourceRow key={a.key} node={a} onOpen={onOpen} />
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </PanelSection>
      )}

      <MembersSection node={node} />
      <RulesSection node={node} />
      <RelatedTree node={node} onOpen={onOpen} />

      {crumbs.length > 0 && (
        <PanelSection title="Scope path">
          <div className="overflow-hidden rounded-md border border-border">
            {crumbs.map((n, i) => (
              <ResourceRow key={n.key} node={n} onOpen={onOpen} indent={i} />
            ))}
          </div>
        </PanelSection>
      )}

      {tags.length > 0 && (
        <PanelSection title="Tags">
          <div className="flex flex-wrap gap-1">
            {tags.map(([k, v]) => (
              <Badge key={k} className="mono !text-[10px]">
                {k}={v}
              </Badge>
            ))}
          </div>
        </PanelSection>
      )}

      <div className="px-5 py-4 text-[11px] text-muted-foreground">
        Resource id <Mono className="break-all">{node.id}</Mono>
      </div>
    </>
  );
}
