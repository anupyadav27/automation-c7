# Cloud architecture diagram — requirements

Status: **draft for review**. Written to be argued with. Every number in §2 is
measured from the current `out/scene.json`, not estimated.

The companion document is [`diagram-layout-spec.md`](diagram-layout-spec.md),
which specifies the engine as built. This document specifies what is *wanted*,
what is *missing*, and who does which part.

---

## 0. Before anything else: you have been looking at the wrong app

Two dev servers are running, and both call themselves "Cloud Estate Console".

| port | app | directory | tracked by git | has the current work |
|---|---|---|---|---|
| **3100** | Next.js | `console/` | **no** | **no** |
| **3200** | TanStack Start | `console-app/` | yes | yes |

`console/` is the superseded UI from before we adopted Cloud Estate Console. It
is untracked, so deleting it is not reversible from git.

**Requirement R0.** One console. Stop `:3100`, and either archive `console/`
outside the repo or delete it deliberately. Until then every review is a coin
toss, and three rounds of "I can't see the changes" have already been spent on
it.

---

## 1. Goal

> Regenerate a standard, readable architecture diagram for any cloud account,
> every time, the way an architect would draw it by hand — and let a reader
> click any box to get the full truth about that resource.

Two properties carry everything else:

- **Deterministic.** Same estate → same diagram, on any screen, at any zoom, in
  any export. Already enforced by test.
- **Provider-neutral.** The grammar is defined once in terms of roles; each
  cloud ships a binding from its types to those roles. Already enforced by test.

---

## 2. Current state, measured

652 nodes in `ap-south-1`, account `588989875114`.

| kind | count | share | what it is |
|---|---|---|---|
| SUPPORTING | 392 | 60% | governs residents, holds no address |
| CONFIG | 145 | 22% | provenance and settings, off-canvas |
| SERVICE | 74 | 11% | the architecture itself |
| PART | 27 | 4% | belongs to exactly one service |
| CONTAINER | 10 | 2% | account, region, VPC, AZ, subnet |
| DOOR | 4 | <1% | ways in and out of a boundary |

**The headline: 11% of what we collect is the architecture.** Nine boxes in ten
are annotation on it. That is not a defect — it is why placement class exists —
but it sets the design constraint: the canvas must show 74 things well and
make the other 578 reachable, not draw all 652.

Concentration inside SUPPORTING is extreme: IAM 187, Secrets Manager 71,
KMS 34. Three services are 75% of everything supporting.

---

## 3. The classification — the complete list

### 3.1 Two axes, not one

This is the part that has caused the most churn, so it is stated plainly:

- **KIND** answers *what is this on a diagram* → decides **placement**.
- **DOMAIN** answers *what kind of service is this* → decides **grouping and
  filtering**.

They are independent, and they must be, because they disagree constantly.
`database.relational` holds one RDS instance (SERVICE) and 24 snapshots and
parameter groups (CONFIG). Forcing one axis to carry both would put 24
snapshots on the canvas to keep one database there.

A group's full name is **`KIND · domain`** — which is exactly the naming you
asked for: *supporting services · identity*, *supporting services · key
management*, *orchestrator services*, *config*.

### 3.2 The six kinds

| kind | test | placement | on canvas |
|---|---|---|---|
| **CONTAINER** | holds other things; is a boundary | the spine | yes, as a box |
| **SERVICE** | has an address; traffic terminates at it | inline, in a band | yes |
| **DOOR** | connects a boundary to somewhere else | straddling the border | yes |
| **SUPPORTING** | governs 1..N services; has no address | rail inside its scope border | yes, as a strip |
| **PART** | belongs to exactly one service | nested inside its host | yes, inside |
| **CONFIG** | describes or records; is not running | — | **no** — panel only |

**ORCHESTRATOR** is a sub-kind of SUPPORTING, separated because it answers a
different question: a security group says *what may reach this*, an ECS cluster
says *what put this here*. Same placement, different heading.

### 3.3 The complete table, as the estate stands

**CONTAINER** — 10
| domain | services |
|---|---|
| — | account, region, availability zone |
| network.connectivity | VPC, subnet |

