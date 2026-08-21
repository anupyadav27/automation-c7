# Diagram layout specification

How a scene graph becomes a *drawn* architecture diagram — the same one, every
time, for any account, on any cloud.

## 1. Why this exists

A provider's tree module answers one question: **what contains what**. It
resolves an instance into a subnet, a subnet into a zone, a zone into a network.
That is containment, and it was already solved.

It does not answer the other four questions a diagram needs:

| Question | Before | Consequence |
|---|---|---|
| In what **order** do siblings appear? | insertion order | two runs, two layouts |
| Along which **axis** — stacked or side by side? | renderer's choice | zones stacked in one view, columns in another |
| **Where** relative to the container border? | no concept | an internet gateway drew as a box in a corner instead of on the boundary it *is* |
| Which nodes are **one unit**? | only `attached-to` | a Kubernetes node and a standalone VM looked identical |

Three different components each picked their own answer — the tree appended in
insertion order, the UI sorted by member count, the renderer inherited both — so
the same estate rendered differently between runs. Meanwhile 3,811 of AWS's
4,761 types landed in one flat `R1` bucket with no sub-grouping.

This spec defines placement as data, the same way containment already is.

## 2. Two axioms

Everything below is derived from these. When a new service needs placing, the
answer comes from applying them — not from adding a special case.

> **A1 — The vertical axis is the traffic path.**
> Top to bottom is *flow*: internet → edge → load balancing → compute → data.
> If X is upstream of Y, X is above Y.

> **A2 — The horizontal axis is redundancy.**
> Left to right is *parallel copies of the same tier*: availability zones, peer
> categories of equal rank. Things beside each other are alternatives or
> replicas, never sequential steps.

These are why a reader can interpret a diagram they have never seen. Below means
*downstream*. Beside means *peer*. Two corollaries settle most arguments before
they start:

- **C1 — Cross-cutting things leave the flow.** Identity, encryption and
  monitoring apply to *everything* in a container. Placing them in the vertical
  flow would assert a position in the traffic path that they do not have. They
  render on the container's **border rail**.
- **C2 — Boundary objects sit on the boundary.** An internet gateway is not *in*
  a network; it is the network's edge. It draws **straddling the border line**,
  which is both accurate and how every hand-drawn cloud diagram does it.

## 3. One grammar, every cloud

AWS, Azure, GCP, OCI and IBM disagree about names and about almost nothing else.
Every one has an account boundary, a region, a software-defined network, a zone,
a segment of that network, a workload in it, and things bound to that workload.

| Role | AWS | Azure | GCP | OCI |
|---|---|---|---|---|
| `account` | Account | Subscription | Project | Compartment |
| `network` | VPC | VNet | VPC network | VCN |
| `zone` | AZ | Availability Zone | Zone | Availability Domain |
| `segment` | Subnet | Subnet | Subnetwork | Subnet |
| `workload` | EC2, RDS | VM, SQL DB | GCE, Cloud SQL | Instance |
| `attachment` | EBS, ENI | Disk, NIC | PD, NIC | Block Volume, VNIC |

So the grammar is defined **once**, against roles:

```
providers/common/topology/model.yaml     the grammar — roles, ranks, anchors
providers/common/topology/layout.py      the engine — 7 stages, no provider names
providers/<cloud>/catalog/topology_binding.yaml    which types play which role
```

A new cloud is a binding file, not a renderer. `test_model_names_no_provider_types`
enforces this mechanically: no provider type slug may appear in the model.

Where clouds genuinely differ, the binding carries it. A GCP network is global
where an AWS network is regional, so `scope` is declared per provider rather than
assuming AWS's answer is universal.

## 4. The five primitives

Every node's position is fully determined by six values, all from catalog data:

```
(container, band, lane, rank, anchor, cluster)
```

| Primitive | Meaning | Axis |
|---|---|---|
| **BAND** | a full-width horizontal strip inside a container | stacks **vertically** by rank (A1) |
| **LANE** | a column inside a band | sits **side by side** by rank (A2) |
| **RANK** | sparse integer, gaps of 10 | ordering within band or lane |
| **ANCHOR** | position relative to the container border | `in` · `edge.{n,s,e,w}` · `rail.{n,s,e,w}` |
| **CLUSTER** | a set of nodes drawn as one box | — |
| **CONTAINER** | inherited from the tree | unchanged by this spec |

- `in` — inside the container, participating in band/lane flow. Default.
- `edge.*` — **straddles the border line**. Boundary objects only (C2).
- `rail.*` — a strip along the border, outside band flow. Cross-cutting only (C1).

A container is a child too: a network occupies a band in its region's flow, so
every spine role carries its own `band` and `band_rank`. Without those, a VPC has
no slot in the ordering and falls through to `unplaced`.

## 4b. What KIND of thing — the six kinds