**SERVICE** — 74 in 13 groups
| domain | n | services |
|---|---|---|
| storage.object | 42 | S3 |
| compute.serverless | 7 | Lambda |
| network.delivery | 5 | CloudFront, ELB, ELB Classic |
| integration.events | 5 | EventBridge |
| integration.api | 3 | API Gateway |
| compute.instances | 3 | EC2 |
| network.dns | 2 | Route 53 |
| integration.messaging | 2 | SNS, Pinpoint SMS |
| database.relational | 1 | RDS |
| database.document | 1 | DocumentDB |
| database.graph | 1 | Neptune |
| storage.file | 1 | EFS |
| integration.streaming | 1 | MediaConvert |

**DOOR** — 4: internet gateway ×2, transit gateway, VPC endpoint

**SUPPORTING** — 392 in 20 groups
| domain | n | services |
|---|---|---|
| security.identity | 187 | IAM |
| security.secrets | 71 | Secrets Manager |
| security.encryption | 34 | KMS |
| network.firewall | 33 | security groups, NACLs |
| network.routing | 19 | route tables, prefix lists, DHCP |
| devtools.artifacts | 17 | ECR, CodeArtifact |
| network.dns | 6 | Route 53 Resolver |
| compute.instances | 4 | EC2 Auto Scaling, Auto Scaling Plans |
| governance.provisioning | 4 | CloudFormation |
| governance.config | 3 | Config, Systems Manager |
| compute.containers | 2 | ECS *(orchestrator)* |
| governance.audit | 2 | CloudTrail |
| governance.observability | 2 | CloudWatch, flow logs |
| management.account | 2 | Organizations |
| security.certificates | 1 | Certificate Manager |
| ai.training | 1 | SageMaker *(orchestrator)* |
| integration.workflow | 1 | Step Functions *(orchestrator)* |
| analytics.query | 1 | Athena |
| management.catalog | 1 | Service Catalog |
| database.cache | 1 | ElastiCache users |

**PART** — 27: network interfaces 18, target groups 4, volumes 3, API stages 2

**CONFIG** — 145 in 17 groups, largest: CloudWatch Logs 31, RDS snapshots and
parameter groups 24, ElastiCache parameter groups 21, Lambda versions 15

### 3.4 Requirement

**R1.** Every collected type resolves to exactly one KIND and one DOMAIN, with
no unclassified bucket. Currently 4 container nodes carry `None.None` — the
account, region and AZ synthetics. Give them a domain rather than a hole.

**R2.** The classification lives in catalog data, never in renderer code. Adding
a service must not require a code change.

---

## 4. Placement rules

### 4.1 Scope beats containment

A resource is placed on the boundary it is **scoped to**, not the one that
happens to contain it. A network ACL with a `contained-in` edge to a subnet is
VPC-scoped, so it draws on the VPC. Already built (hoisting).

### 4.2 Attachment cardinality decides the rest

| cardinality | attached? | placement |
|---|---|---|
| exactly one host | yes | **nests inside the host** |
| exactly one host | no | **scope border** — and it is a cost finding |
| many hosts | — | **scope border** |
| no host concept | — | **inline, in a band** |

Measured against the estate: 8 of 18 network interfaces are attached to an
instance and nest inside it; 10 are attached to nothing and ride the subnet
border. All 3 volumes are attached. That distinction is exactly the one you
asked for, and it is live.

### 4.3 Known defect

**D-1.** `elbv2.listener` ×2 and `apigatewayv2.stage` ×2 are classified PART but
their parent is `region` — the owner edge is not collected, so they are
components with nothing to be a component *of*. They currently fall back to the
region rail, which is not wrong so much as meaningless.

**R3.** A PART with no host is an error, not a placement. Either collect the
owner edge or reclassify. It must be visible in a report, not silent.

---

## 5. Cluster containers — the biggest ask, and mostly blocked

The request: an EKS/ECS box spanning the availability zones, holding the EC2
instances that are its nodes, each with its interfaces and volumes; and Lambda
functions grouped inside a dotted Step Functions box.

This is the right shape. Here is what the data supports **today**:

| container wanted | edges present | verdict |
|---|---|---|
| **Autoscaling group over its instances** | `references` ×16, and `cluster` already populated on all 3 instances | **buildable now** |
| **EKS cluster over its nodes** | `eks.cluster` collects **0 assets** | blocked |
| **ECS cluster over its tasks** | **0** edges from `ecs.*` | blocked |
| **Step Functions over its Lambdas** | **0** edges from `stepfunctions.*` | blocked |

The EKS case is worth stating precisely, because the estate is not empty: an
autoscaling group in this account is literally named
`eks-nodegroup-spot-secops-70cf8277-…`, and its three instances are collected.
The cluster that owns them is not. `eks.cluster` is marked `collect: yes` in
`asset_types.csv`, returns zero, and logs no failure — the same silent-empty
behaviour noted earlier for 17 colliding catalog entries.

**R4.** A dotted cluster box spans the zone lanes its members actually occupy,
never a lane it has no member in. Members keep their own placement; the box is
drawn *around* them, not *instead of* them.

**R5.** Cluster membership comes from an edge, never from a name. Matching
`eks-nodegroup-*` would produce a diagram that is right in this account and
wrong in the next one.

**R6 (prerequisite).** Collect `eks.cluster`, `ecs.service`, `ecs.task`, and
Step Functions state-machine → invoked-resource edges. Until then three of the
four cluster boxes cannot be drawn honestly, and drawing them from names would
be worse than not drawing them.

---

## 6. Panel data per kind

The panel is where the 89% that is not architecture finally has somewhere to
live. Sections are **generic by kind**, so a new service gets a useful panel on
the day it appears rather than on the day someone designs one for it.

| section | source | applies to | state |
|---|---|---|---|
| Identity | scene node | all | built |
| Placement | `position` — kind, scope, anchor, exposure | all | built |
| Attached | child nodes | SERVICE | built |
| Posture | findings by ARN | all | built |
| Cost | recommendations by ARN | all | built |
| Governance | edges: assumes → references, protected-by, encrypted-by | all | built |
| Related / Config | edges: created-from, launched-from | all | built |
| **Members** | cluster edges | ORCHESTRATOR | built |
| **Rules** | ingress/egress | SUPPORTING · firewall | built |
| **Type facets** | `detail_fields.csv` | 13 types, 44 fields | built |