> **Reference model:** [The KIND axis](https://claude.ai/code/artifact/0c1638a8-2ce3-4e90-be3c-12c17573e71b)
> — each kind drawn in the position it describes, the live KIND × DOMAIN grid,
> and where the model strains against what a diagramming tool can express.
> Regenerate its figures with `python3 scripts/kind-grid.py`.

Sections 4–7 answer *where* a node goes. This answers *how it is placed at all*,
and it is the distinction that took longest to find. Without it a security
group, an internet gateway and a database are all just "contents".

Every kind answers the same question — *what is my relationship to the boundary
I am drawn in?* — which is why six is enough and why they form a family.

| Kind | Test | Placement |
|---|---|---|
| **boundary** | I *am* one | the spine |
| **resident** | I live inside it and hold an address | inline, in a band |
| **part** | I belong to exactly one resident | nests inside its host |
| **door** | I am a way through it | straddling the border line |
| **rule** | I govern everything inside it, and hold no address | its scope container's border, on the arm that matches its question (§4d-ii) |
| **record** | I am not in the picture; I describe something that is | never drawn — panel only |

**Naming rule: a role name is its kind**, optionally followed by `.` and a
qualifier — `record`, `part`, `door.egress`, `rule.identity`,
`resident.compute`. Enforced by test, because the prefix used to be pure
documentation that no code read: `flow.egress` was a door, `plane.application`
a resident and `plane.artifact` an artifact, and nothing caught any of them.

Three of these are easy to get wrong, and each was wrong here first:

- **A NAT gateway is a door, not a resident** — it lives in a segment and owns
  an interface, but what it *is* is the way out. Inline it was buried among the
  workloads it serves.
- **A key pair is a record, not a rule.** 79 resources — images,
  snapshots, key pairs, launch templates, log groups — were classed as rules
  and drawn on a border, which claimed a control they do not have.
- **An autoscaling group is a rule, not a resident.** It owns instances and
  holds no address, so traffic never arrives at one. Its members carry its name
  as a badge, the way a security group's members carry its code.

## 4c. The placement table

Three facts decide everything. **Scope** and **cardinality** are facts about the
type; **attached** is a fact about the instance.

| cardinality | attached | placement |
|---|---|---|
| `one` | yes | inside its host |
| `one` | no | its scope container's border |
| `many` | *ignored* | its scope container's border |
| `none` | — | inline, in its band |

Cardinality decides it rather than current attachment because a thing that can
only ever serve one host belongs *with* that host — drawing it separately splits
one unit in two. A thing that serves many belongs to none of them, so drawing it
inside any one is a lie. That is how a network ACL governing four subnets came
to be drawn inside one of them.

The `many` row ignores attachment deliberately: a security group attached to
nothing is still that network's security group, and an unused one is worth
seeing.

**Scope beats containment.** A binding's container is a fact about the resource;
which `contained-in` edge happened to be collected is an accident. When they
disagree the declared scope wins — the engine calls this *hoisting*.

One pass reads this table. It was three — one for a flow role outside a network,
one for an attachment with no host, one for a binding outside its scope — each
answering the same question in its own way, in an order that mattered and was
never written down.

## 4d. Doors: the side says where it leads

```
              north = ways in / lateral out
        [ internet gateway · transit · peering ]
    ┌──────────────────────────────────────────┐
    │                 network                  │
    │   rail: security groups · ACLs · routes  │
    └──────────────────────────────────────────┘
     [ interconnect ][ endpoint ][ NAT ][ endpoint ]
              south = ways out, centre-out
```

South is ordered **centre-out by how public the destination is**: the way to the
open internet takes the middle (`edge_rank` 10), private service access flanks
it (20), links to your own datacentre sit at the ends (30). A door anchors to
the container it is *scoped* to — a NAT gateway to its segment, an internet
gateway to its network.

## 4d-ii. The four arms — which border a rule rides

A rule applies to everything inside a boundary, so it has no position in the
traffic path. It still has to go somewhere, and choosing the side by hand let
one arm become a bin: east once carried secrets, encryption, config, deploy,
posture, provisioning and observability at once — seven different questions
stacked on one border because nothing said they were different.

The axioms decide it. A1 makes the vertical axis the traffic path, so north and
south are about **flow**. A2 makes the horizontal axis peers, so east and west
carry what applies regardless of where in the flow you stand.

| arm | question | what rides it |
|---|---|---|
| **west** | SUBJECT — who may act | identity, accounts |
| **east** | OBJECT — what protects the data | secrets, keys, certificates |
| **south** | PATH — how traffic moves through | firewall, routing, DNS |
| **north** | OVERSIGHT — who is watching, and what put this here | audit, config, posture, provisioning, orchestration, scaling |

North reads as oversight because it sits above the box looking down on it — and
because the north *edge* already holds the ways in, so the rail just inside it
is where controls over arrival belong.

Declared per role rather than derived, so every assignment is arguable in
review, and asserted by test: each rail role must name one of the four, and all
four must be in use. The rule pays for itself immediately — with each arm
answering one question, a misfit becomes visible. Detection services and
CodeDeploy were on east; neither protects data, and both moved to oversight the
moment the question was stated.

**A scaling group is north, not south.** It governs no traffic at all — it
decides how many instances exist, which is the same question an audit trail
answers about a change.

## 4d-iii. Adjacency — what the kind axis does *not* answer

Kind describes a node's relationship to **its own** boundary. It says nothing
about relationships **between** boundaries, and three real scenarios are
entirely the second thing:

| scenario | what works | what is missing |
|---|---|---|
| on-prem → transit gateway → VPC | the gateway draws as a door on the VPC edge | **on-prem has no boundary at all** — the spine starts at `org`, so everything is inside the cloud |
| VPC ↔ VPC peering | each VPC gets a door | both doors land on `edge.e`, facing the same way rather than each other; the link itself is never drawn |
| cross-account trust | the spine already supports `org → account` | ten accounts are discovered in this estate and one is drawn; the trust has nowhere to live |

**This is not a seventh kind.** A kind must change placement, and a peering
relationship places nothing — it connects two things already placed. It is a
third concept beside kind and domain: **adjacency**. A door is the aperture;
nothing yet expresses the far side.

Two pieces of design follow from that, neither built:

- **An external boundary.** On-premises, another cloud, the public internet.
  A boundary kind we never declared because the spine assumed everything is
  inside AWS. AWS ships a *Corporate data center* group icon precisely because
  a diagram needs a box for what is outside yours.
- **A link between boundaries**, which decides door *orientation* as well as
  the connection: two peered VPCs should face each other, so one door takes
  `edge.e` and its partner `edge.w`. `edge.w` is declared and unused today for
  exactly this reason.

Deliberately deferred: this estate has one VPC, no peering and one collected
account, so any of it would be built blind and verified against nothing.

## 4d-iv. The DOMAIN axis — thirteen categories, and why the thirteenth

Kind decides geometry. **Domain decides grouping, filtering and criticality, and
never position.** The two are independent: 20 of 43 domains in the live estate
span more than one kind, so neither nests under the other —
`compute.instances` alone is residents, rules and records at once.

Twelve of the thirteen categories are infrastructure primitives. The thirteenth
is **`application`** — services the cloud runs *for* you rather than primitives
you build one *from*:

| subcategory | examples |
|---|---|
| `application.communications` | Connect, Chime, SES, Pinpoint, WorkMail |
| `application.devices` | IoT Core, SiteWise, FleetWise, TwinMaker |
| `application.media` | MediaLive, MediaPackage, IVS |
| `application.business` | Omics, HealthLake, Deadline, DeviceFarm |
| `application.enduser` | WorkSpaces, AppStream, WorkDocs |

It exists because without it those services were forced into the nearest
infrastructure slot. `integration.messaging` reached **312 of 3,070** catalog
types — a contact centre, an email service and a document store filed as
messaging infrastructure — and `compute.edge` reached 262 by absorbing the whole
IoT platform. Both are now 20 and 51.

**The line against `compute.edge` is whether the service runs YOUR code
somewhere else.** Greengrass and Panorama do, and stay. IoT Core is a platform
you talk to, and moved.

`application` is criticality tier **A**, structural: a contact centre is not
annotation on an architecture, it *is* one.

Guarded by test: **no subcategory may hold more than 10% of the catalog.** The
number is arbitrary the way a speed limit is — what matters is that there is
one, and that 312 was ten points over it.

## 4d-v. Two gates the grid does not answer

Kind × domain says where a thing goes and what it is. Two questions sit either
side of that, and both were undefined.

### Is it drawn at all — decided first, and enforced

**396 of 1,124 nodes never reach the canvas.** That is the largest single
decision in the pipeline, and it is a property of the kind: a `record`
describes something rather than being it.

`model.yaml` declared `render: detail` on the record role for months and **no
code read it** — the renderer decided independently and the two agreed by luck.
A declaration nothing enforces is a comment with a colon in it.

The engine now reads it and emits `drawn` on every position; the renderer obeys.
Change `render:` in the model and the picture changes, which is what a model is
for.

### In what order, when several share a slot

**Thirteen subcategories ride the region's north rail.** They resolve to the
same role, so they share a rank, so the tie-break was `(service, name, id)` —
alphabetical. `governance.config` came second because `c` sorts early.

Every other axis here has a declared rank: bands have `band_rank`, lanes have
`rank`, doors have `edge_rank`, exposure is 1–4. The taxonomy was the only one
with no ordering at all.

**The order the taxonomy is written in IS the order it draws in.** No new
numbers to author — `taxonomy_ranks()` derives a sortable rank from the
sequence, category first so a category stays together, then position within it.
`sort_key` becomes `(rank, sub_rank, service, name, id)`.

Role rank still dominates, which is right: what a thing *does* is a stronger
statement than what kind of service it is. The subcategory only breaks ties.

> **Do not alphabetise the taxonomy block. Moving a line moves a box.**

## 4d-vi. Composition — three mechanisms, no per-service specs

An EC2 instance reads as layers: the instance, its volumes, its interfaces,
with a security group round it. An EKS cluster reads as those layers wrapped
again. That look does **not** come from describing EC2 — there are 3,070 types,
and per-service presentation specs would drift the day AWS ships anything.

It comes from three generic mechanisms:

| | what it produces | decided by |
|---|---|---|
| **stack** | EBS and ENI layers inside the instance | `part` nests in its host; order from `attachment_order` |
| **cluster wrap** | EKS or an autoscaling group round its members | membership edges, one dashed box |
| **rule wrap** | a security group drawn round what it protects | contiguity, measured per rule |

EC2 looks layered because it *has parts*. EKS looks wrapped because it *is a
cluster*. Neither needed a spec of its own, which is why a service nobody has
seen yet renders correctly the first time an account produces it.

### When a rule wraps

Two conditions, both measured, neither authored:

1. **Its drawn members sit in one container.** A box on the canvas can only
   enclose things on the canvas — a security group's `protected-by` edges come
   mostly from its own *rules*, which are records living in a panel. Counting
   those measured "all my rules are in the region": true of every group,
   informative about none, and it marked 27 groups wrappable when the answer
   is 2.
2. **The box is tighter than the rail the rule already rides.** A KMS key on
   the region rail whose members are all in that region is contiguous and says
   nothing. Eight of them drew eight boxes round the whole region.

Otherwise the rule stays a chip on its scope rail. Of 578 rules in the live
estate, 6 govern anything drawn at all and **2 qualify** — which is the honest
answer, not a disappointing one: most rules genuinely do span their scope.

**One wrap per resident.** If a cluster and a rule both claim a member, the
cluster wins and the rule stays a chip. Four nested borders round one instance
is a maze, not a diagram.

## 4d-vii. Product families — a naming problem, not a placement one

AWS ships one product as several service ids: Bedrock is five, Chime is six,
SSM is six. Each drew as its own box, so one product read as five unrelated
services.

A **family** is derived, not authored: the longest service id that is itself a
service. `bedrock-agent` folds into `bedrock` because `bedrock` exists;
`application-autoscaling` stays itself because `application` does not. 496 ids
collapse to 42 families with more than one member.

Two guards, both learned by getting it wrong. A prefix that is a common **word**
rather than a product absorbs unrelated services — `service` is a catalog id, so
`service-quotas` folded into "service". And a longer id is not always a
sub-product: VPC Lattice is its own thing, not part of VPC. Both are listed
explicitly, because nothing in the name distinguishes them from the real cases.

### Used for labels and filtering, not as a nesting level

A family box was built and **reverted**. It rendered in **zero** cases against
the only estate available to test it — every multi-service family present here
is rules and records, and families group residents. Two families also span
domains (`ecr`, `ssm`), so the box could not always sit in one lane.

What Bedrock exposed was never a missing nesting level. Domain and kind already
say where its resources go; what was broken is that they were **labelled** as
five unrelated things. Fixing the labels fixes that, and the composition
mechanisms in §4d-vi already produce the nesting the diagram needs.

### The related defect: 44 services spelled two ways

`bedrock-agentcore` and `bedrockagentcore`, `acmpca` and `acm-pca` — the same
service, differing only in hyphenation, each splitting one product across two
sets of types. **boto3 settles it, not type count**: the collector builds a
client from the service name, so a spelling boto3 does not have can never
collect. That criterion disagreed with "keep the heavier side" twice, and both
times the heavier side was the one that could never have worked.

## 4d-viii. Supporting services: family headings, and tags that point somewhere

### The rails say which discipline, not just which service

A rail carried 331 identity resources as six chips — roles, policies, instance
profiles, users — with nothing saying they were all *management* concerns, or
that CodeBuild and CodeDeploy are *devops* ones. Both arms now group by
**family · subcategory**: `management · identity`, `management · encryption`,
`devops · deploy`.

The family comes from the category, and **only for rules** — a resident is named
for its product, not for the discipline that looks after it:

| category | family |
|---|---|
| `security` `governance` `management` `network` `migration` | management |
| `devtools` | devops |

**Composed at render time, never a taxonomy category.** `management` is
`kind=rule` plus a domain. Folding that into a category name would undo the
separation everything else rests on: `compute.instances` is residents *and*
rules *and* records at once, and no `management-compute` category could say
that.

The vertical rails are 28px wide, so they show the family as an icon and a
count with the name in the tooltip; the horizontal arms have room for the text.
Same grouping either way.

### A tag has to point at something a reader can find

The short codes (`sg-2`, `kms-1`, `iam-3`) link a governed resource to what
governs it. **371 of 494 landed on records** — resources that live in a detail
panel and never draw — leaving **27 of 80 governing resources with a code that
appeared nowhere on the canvas.**

Only drawn nodes carry a tag now: 494 → 123 tags, 80 → 53 legend entries, with
every real relationship preserved (`ec2.volume` → kms, `ec2.instance` → iam and
sg, `rds.db_instance` → kms). A record still shows what governs it in its own
panel, which is where a reader of a record is already looking.

**Third appearance of one artefact.** A security group's `protected-by` edges
come mostly from its own *rules*. The same fact broke the rule-wrap contiguity
measure (27 wrappable, really 2) and inflated `integration.messaging`. Whenever
a count looks too good, check whether records are in it.

### Two things that already worked

Verified rather than assumed, and neither needed changing:

- **Several tags from different families on one box.** `ec2.instance` carries
  `sg` and `iam`; `rds.db_instance` carries `sg` and `kms`. The index is keyed
  by code family, so a node accumulates one code per family.
- **The tag lands on the right level of the hierarchy.** `ec2.volume` carries
  `kms`, `ec2.instance` carries `iam` — because the tag follows the **edge**,
  and the edge is a collected fact about which resource actually holds the
  relationship. Nothing has to declare that a volume is the KMS-bearing level;
  the data already says so.

## 4e. Exposure: how far from the internet

Placement says *where a thing sits*; exposure says *how hard it is to reach from
outside*. They are different questions and a diagram that answers only the first
cannot be read for risk.

| | name | test | examples |
|---|---|---|---|
| **L1** | internet | public by definition, with no network to hide behind | CDN, global WAF, public DNS |
| **L2** | entry | terminates inbound traffic **at** the boundary | load balancers, API gateways, internet gateways |
| **L3** | conditional | reachable from outside **only if** something grants it | instances, tasks, functions, buckets |
| **L4** | internal | no path from the internet exists | databases, caches, file systems |

Declared per **role** in `model.yaml`, so it is one ladder for every cloud — a CDN
is L1 on AWS, Azure and GCP alike — and it is not recomputed per resource.

Two consequences worth stating:

- **Only residents carry a level.** A security group is not nearer or further
  from the internet; it *applies*. Giving a binding, door, component or artifact
  a level would state a distance that has no meaning, and a reader would
  reasonably believe it. Enforced by test.
- **L3 is the interesting rung**, and it is deliberately not split into public
  and private. A bucket, an instance and a function are each reachable from
  outside only if a public address, a balancer or a resource policy says so —
  and that "only if" is where nearly every exposure finding comes from.

Reading order follows it: groups sort by exposure first and size only as a
tie-break, so a reader scanning a container meets the front door before the
things behind it. That is axiom A1 applied one level down from the bands.

## 4f. Orchestrators are not workloads

A container orchestrator, a workflow engine, a training service and a scaling
group all **drive** compute rather than being it. What actually runs is an
instance, a task or a function, and those are already drawn — so an ECS cluster
given a band of its own reads as a second fleet standing beside the real one.

`plane.orchestration` is a binding: scope decides where it rides, exactly as for
any other binding. What it governs is an edge, not a container, which is also the
honest shape — an orchestrator's members frequently live somewhere it does not.

Three things that look like they belong here and do not:

- **Autoscaling groups and capacity providers** are already `plane.scaling` —
  the same idea scoped to the network rather than the region, which is right,
  because a scaling group really is per-VPC.
- **Node groups, EMR clusters and Batch compute environments** *are* the
  instances. They stay `flow.compute`.
- **A registry is not an orchestrator.** ECR orchestrates nothing; it is what an
  image is pulled *from*. That is supply, not control, so it rides the platform
  rail and its taxonomy is `devtools.artifacts` — filing 16 repositories under
  `compute.containers` made a fleet of one ECS cluster look like a fleet of
  seventeen.

## 4g. The labels, and how many a reader can hold

Seven labelling systems accumulated, three of them spelled with an L. This is
the budget.

**On the canvas — four:**

| label | answers | where |
|---|---|---|
| **boundary** | what kind of box is this | container header: Account, Region, VPC, AZ, Subnet · public |
| **exposure** | how far from the internet | `L1`–`L4` on the group |
| **service** | what product is this | the group name: Lambda, S3, security groups |
| **role** | what does it do for the box | *part of*, *applies to*, *way in / out*, *config* |

**In the detail panel only — three:** taxonomy (`category.subcategory`, which
drives the filter), placement class and anchor, and spatial layer `L0`–`L4`.

Two rules decide what got cut:

- **One meaning per glyph.** `L0`–`L4` meant nesting depth and `L1`–`L4` means
  distance from the internet. Two ladders both spelled L is worse than either
  alone, so depth left the canvas — the nesting already shows it.
- **The architecture is unlabelled.** `resident` has no word, because being
  unlabelled *is* the statement that this is the architecture and everything
  else is annotation on it. The engine keeps `resident` where precision beats
  familiarity; the screen does not.

## 4f-i. The model may not contain settings nothing reads

An end-to-end review found **six declarations in `model.yaml` that read as
configuration and that no code consulted**:

| declaration | what was actually happening |
|---|---|
| `attachment_rule.one_attached` | the "nests inside its host" branch was implicit |
| `attachment_rule.none` | so was "stays inline" |
| `segment_tiers[].test` | tier logic hardcoded in Python |
| `entry_points[].where` | read as a boolean; its contents ignored |
| `edge_order.centre_out` | the renderer hardcoded which side |
| `cluster_placement.spans` / `.band_from` | never consulted |

This matters more than tidiness. **The model is the multi-cloud contract** — the
premise is that a new cloud is a binding file rather than code. Someone writing
an Azure binding would reasonably change a declared test and watch nothing
happen.

### One of them was not cosmetic

Because the tier tests were never read, **the `isolated` tier was unreachable.**
A segment with routes but none reaching the internet fell through to `unknown` —
which the model itself calls an *absence of routing data*, not a tier.

Those are different facts. "I looked and there is no way out" is a finding; "I
could not see the routes" is a gap in collection. Reporting both as `unknown`
told a reader neither, and the `assumed` flag that exists to separate them was
applied to both.

### The rule now

> Every key under a settings block must be reachable from code, or live under
> `note:`.

Asserted by test across `attachment_rule`, `edge_order`, `segment_tiers`,
`entry_points` and `cluster_placement`. `cluster_placement` moved wholesale
under a `note:` — its behaviour is real, but it is implemented in
`_resolve_clusters` and `cluster_precedence`, and its keys were describing that
rather than driving it.

`entry_points[].where` became `conditional: true`, which is what it always was:
a flag meaning "the provider's binding carries the real test", because the field
that proves a resource is public differs per cloud and cannot live in a
provider-neutral model.

## 4f-ii. Sequencing: a lane may not sort against a band

Lane ranks were written straight into `Position.rank`, so they competed with
band ranks. `resident.api` at 10 sorted above the network band at 20, and a
region read:

```
api  ->  VPC  ->  messaging  ->  events  ->  serverless
```

The regional services interleaved with the network instead of forming a block
beneath it. Nobody chose that order; it fell out of two scales sharing one
field.

`sort_key` is now **(rank, lane_rank, sub_rank, service, name, id)** — three
scales that can never be compared:

| | orders | example |
|---|---|---|
| `rank` | bands against each other | network 20 before services 30 |
| `lane_rank` | lanes inside a band | api 10 before datastore 50 |
| `sub_rank` | subcategories inside a slot | audit before config |

The region now reads **VPC → regional services → artifacts**, and inside the
services band **api → integration → application → serverless → datastore →
analytics**, which is the order the model lists them in.

**Orchestrators stay on the oversight rail and are not given a band.** An EKS
cluster appears at the compute level because it *wraps* the instances that are
there, not because it has a rank in the sequence — traffic does not pass through
a control plane on its way to a database.

## 4f-iii. Availability zones are columns

Uniform peers go **side by side as columns**, each as tall as it needs.
Redundancy is the horizontal axis (A2), and three zones beside each other say
"three copies of the same thing" in a way a stack cannot: stacked, the vertical
axis says *downstream*, which is false of a peer.

Equal fractions rather than content width, because a zone holding one subnet and
a zone holding four are still peers — drawing one narrower would say it matters
less when the only difference is what happened to land there.

## 4f-iii-b. Bands pack; zones do not

A zone gets an **equal** fraction of the width (§4f-iii): three availability
zones are three copies of the same thing, so equal width is a claim about
standing, and drawing one narrower would say it matters less.

A category **lane** gets width **proportional to content**. These do not
conflict, and the difference is what each width is claiming. Zones are peers, so
their widths must say nothing. Lanes are different kinds of thing — datastore is
not a copy of analytics — so a wider datastore says "there is more datastore
here", which is true and worth saying.

### The problem

Drawn one column per lane, a band is as tall as its **worst** lane while its
best use a fraction of that. On the live estate:

| lane | one column | packed | + one-line chips | columns |
|---|---|---|---|---|
| serverless | 792px | 698px | **256px** | 2 |
| datastore | 677px | 347px | **256px** | 3 |
| application | 308px | 235px | 233px | 2 |
| integration | 430px | 263px | 228px | 2 |
| api / analytics | 107px | 107px | 100px | 1 |
| **band** | **792px** | 698px | **256px** | |

**792px to 256px, and the four substantial lanes now sit within 28px of each
other** — which is what "the same height" means in practice.

Packing alone got 792 to 698 and stopped, because the band was then bounded by a
single **indivisible** block: one Lambda group whose chips each carried up to
four attachment rows, so it measured three times an S3 group of the same count.
Column allocation cannot cut a block, and **no packing can fix raggedness that
lives inside the cells.** Making the chip one line is what unblocked it.

### The rules

1. **A column is a subcategory.** Object, nosql, file — each column keeps a
   meaning even when it holds several products. Splitting on service groups
   packs marginally tighter and leaves columns that are "some of the datastore",
   which is not a thing anyone can name.
2. **Blocks stay contiguous.** Subcategories carry `sub_rank`; a split chooses
   *where* to cut, never which side a block lands. A free assignment would pack
   better and reorder the lane.
3. **The tallest lane gets the next column**, because the band's height is the
   tallest lane and every other spend is wasted width. Ties break on lane rank,
   then key — never on map order.
4. **The budget is the width the container already has**, set by its widest
   child. A band narrower than that leaves dead space to its right; wider makes
   the container grow for nothing.
5. **Uniform tracks.** A short column ends early. Flowing the next block up into
   the gap packs tighter and reads as misalignment rather than as data.
6. **A chip is one line, and its height is stated rather than observed.** Name,
   then the codes for whatever governs it, then a count if it owns anything.
   `width` and `height` are both set from `CHIP_W`/`CHIP_H`, so a group of n
   chips is a function of n alone and `measureGroup` is right by construction.
   Left to its content a chip came out 29px bare, 31px with codes and 37px with
   a badge, so five chips were never the same five chips.

   What a chip no longer does is enumerate what it owns. The composition claim
   survives in the count badge — an instance, its volumes and its interfaces are
   still one thing — and the panel still names them. On the canvas the only
   question a chip has to answer is *which resource is this*, and the name is
   the one thing on it that can lose characters and still be recognised, which
   is why the codes hold their width and the name truncates.

### One gap, everywhere

A layer's border needs air on both sides: inside, so a child's border does not
sit on its parent's; outside, so the tabs hanging off that child's edges have
somewhere to be. **16px**, uniformly — at 12px a rail tab landed on the border
of the box containing it, which is the difference between "attached to this" and
"drawn over that".

**Not scored against `ASPECT`.** That target is right for a container free to
choose its own shape and wrong for a band whose width is fixed by its siblings:
a band is already wider than it is tall, so aspect scoring picks the fewest
columns every time and the tall lane never splits. Measured on this estate,
aspect scoring returns the layout that already existed.

### Two facts the engine knew and did not say

`sub_rank` and `lane_rank` were computed in `layout.py` and dropped at
serialisation, so the view received `datastore` and `object` as bare strings
with nothing saying which came first — and sorted lanes by the alphabet of
whatever their first member happened to be called. `taxonomy_ranks()` exists
precisely to prevent that.

`categories.wrap: 4` declared "wrap to a new row after four lanes" and nothing
read it. It has been **removed rather than revived**: it was written when a lane
was one fixed-width column, so four lanes was a statement about width. A lane is
now as many columns as its content earns, so the same four lanes span anywhere
from one column to twelve, and a count can no longer say what it was written to
say. The row breaks where the container runs out of width, which is a
measurement, and measurements do not belong in the model.

This is the fourth declaration in this file's history that said something no
code read — after `render: detail`, `edge_order.centre_out`, and the `isolated`
segment tier. The pattern is worth naming: **a fact the engine knows, does not
say, and the renderer then guesses.**

## 4f-iv. Colour: the provider's where there is one, grey where there is not

AWS ships Architecture Group icons, with colours, for exactly five boundaries:
Account, Region, VPC, Availability Zone, Subnet. Those keep their hues — every
AWS diagram already draws them that way, and repainting them spends recognition
for nothing.

AWS ships no colour for an EKS cluster, a scaling group or a security group
boundary. Those take a **three-step grey ramp** that lightens inward:

```
orchestrator   light grey     EKS, the scaling group
  service      lightest grey  the EC2 group inside it
    resource   white          the instance, with its icon
```

Inventing a hue for them would assert a convention that does not exist.

## 4f-v. Splitting a domain: by what it does, never by where it runs

`network.delivery` held a global CDN and an in-subnet load balancer together —
too coarse to filter on, since all they share is "getting traffic to things".
It now splits:

| | holds |
|---|---|
| `network.delivery` | CloudFront, Global Accelerator — edge delivery |
| `network.loadbalancing` | ALB, NLB, CLB, listeners, target groups |
| `network.proxy` | API Gateway — a managed reverse proxy |
| `integration.api` | AppSync, App Runner, and API Gateway's own config |

**The split is by what the thing does, never by where it runs.** The rejected
version of `proxy` was "anything deployed outside a subnet", which reads
naturally and is wrong: it makes the domain depend on placement, so the same ALB
would change category the day AWS made it regional, and a filter on load
balancers would miss half of them.

`network.proxy` as shipped is not that rule. It holds API Gateway because API
Gateway *is* a reverse proxy — the same claim as calling an ALB a load
balancer — and it would keep the category if AWS moved it into a subnet
tomorrow. Placement never enters into it.

Bound per TYPE, not per service: `apigateway.rest_api` and `apigatewayv2.api`
are the proxies, and the other 38 `apigateway.*` types — keys, methods, models,
usage plans, authorizers — are the API's configuration and stay under
`integration.api`. A service-level binding swept all 40 into the traffic path.

### The placement that goes with it

An API gateway terminates inbound traffic at the boundary exactly as a load
balancer does. Both are **L2**, both **rank 10** — peers, so they read side by
side (A2) rather than as a sequence. What differs is only where they terminate:

| | role | container | band | L | rank |
|---|---|---|---|---|---|
| CloudFront | `resident.edge` | account | edge | 1 | 10 |
| API Gateway | `resident.ingress` | region | ingress | 2 | 10 |
| ALB / NLB | `resident.balancer` | network | balancer | 2 | 10 |

This is what the role's `container: [region, segment]` is for, and it took two
fixes to actually hold:

1. **The binding sent API Gateway to `resident.api`** — a lane resident in the
   services band, rank 30 — so it drew *below* the VPC as a regional service
   rather than in front of it as the entry point it is.
2. **The demotion rule overrode the role that permits it.** `demotion.
   requires_container` was `[network, zone, segment]`, which agrees with three
   of the four demotable roles and contradicts the fourth: `resident.ingress`
   declares `[region, segment]`, so a region-anchored gateway was demoted
   straight back out of the role that exists for it. A role's declared
   containers now count **in addition to** the global list — additive, so a
   role declaring fewer does not thereby become stricter.

A rule that overrides the declaration it is meant to enforce is not a rule. That
is the general form of the bug, and it is worth watching for elsewhere: any
place a hardcoded list sits beside a declaration that says the same thing.

## 5. Resolution order

```
1. INHERIT   container from the tree                     (unchanged)
2. CLUSTER   collapse owned nodes into composite boxes    (§8)
3. CLASSIFY  band + lane + rank + anchor from catalog     (§6)
4. DERIVE    segment tier, zone order, network groups     (§9)
5. COLLAPSE  drop empty bands/lanes, close the gaps       (§7)
6. ORDER     sort by (rank, service, name, id)            (§10)
7. SPAN      expand zone-spanning nodes across lanes
```

Layout is a **decoration pass over the existing tree**, never a rewrite. The tree
keeps sole ownership of containment; layout only answers where inside the
container. Neither can corrupt the other.

## 6. Binding resolution — data beats a lookup table

Per resource, first match wins:

```
1. discriminators   the resource's own payload decides
2. overrides        this exact type
3. services         the service segment of the type
4. unplaced         visible, named, and loud
```

Discriminators come first because **the same type can be two different places**:

| Type | Payload | Placement |
|---|---|---|
| VPC endpoint | `Gateway` | a route-table entry, no address in the network → **border** (`edge.e`) |
| VPC endpoint | `Interface` | has an interface in a segment → **in the segment** |
| Function | has a network config | a resident → `flow.compute` |
| Function | no network config | a regional service → `serverless` |

Two functions in one account legitimately land in different boxes. A lookup table
cannot express that, and guessing one answer for both is how a diagram starts
lying.

## 7. Presence collapsing — "if the first is absent, move up"

This is what makes one spec fit every account. Ranks are **relative order, not
coordinates**:

```
render = [slot for slot in slots if slot.members]   # drop empties
render.sort(by rank)                                 # keep declared order
position = enumerate(render)                         # close every gap
```

An account with no NAT gateway does not draw an empty NAT band — the private
segment tier moves up into its place. An account with no network at all draws a
region with only its service bands, and the zone axis disappears entirely.

**Entry-point resolution** is the same rule applied to the top of the diagram.
The "users / internet" marker attaches to the first role that *exists*:

| # | Entry point | Condition |
|---|---|---|
| 1 | `flow.edge` | CDN, global accelerator — any |
| 2 | `flow.ingress` | public API gateways |
| 3 | `flow.balancer` | internet-facing only |
| 4 | `flow.compute` | has a public address |
| 5 | *(none)* | the diagram opens at the region box |

Only the winner gets the marker. Losers still draw in their own band — present,
just not the front door.

## 8. Clustering — when several nodes are one box

Two independent mechanisms. Do not conflate them.

**Attachment clustering** — `attached-to` → nest. A volume draws inside its
instance. Already handled by the tree.

**Ownership clustering** — a VM that is a Kubernetes node is not a standalone VM.
It draws inside the cluster box, and only *unclaimed* workloads render alone.

A workload can satisfy several claims at once — a Kubernetes node is also in an
autoscaling group — so precedence is fixed in the model. Without it the winner
depends on dict iteration and the diagram flips between runs:

```
kubernetes > bigdata > ml > containers > batch > autoscaling > standalone
```

The highest-precedence owner wins; every loser becomes a **badge on the box
border**, never a second container. A cluster box spans the zone lanes at the
segment tier where its members actually live; the control plane is
provider-managed and reached over the network boundary, so it anchors to `edge.n`.

## 9. Derived facts — never read off a name or a tag

**Segment tier comes from routes.** A segment named `private` holding a default
route to the internet gateway *is* public, and the diagram must say so — that
contradiction is a finding, not a labelling preference.

| Tier | Rank | Test |
|---|---|---|
| public | 10 | default route to the internet boundary |
| private | 20 | default route to an egress node |
| unknown | 25 | **no routing data collected** — flagged `assumed`, not guessed |
| isolated | 30 | no default route |

`unknown` matters. An absence is reported as an absence rather than dressed up as
a derivation, so a reader can tell a derived tier from a fallback.

**Zones order by stable zone id**, not display name. Several clouds shuffle the
user-facing zone letter per account, so name-ordering makes two accounts
disagree about the same physical zone.

**Networks group by connectivity.** Union-find over peering and transit edges;
peered networks render as parallel lanes (A2), unrelated ones stack. With no
peering data every network is its own group and the layout degrades cleanly to
vertical stacking.

## 10. Determinism

A diagram that changes when nothing changed is not a diagram, it is noise.

1. **Every sort key is total.** `(rank, service, name, id)` for nodes;
   `(min rank, name)` for bands and lanes. Never count, never insertion order,
   never a hash.

   The second one is not pedantry. Grouping bands by minimum rank alone lets two
   bands tie, and a tie falls back to **set iteration order — which varies with
   the process hash seed**. The same estate then renders differently between
   runs, and an ordinary test suite only catches it on the unlucky seed. This
   spec shipped with that bug and `test_layout_is_independent_of_the_hash_seed`
   now runs the layout in subprocesses under three seeds to guard it.
2. **Only reachable nodes are placed.** A structural resource is registered under
   both its collected key and the synthetic container key the tree mints for it;
   the collected one is orphaned. Placing both counted three networks as six.
3. **Unplaced types fail loudly.** A type with no binding renders in a visible
   `unplaced` band carrying its type name — never silently absorbed into a
   default bucket. Silence is how thousands of types accumulated unnoticed.

## 11. Renderer contract

Renderers **consume** placement; they never compute it. `to_dict()` emits
children already in position order, so a renderer that iterates naively is
correct by default.

Two things static Mermaid cannot draw, and how they degrade honestly:

- **A node on a border line.** Mermaid has no boundary concept, so `edge.*`
  anchors render first inside their container with a hexagon shape. Position is
  approximated; the fact that it *is* a boundary is not.
- **A rail.** Cross-cutting groups collapse to one counted chip rather than
  scattering through the flow — the readable half of what a rail is for.

Placement must be computed where the **raw payloads** live. `to_dict()` does not
carry them, so a renderer physically cannot decide gateway-vs-interface
correctly. That is why `Scene.positions()` runs before serialisation.

## 12. Current state

Implemented and verified against a live account (588989875114 / ap-southeast-1 —
513 nodes, 3 VPCs, 2 AZs, 4 subnets):

- 513/513 nodes placed, **zero unplaced**
- category lanes render in declared rank order: api → integration → serverless →
  containers → datastore → analytics → ai
- rails collapse to counted chips; entry point resolves to the CloudFront
  distribution
- one segment tier derived `public` from routes; three flagged `unknown`
- 203 tests pass, including two mutation-checked determinism tests

**Not yet exercised on real data:** border anchors, spanning balancers, zonal NAT
and ownership clustering. This account is serverless-only — it has no internet
gateway, no load balancer and no EC2 instance — so those paths are covered by
fixtures rather than by the live estate.

**Known gap:** the `L6 attached` layer in `layer_assignment.csv` was derived by a
keyword rule and over-captured — `fsx.file_system`, `finspace.kx_cluster`,
`guardduty.finding` and ~25 others are classified as attachments. It only bites
for resources with no placement data, so the blast radius is orphans rather than
mis-nesting, but the bucket needs a pass.

---

## 5. Interaction — three levels, and what each answers

Placement is settled above; this is what happens when a reader touches it. It
was undocumented until the drill-down was built, which is why the spec ran to
§4f and then stopped.

### An arm wraps rather than overflows

A wall's tabs are bounded by the box they ride (`inset-y-6`) and wrap into
parallel columns when they do not fit. `layersNeeded` decides a column count
from `measureNode`'s height, and that number disagreed with what was drawn —
twelve tabs at 150px ran 1,866px down the side of a box 1,098px tall, because
the model said one layer was enough.

Rather than correct arithmetic against a height that is already wrong, the wall
is bounded by the box itself and the overflow goes in the next column. This is
still layout without DOM measurement: no JavaScript reads a rectangle, the box
constrains its own rail through CSS, and the diagram renders identically twice.

### A service is a count, not a list of chips

A group used to draw five chips and a `+N` button. That made the canvas argue
with itself: the same estate showed five names for a group of 26 and five for a
group of 400, and every group stood a different height depending on how many
members happened to fit.

The names moved to the list panel, which is built to hold them — it filters, it
scrolls, and it previews each row beside itself. What a tile answers on the
canvas is only *what runs here, and how much of it*, which is one line whatever
the count. Every tile is therefore the same height, and `measureGroup` returns a
constant: the packing arithmetic in `layout-metrics.ts` is exact by
construction rather than approximate by luck.

A tile carries every member's key in `data-members`, so
`[data-members~="key"]` lights it whichever of its members a relation points at
— carrying only the first would light a group of 55 buckets only when the
relation happened to name bucket number one.

### The three levels

| | trigger | shows | answers |
|---|---|---|---|
| **0** the canvas | — | boxes, chips and rail tabs | where does everything sit |
| **1** the list | click a rail tab, door tab or group heading | the resources behind that tab, over the box it rides | which ones are they |
| **2** the panel | click a row, or a chip | the right-docked sheet | what is this one, and what does it touch |

**The list opens at what was clicked.** It is `position: fixed`, portalled to
`document.body`, and placed from the clicked element's rect measured at click
time — `placePanel` in `layout-metrics.ts`, with the widths it is placed
against stated once in `PANEL`.

*This paragraph used to say the list rendered `absolute inset-0` inside its own
container, covering the box it belongs to, and that covering needed no
measurement because the overlay was a child of the thing it covered.* That was
true and is not. Two things broke it: rail tabs sit in containers with a
`transform`, which makes `position: fixed` resolve against that box rather than
the viewport, and the canvas has its own `overflow-auto`, which clipped any
overlay that tried to reach past it. A portal plus a measured anchor is what
survived both.

The measurement is permitted by the rule §10 already draws: measuring for an
**overlay** is not measuring for **placement**. Where a box goes is still
decided bottom-up with no DOM read anywhere. Only where the panel ABOUT that
box goes is measured, and a panel changes nothing about the picture beneath it.

Re-clicking the same tab closes the list, so a tab is its own toggle. The X
sits top-right.

### Hover: lit, and light

Hovering a row in the list lights that resource **and everything one hop from
it**, and drops everything else to `opacity: .2` — the same value out-of-focus
tiers already use, so a reader learns one dim and not two.

The lit set comes from `relatedTo()`, the resolver the panel uses, so the
canvas and the panel can never disagree about what a resource is connected to.
It is computed **without the roll-up cap**: `GROUP_LIMIT` exists so a panel
does not become a wall of 356 rule rows, but lighting is not a display list,
and capping it meant a security group's five slots all went to rules while the
interfaces it actually protects stayed dark.

Implemented as **one `<style>` element**, not per-chip state. The estate draws
over a thousand chips; threading a `hovered` prop through all of them would
re-render the whole canvas on every mouse move, for an effect that touches no
layout. Chips carry a static `data-node`, the canvas root carries
`data-canvas`, and a hover swaps one stylesheet. The cost of a hover is
independent of the size of the estate.

**Connector lines, on the same hover.** *This paragraph used to say they were
unbuilt.* `HoverTraces` now draws a labelled cubic from the hovered row to
every element standing for something it reaches — `trace.ts` holds the
geometry, so the curve, its arrowhead end and its label midpoint are all
testable without a browser.

Three things it has to get right, each of which was wrong once:

- **The lit set is derived, never read back off the page.** Reading
  `getComputedStyle(...).opacity` raced the stylesheet above — both run on the
  same state change — so every tile still measured as opaque and the curves
  fanned out to everything.
- **Rects are measured in the diagram's space, not the window's.** The overlay
  travels with the canvas scroll; `getBoundingClientRect` does not. Without
  `relativeTo`'s scroll term, every arrow drew at scroll-zero coordinates —
  and reaching a border rail nearly always means scrolling first.
- **One element can stand for many resources.** A tab carries four interfaces
  and a service tile fifty-five buckets, so the line is labelled
  `protected-by ×4` rather than drawn once and unlabelled.

The hover now answers both "which resources are connected to this" and "by
what path".

### The panel is docked, not centred

Right-docked, `sm:max-w-lg`. Centred was tried and reversed: the canvas is the
other half of the answer, and a centred panel covered the resources its own
hover was lighting.

Sections read outward from the resource: what it **is** (Configuration), where
it **sits** (Scope path), what it is **made of** (Contained), and what it
**reaches** (Connections). Every row is clickable and pushes onto a breadcrumb
stack, so following a chain never loses the way back.

**Configuration is ranked, not dumped.** Seventeen fields in payload order give
`ami_launch_index` the same weight as `state`. The fields answering the four
questions someone opens an inventory to ask — is it running, how big, is it
exposed, is it encrypted — lead, and the rest keep their order behind. Matched
on prefix, because `state`, `life_cycle_state` and `status` are one question
asked by three services.

**Contained groups by type, Connections by service then type.** A flat list
repeated the verb on every line and never named the service; an instance's four
children read as four undifferentiated rows. Both now say the grouping once and
scroll within a group rather than truncating it — a security group's 356 rule
records keep all 356, because a count on the heading plus a scrollable body
tells the truth where `+351 more` only hints at it.

**Two sections were cut.** `Overlay state` was which canvas toggles are on —
identical on every panel, a property of the view rather than the resource.
`Placement` was seven cells of which two repeated the header and three (`role`,
`band`, `anchor`) were how the layout engine thinks rather than how an operator
does.

Tier 2 is fetched from `/api/v1/inventory/assets/{uid}` and seeded from the
scene, so the panel paints immediately and refines when the call lands. A dead
API leaves it stale, never empty.

---

## 13. Sizing strategy — which dimensions are fixed, and why

Every dimension on the page falls into one of three classes. The class is not a
style preference; it follows from one question — **does anything else depend on
this number?**

### The three classes

| class | who decides | where it lives | example |
|---|---|---|---|
| **Fixed** | stated once, by us | `layout-metrics.ts` | chip 190×26, rail depth 26, panel widths |
| **Intrinsic** | the content, bottom-up | `measureChip` → `measureGroup` → `measureContainer` | groups, containers, bands |
| **Fluid** | the viewport, with a ceiling | a `maxHeight` plus scroll | panel heights, list bodies |

**Fixed** is for anything another element must reserve room for, or line up
with. A parent cannot reserve space for something whose extent depends on its
text — that is the whole argument. A rail tab left to its label came out
anywhere between 28px and 42px wide, so reserving 28 made the long ones overlap
and reserving 42 left every short one with a ragged margin. Fix the dimension
and let the label truncate.

**Intrinsic** is for anything with children. A box is as big as what it holds,
computed bottom-up from fixed atoms, so one estate produces one diagram on any
screen, at any zoom, in any export. The parent never divides space among its
children; the children report what they need and the parent adds up.

**Fluid** is for anything with no dependents. A panel has no parent and no
siblings — the only thing constraining it is the window, so it takes a ceiling
and scrolls. A list of two rows is 80px tall; a list of 250 is capped.

### The rules that follow

1. **A number two places need is declared once.** If markup and script both
   need a panel's width, the markup takes it from the constant. Panel widths
   were previously written twice — `w-[290px]` in a class and `290` passed to
   the placer — in eight places, with nothing making them agree, and the second
   copy is the one that decides where the panel lands.
2. **Text never sets a dimension.** It truncates against `NAME_FLOOR`. The name
   is the only thing on a chip that can lose characters and still be
   recognised, so it is the thing that gives.
3. **A derived number is derived, not retyped.** `RAIL_LABEL_MAX` is
   `RAIL_TAB_LEN`; `PANEL_SCROLL_AT` is `PANEL_ROWS × PANEL_ROW_H`. Writing
   `168` beside `> 6` is two facts that must move together, kept apart.
4. **A ceiling is not a size.** Fluid things declare the most they may take and
   scroll past it. Nothing downstream may read how tall they turned out.
5. **Borrowed space is returned.** Room lent to a panel — the gutter in
   `makeRoom` — is transient, applied outside the diagram's own box so no box
   moves, and cleared when the panel closes. Permanent reservation for a
   transient need cost a 1,880px scrollbar and the single-view read of the
   estate.

### What the tests hold

`layout-metrics.test.ts` asserts the invariants rather than the values, so the
numbers can change and the guarantees cannot:

- a list and its detail open together still leave room for two chips side by
  side at `MIN_VIEWPORT` (1280×720)
- no panel asks for a height the shortest supported window cannot give
- the detail panel is wider than the list it docks beside — it carries a
  two-column field grid, not names
- every panel is wider than a chip
- an empty arm reserves nothing; rails never collide with a sibling or a parent

### Where each component sits

| component | class | number |
|---|---|---|
| resource chip | fixed | `CHIP_W` × `CHIP_H` |
| service tile | fixed height, intrinsic width | `measureGroup` |
| container box | intrinsic | `measureContainer` |
| band / lane | intrinsic, packed | `pack.ts` |
| rail tab | fixed both ways | `RAIL_DEPTH` × `RAIL_TAB_LEN` |
| rail clearance | derived from layers | `railClearance` |
| list panel | fixed width, fluid height | `PANEL.list` |
| detail panel | fixed width, fluid height | `PANEL.detail` |
| filter dropdown | fixed width, fluid height | `PANEL.filter` |
| detail sheet | fluid, docked right | viewport |
| canvas | fluid, scrolls | viewport |