**R7.** Config never appears on the canvas and always appears in the panel of
the thing it configures. An AMI belongs in the detail of the instance it
launched. Built — but note the constraint that shaped it: only 37 of 133
artifacts are reachable from a resource by an edge, so the other 96 need a
second door (the filter panel's CONFIG plane) or they become invisible.

**R8.** IAM is the worked example, since it is 187 of 392 supporting resources:
a resource's panel names the role it assumes **and** that role's attached
policies. Built (two-hop). The same shape should serve security groups (rules)
and KMS (what else this key encrypts).

---

## 7. Criticality and reading order

Two orderings, and they are different questions:

**Reading order (vertical, within a container)** — by exposure, nearest the
internet first. Built. L1 internet → L2 entry → L3 conditional → L4 internal,
then everything off the traffic path.

**Criticality (what a reviewer looks at first)** — not yet built:

| tier | what | why first |
|---|---|---|
| **A — structural** | boundaries, load balancers, compute, storage, databases | if these are wrong, nothing else matters |
| **B — control** | identity, firewall, routing, encryption | decides who reaches tier A |
| **C — operational** | observability, provisioning, config rules | decides whether you would notice |
| **D — provenance** | images, snapshots, versions, templates | evidence, not architecture |

**R9.** Criticality is a filter and an emphasis, not a position. A tier-D
resource does not move when you change tiers; it dims. Position is decided by
scope and exposure alone, or the diagram stops being reproducible.

---

## 8. Layout, sizing, responsiveness

Built and holding:

- **Bottom-up sizing.** A chip has a fixed size, a group is as tall as the chips
  it shows, a container is as big as the grid inside it. The parent never
  divides space among children; children report what they need.
- **Uniform peers stack.** Availability zones are the same kind of thing, so
  they get equal width and one per row.
- **Groups collapse.** Three chips visible, then a count.

Not built:

**R10.** The summary rung. Past ~18 siblings a container should draw its
heaviest 6 plus "+N more" rather than overflow. The ladder exists; this estate
has at most 4 siblings, so the rung has never fired and needs a synthetic
fixture to build against.

**R11.** Export parity. A diagram whose layout depends on viewport width cannot
be exported faithfully. Bottom-up sizing was chosen for this; it needs a test
that renders the same estate at three widths and asserts identical structure.

---

## 9. Decisions — settled 2026-08-08

**Q1. Autoscaling groups: supporting, or config?**
You have said both. Currently SUPPORTING, on the VPC border, with each instance
badged — which matches your earlier "put it on the VPC border and tag each
resource". Now you say config.
*Evidence:* all 3 instances in this estate are claimed by an ASG, and one ASG
*is* the EKS nodegroup. As config it disappears from the canvas and the only
visible grouping of the instance fleet goes with it.
**DECIDED:** ASG stays SUPPORTING · orchestrator *and* becomes the dotted
cluster box of §5 — it is the one cluster container the data actually supports.
Its launch configuration and launch template move to CONFIG.

**Q2. ECR and AMIs: supporting, or config?**
You said "images which support EC2 and containers … these are supporting".
Currently ECR is SUPPORTING · devtools.artifacts (17) and AMIs are CONFIG.
**DECIDED:** both become CONFIG. An image is what a thing was built from —
provenance, and provenance belongs in the panel of the thing it built. Keeping
ECR on the canvas put 16 repositories beside 3 instances and made the registry
look bigger than the fleet.
*Cost accepted:* an unused ECR repository is a real cost finding, so it must
stay reachable through the filter panel's CONFIG plane — R7's "second door".

**Q3. Nodegroups.** Agreed as CONFIG, with one caveat: if EKS is collected
(R6), the nodegroup is the edge that connects cluster to instances. It should be
config *in the panel* and an *edge* in the graph, not deleted.

**Q4. Where do storage and regional services draw?**
You asked for them "behind the VPC". **DECIDED:** below is correct and stays. Vertical is the traffic path, so
below the VPC already means downstream of it.

---

## 10. Prerequisites and blockers

| # | blocker | blocks | status |
|---|---|---|---|
| B1 | `console/` on :3100 shadows the real app | every review | open — needs your call to delete |
| B2 | `eks.cluster` collects 0 with no failure logged | §5 EKS box | **fixed** |
| B3 | ECS task/service edges absent | §5 ECS box | partly — cluster now collected, tasks still 0 |
| B4 | Step Functions invoke edges absent | §5 workflow box | partly — machine collected, targets still 0 |
| B5 | Listener/stage owner edges absent | R3 | open |
| B6 | Catalog aliases collide on `(service, operation)`; the loser returned `[]` silently | unknown breadth | **fixed — now counted** |
| B7 | 70 types skipped as `NoParentAvailable` marked benign | unknown breadth | open |

### What B2 actually was

Not the alias collision. `extract_items` ended with
`[c for c in current if isinstance(c, dict)]`, and **`eks.list_clusters` returns
`{"clusters": ["onam-eks-cluster"]}` — a list of names, not of objects.** Every
type whose list operation returns bare identifiers was dropped on the floor:
collected zero, logged nothing, and looked exactly like an account that owns
none of them.

The cluster was there the whole time. It is called `onam-eks-cluster`.

**Fixed**, and the fix is general rather than per-service: bare identifiers are
kept, and normalised into an item using the catalog's own `id_field` /
`arn_field`, with an `arn:` prefix deciding which. Result on re-collection:

| | before | after |
|---|---|---|
| assets | 827 | **871** |
| types with assets | 114 | **119** |
| EKS clusters | 0 | **1** |
| Step Functions state machines | 0 | **1** |
| ECS task definitions | 0 | **1** |
| DynamoDB tables | 0 | **10** |
| S3 buckets | 42 | **55** |

### The three silences, now separated

A type producing nothing had one indistinguishable outcome. It now has three,
each counted in `collection.json`:

| outcome | meaning | this estate |
|---|---|---|
| **failure** | the API refused | 1880 |
| **barren** | the call answered and produced nothing usable | **690 across 596 types** |
| **skipped** | another type had already made the identical call | **266 across 47 types** |

690 barren is not 690 bugs — most are genuinely empty in this account. The point
is that it is now a number someone can work through rather than an absence
nobody can see. This is the single highest-value fix in the project so far, and
every "where is my X" question we have had bottomed out here.

---

## 11. Work breakdown by discipline

| # | work | discipline | depends on |
|---|---|---|---|
| W1 | Retire `console/`, one console on one port | build / repo hygiene | — |
| W2 | Fix silent-empty collection; make a zero-result call distinguishable from a zero-resource account | **data collection** | — |
| W3 | Collect EKS clusters, ECS services/tasks, Step Functions targets; emit membership edges | **data collection** | W2 |
| W4 | Settle Q1–Q4; apply to `topology_binding.yaml`; classify every remaining type | **catalog / taxonomy** | your call |
| W5 | Cluster containers: dotted box spanning member zones, members keep placement | **topology engine** | W3, W4 |
| W6 | PART-without-host becomes a reported error | **topology engine** | — |
| W7 | Summary rung + export-parity test | **topology engine + QA** | — |
| W8 | Panel: Members, Rules, type facets from `detail_fields.csv` | **information design** | W4 |
| W9 | Criticality tiers as emphasis and filter, never position | **information design** | W4 |
| W10 | Dotted-container rendering, responsive behaviour at three widths | **frontend** | W5 |
| W11 | Determinism and classification tests for all of the above | **QA** | each |

**Agreed order: W2 → W3 → W4 → W5/W6 → W8/W9 → W10 → W7.**

Collection first, because nothing else in this plan is worth building on data
that is silently absent. A cluster box drawn from a name instead of an edge
would be right in this account and wrong in the next one, which is the failure
this whole engine exists to avoid.


---

## 12. Enhancement and cleanup plan

Written after §11's W2/W3 landed. Cleanup first, because three of the four
cleanup items are *causes* of things on the enhancement list.

### Cleanup

**C1. Retire `console/`.** 429 MB, untracked, serves a superseded UI on :3100
under the same name as the real one. Blocks nothing technically and has cost
three review cycles. **Needs an explicit go-ahead — untracked means gone.**

**C2. Collapse 18 catalog alias pairs.** Two keys, one AWS call, one response
path: `eks.nodegroup` / `eks.eks_nodegroup`, `iam.saml_provider` /
`iam.iam_saml_provider`, and 16 more. One wins the call and the other reports
zero. Which survives is decided by how many *other* catalogs already reference
it, not by taste.

**C3. `cloudwatch.alarm` is a real bug, not an alias.** `describe_alarms`
returns `MetricAlarms` **and** `CompositeAlarms` — two genuine resource types
from one call. Both catalog keys point at `CompositeAlarms`, so **metric alarms
have never been collected in this project**, and the dedup then silenced one of
the two. Fix the path; keep both keys.

**C4. Memoise call pages instead of returning `[]`.** C3 proves the case: two
types can legitimately share one call and read different parts of the response.
A cache that returns empty to the second caller is not a cache, it is data loss.
With C2 removing the true duplicates, memoising cannot produce duplicate assets.

**C5. Persist `out/barren.json`.** 596 barren types are currently a number, not
a list anyone can work through. The detail exists in memory and is thrown away.

**C6. Renderer hygiene.** `LayerBadge` and `CATEGORY` are imported and unused
since the label consolidation; 302 formatting errors and 2 expression-statement
warnings.

### Enhancement

**E1. Cluster containers (W5).** A dotted box spanning the zone lanes its
members occupy. Autoscaling groups support this today — 16 member edges, and
`cluster` already populated on every instance. EKS and ECS follow once E2 lands.

**E2. Membership edges (W3 remainder).** ECS services and tasks, Step Functions
targets, EKS nodegroups. The clusters are collected now; what they contain is
not. Per R5 this comes from edges, never from names.

**E3. PART-without-host is an error (W6).** Two listeners and two API stages are
components of nothing.

**E4. Panel: Members and Rules (W8).** An orchestrator lists what it drives; a
security group lists its rules.

**E5. Criticality as emphasis (W9).** Tiers dim and filter; they never move a
box.

**E6. Summary rung and export parity (W7).**

### Order

`C2 → C3 → C4 → C5 → C6 → E1 → E2 → E3 → E4 → E5 → E6`, with C1 whenever you
say. Cleanup is first because C2/C3/C4 are one interlocking change to how a
call maps to a type, and E2 collects into that same path.


---

## 13. Cleanup results — 2026-08-08

C2–C6 landed. Three of the four cleanup items turned out to be causes of
missing data rather than tidiness, which is why they were sequenced first.

### What the catalog was hiding

| defect | found | effect |
|---|---|---|
| 18 alias pairs — same call, same response path | `eks.nodegroup` / `eks.eks_nodegroup` + 17 more | one of each pair reported zero forever |
| `cloudwatch.alarm` pointed at `CompositeAlarms` | 1 key, wrong path | **metric alarms had never been collected in this project** |
| 77 keys de-pluralised by chopping a letter | `event_bus` → `event_bu`, `..._status` → `..._statu` | 4 were phantom duplicates of the correctly spelled key next to them |
| `ec2.security_group_rule` read `SecurityGroupRuleArn` | AWS returns `SecurityGroupRuleId` and no ARN | **228 real rules extracted, built no asset, vanished silently** |
| `call()` returned `[]` to a second reader of the same call | design | data loss dressed as a cache |

The security group rules matter beyond the count: they are exactly the data
E4's **Rules** panel section needs, and they were being fetched and thrown away
on every run.

### Collection, before and after

| | start of day | now |
|---|---|---|
| assets | 827 | **1135** |
| types with assets | 114 | **123** |
| EKS clusters | 0 | 1 |
| Step Functions state machines | 0 | 1 |
| security group rules | 0 | 228 |
| metric alarms | 0 | 1 |
| DynamoDB tables | 0 | 10 |

### One bug I introduced and caught

Recording a skipped call from inside `call()`'s own lock deadlocked every
worker in the pool — `_lock` is a plain `Lock`, not an `RLock`. The suite
caught it by hanging rather than failing, which is worth noting: a deadlock has
no assertion to fail. There is now a test that runs `call()` on a thread and
asserts it returns within five seconds.

### Barren, triaged

778 barren is not 778 bugs. The breakdown:

| | count | verdict |
|---|---|---|
| child call, parent has none (`InstanceProfiles`, `AttachedPolicies`, …) | ~740 | genuinely empty — expected |
| items extracted, no asset built | 19 | **real defects** — one was the 228 rules |
| no `items_for` at all | 17 | catalog gaps |

**R12.** Barren should record whether a call was a root or a child call, so the
~740 expected-empty child calls stop burying the ~36 that are defects. Not yet
built.

### Still open

- **C1** — `console/` on :3100. Needs your go-ahead; untracked means gone.
- **18 remaining `no asset built` types** — `iam.access_key`,
  `ssm.patch_baseline` (17 items), `securityhub.standard` (13). Same class of
  defect as the security group rules, each needing its own recipe check.
- **17 types with no `items_for`** — including `sts.caller_identity`,
  `organizations.organization`, `cloudfront.function`.


---

## 14. Everything closed out — 2026-08-08

### Delivered

| # | work | outcome |
|---|---|---|
| C1 | retire `console/` | :3100 stopped; 429 MB moved to `~/Desktop/cloud-estate-archive/`, not deleted — it was untracked |
| C2–C6 | catalog and renderer cleanup | see §13 |
| R12 | barren tagged root vs child | 1051 barren → **586 root**, the only ones worth reading |
| E1 | cluster containers | dashed box per container, per owner; members keep their placement |
| E2 | membership edges | EKS nodegroups collected and linked; **the cluster now owns 4 instances, 3 scaling groups, 2 security groups** |
| E3 | hostless components reported | **19 orphans** named in `scene.meta.orphan_components` |
| E4 | Members and Rules panel sections | backed by a new `detail_fields.csv`; 270 nodes carry detail |
| E5 | criticality tiers | a Focus control that dims — never moves, never hides |
| E6 | summary rung verified | `npm run check`, no test framework added |

### Two design decisions worth recording

**A cluster box draws per container, not spanning them.** A fleet whose members
sit in three zones *is* three groups of instances that share an owner, and the
repeated labelled box says exactly that. A single box stretched across three
stacked zones would have to cross the zone boundaries to do it, claiming a
containment that runs the wrong way. Dashed, because a cluster owns its members
but traffic does not cross into it — solid would put it in the same visual
class as a VPC, which is the one thing it is not.

**Criticality dims; it never moves.** Position stays a function of scope and
exposure alone. If a tier could relocate a resource, changing what a reader
cares about would change the diagram, and two people would be looking at
different pictures of the same estate.

**`detail_fields.csv` is how a field reaches a panel.** The raw API payload is
kept on every asset and dropped at the scene boundary — a scene carrying 4743
types' worth of payloads is not a scene. But some fields *are* the answer: a
security group rule without its ports is a row that says nothing. So a catalog
decides which survive, which is the same rule the rest of this engine follows.

### A bug I introduced, and what it cost

Matching child parameters case-insensitively fixed the EKS nodegroups and broke
the collection budget: **53 collectable child types ask for a parameter called
`id`**, and matched loosely against every asset that has one, that is a cross
product rather than a lookup. A run that took five minutes was still going at
twenty-three when I killed it.

The fix keeps the convention that worked — `clusterName` finds the cluster —
and refuses it for bare names that identify nothing. Both halves are tested
together, so the guard cannot be tightened until it undoes the fix it came
from.

### Where things stand

| | start of session | now |
|---|---|---|
| assets collected | 827 | **1141** |
| types with assets | 114 | **125** |
| tests | 236 | **256** + `npm run check` |
| consoles running | 2 | 1 |

### Still open, deliberately

- **586 root-barren types.** Now a readable list in `out/barren.json`. The
  19 "items extracted, no asset built" are the same defect class as the 228
  security group rules and each needs its own recipe check.
- **19 orphan components** — 13 interfaces, 2 volumes, 2 API stages, 2
  listeners with no collected owner edge.
- **ECS and Step Functions cluster boxes.** ECS is genuinely empty in this
  account (1 cluster, 0 services, 0 tasks). Step Functions targets live inside
  a 20 KB state-machine definition and need a parser, which is real work rather
  than a catalog row.


---

## 15. Open items closed — 2026-08-08

Everything §14 left open is fixed. Four of the six turned out to be different
symptoms of one habit: **a defect that produces no error is invisible until
something counts it.**

### The eighteen broken identity recipes

Each named a field AWS does not return, so real items extracted and no asset
was built. Diagnosed by calling every operation and reading the first item's
keys, then repaired against ground truth:

| | declared | actually returned |
|---|---|---|
| `athena.data_catalog` | `Name` | `CatalogName` |
| `iam.access_key` | `Id` | `AccessKeyId` |
| `ssm.patch_baseline` | `Id` | `BaselineId` |
| `securityhub.standard` | `StandardsSubscriptionArn` | `StandardsArn` |
| `xray.sampling_rule` | `RuleName` | `SamplingRule.RuleName` — **nested** |
| …14 more | | |

**48 assets recovered**, including an IAM access key nobody could see. The
nested case needed a second fix: `_identity` read fields flat, so a wrapped
payload resolved to nothing. It now uses the dotted reader the rest of the
collector already had.

`ivs.*` arrived with no taxonomy binding at all — caught immediately by the
binding-coverage test, which is what that test is for.

### Orphan components: 19 → 0

Not one fix, four. And the first finding was that most of them were never
defects:

| | count | verdict |
|---|---|---|
| managed-service interfaces (`amazon-elb`, `amazon-rds`, EKS's own account) | 8 | **not orphans** — a service's footprint in our subnet |
| genuinely detached (`status: available`) | 1 | **not an orphan** — correct placement, and a cost finding |
| interfaces attached to a collected instance | 7 | missing `Attachment.InstanceId` rule |
| listeners | 2 | missing `LoadBalancerArn` rule |
| API stages | 3 | three separate defects, below |

A resource's own data settles which it is, so the scene now reports
`orphan_components`, `unattached_components` and `service_footprints`
separately. Counting them as one number is what made ten non-problems look
like a bug.

### The API stage, which was wrong three ways

1. **Collected as a root type**, though `get_stages` requires an `ApiId`. Now a
   child.
2. **Two stages named `$default` collapsed onto one scene node** — two real
   resources drawn as one, silently. A child's id is unique within its parent
   and nowhere else, so the synthetic id now carries the parent.
3. **Nesting refused on a depth comparison across two different axes.** `R1` is
   8 and `L6` is 6, but that 8 means "not in the network at all", not "deeper
   than a volume" — so the layer table claimed an API Gateway is deeper than
   its own stage. Depth is now compared only within an axis; across axes the
   cycle check is the real protection and is sufficient.

The third one was the interesting bug: the guard was written to stop a
volume↔instance loop recursing forever, and it did that correctly. It just had
no business answering a question about a regional service.

### EKS, end to end

`list_nodegroups` returns names, so a nodegroup arrived as `{name}` and nothing
else — enough to say it exists, not enough to say what it holds. A new
`enrich_specs.csv` declares one describe call per item for the types that need
it, and the node pool now carries `clusterName`, `subnets`, `nodeRole` and
`resources.autoScalingGroups`.

That last field is the whole point: **it is the only collected link between an
EKS cluster and the EC2 instances that run it.** The chain now resolves as
edges rather than by matching a name — cluster → nodegroup → scaling group →
instances.

*(An `str.format` bug cost a round here: the params are JSON, so their own
braces were read as format placeholders. Explicit substitution now.)*

### Where things stand

| | start of session | now |
|---|---|---|
| assets collected | 827 | **1,185** |
| types with assets | 114 | **143** |
| orphan components | — | **0** |
| tests | 236 | **260** + `npm run check` |
| consoles running | 2 | 1 |

### Genuinely still open

- **569 root-barren types.** Now zero of them are identity defects — the
  remaining ones are empty responses or types with no `items_for`. `ivs.stream_key`
  is the single new no-asset-built, a child type surfaced by the repairs.
- **9 types with no `items_for`** — `sts.caller_identity`,
  `organizations.organization`, `cloudfront.function` and six others.
- **Step Functions membership.** The state machine is collected and its
  definition can now be enriched, but nothing parses the 20 KB of JSON to find
  the resources it invokes. That is a parser, not a catalog row.
- **ECS is genuinely empty** — 1 cluster, 0 services, 0 tasks. Nothing to draw.


---

## 16. End-to-end review — 2026-08-09

A full sweep of the pipeline. The model itself is in good shape; the gaps were
around it.

| | |
|---|---|
| collection | 1,185 assets · 143 types · 2,465 calls |
| scene | 608 edges · **0 orphans** · **0 unplaced** · six kinds populated |
| classification | **0 unclassified** of 3,070 types · 60 subcategories, all populated |
| contract | clean — all 20 position fields the engine emits are read by the renderer |
| tests | 282 Python + `npm run check` |

### Closed: the model was partly decorative

Six declarations read as configuration and no code consulted any of them. See
`diagram-layout-spec.md` §4f-i. One was not cosmetic: **the `isolated` segment
tier was unreachable**, so a segment with routes but none to the internet was
reported as `unknown` — which the model itself defines as an *absence of data*.
Two different facts, one label.

A test now asserts that every key under a settings block is reachable from code
or lives under `note:`. It immediately caught a seventh declaration and then a
regression in the fix for the first six.

### Still open, ranked by risk

**1. The renderer is untested.** 2,775 lines, one 12-function check. Four real
bugs in a single day and tooling caught one: a TDZ error found by loading the
page, a name collision found by reasoning, a variable in the wrong function
found by `tsc`, and a role name leaking into a heading found by grepping the
rendered HTML. This is now the highest-risk area by a distance, and closing it
means a test-runner decision for `console-app`.

**2. Collection health.** 569 root-barren types and 421 non-benign failures,
unexamined. The last pass through that bucket produced 228 security group rules
and an IAM access key, so there is likely more real data hiding in it.

**3. Single-estate blindness — structural.** One account, one VPC, one region.
Never exercised by real data: the summary rung (needs >18 siblings), adjacency,
the ECS and Step Functions cluster boxes, family grouping, multi-account. Three
features have been deliberately deferred on this basis. It is a ceiling on
confidence that no amount of code removes.

### Two habits this codebase invites

Worth naming, because each produced several defects:

- **A count that looks fine because records are in it.** 27 wrappable security
  groups (really 2), `integration.messaging` at 312 (really 20), 494 tags
  (really 123). Whenever a number looks good, check what kind of thing is in it.
- **A declaration nothing reads.** `render: detail`, and then six more. The
  model is the multi-cloud contract; a setting that does nothing is worse than
  no setting, because someone will change it and believe they have.
