# Sprint plan — border placement, internet exposure, onboarding resume

Status: **plan, agreed sequence, not yet built.**

Three streams, run in this order, all inside `cloud-estate`. Nothing is ported
into a second project: threat-engine contributes **rule data and a rule format**,
never a running service.

| Sprint | Delivers | Depends on | Size |
|---|---|---|---|
| **1** Border | Org, CloudFront and DNS on the account's top line | — | small |
| **2** Exposure facts | Per-resource "is this actually reachable" | — | medium |
| **3** Hop chain | `internet → CF → LB → EC2` drawn on the diagram | 1, 2 | medium–large |
| **4** Run & test | Live pipeline run, browser verification | 1–3 | small |
| **5** Onboarding resume | Tables, store, API router for account onboarding | — | medium |

Sprints 1 and 2 are independent and could run in parallel. Sprint 5 is already
half-built (§5) and is deliberately last, per the agreed order.

---

## Sprint 1 — The three on the account's top border

### The change is in the MODEL, not the renderer

`EdgeStrip` already draws things on a container's top line — today the account's
carries `network · igw`, `network · tgw`, `network · direct-connect`. So this is
an anchor change (`in` → `edge.n`), not new rendering machinery.

### Stories

| | Story | Notes |
|---|---|---|
| 1.1 | `cloudfront.distribution` and `route53.hosted_zone` become `door.ingress`, anchored `edge.n` | §4b's door test is *"I am a way through it"*. A CDN and public DNS genuinely are, so this is more correct than `resident.edge` is today — not a fudge to get a position. |
| 1.2 | `organizations.organization` gets a **boundary tab** on the top-left, staying `boundary` | It is **not** a door. A role name must match its kind and there is a test enforcing it, so calling it `door.*` would break the taxonomy to buy a position. A tab says "this account sits inside this org" without claiming it is a way through. |
| 1.3 | `EdgeStrip` learns left / centre / right alignment | It knows `side` and `centreOut` only. Org anchors left, CF and DNS right. |
| 1.4 | Exposure levels re-checked after the kind change | §4e: **only residents carry a level**, enforced by test. Moving CF from `resident` to `door` means it must *lose* its L1, or that test fails — and the failure is the correct one. Where the L1 fact should now live is a real decision, not a mechanical fix (see below). |

### The one open question in this sprint

CloudFront is currently the estate's L1 anchor — the thing exposure is measured
*from*. Reclassifying it as a door removes its right to carry a level. Two ways
out, and 1.4 has to pick one:

- **(a)** The internet origin from Sprint 3 becomes the L1 anchor, and doors
  simply have no level. Cleaner model, but Sprint 1 then temporarily has no L1
  until Sprint 3 lands.
- **(b)** Doors carry a level after all, and §4e's rule is amended to
  "residents and doors". Weakens a rule that currently has a clean test.

Recommend **(a)**, and accept the gap between sprints. Sequencing 1 before 3 is
what creates it, and it is one release, in a view nobody is depending on yet.

### Gate

Org reads on the top-left, CF and DNS on the top-right, kind and exposure tests
green, and the account box's own layout unchanged below the border line.

---

## Sprint 2 — Internet exposure, as a fact per resource

### What we have and why it is not enough

§4e declares L1–L4 **per role** in `model.yaml`. That is a *class* statement —
"an instance is conditionally reachable" — and the spec is explicit that L3 is
deliberately not split, because "that 'only if' is where nearly every exposure
finding comes from".

So today the diagram can colour by exposure and cannot answer **which EC2 is
actually reachable**. That is the gap this sprint closes.

### What comes from threat-engine

`catalog/rule/network_exposure/aws/` — eight YAML files, three tiers:

- **Tier 1** — structurally public types, catalog flag only, no field check.
  CloudFront, API Gateway.
- **Tier 2** — per-resource field checks, one file per service: `tier2_ec2`,
  `tier2_elb`, `tier2_rds`, `tier2_lambda`, `tier2_storage`, `tier2_eks_ecs`.
- **Tier 3** — `traversal_steps`, deferred to Sprint 3.

This is **data, not code**. The rules are declarative; what we write is the
evaluator that runs them against our own asset emit.

### Stories

| | Story |
|---|---|
| 2.1 | Copy the AWS YAML catalog into `engines/exposure/rules/aws/`, unchanged where possible, with provenance recorded |
| 2.2 | Rule schema + loader + a validation pass that fails loudly on an unparseable or unbound rule |
| 2.3 | Tier 1 evaluator — structural, from the type alone |
| 2.4 | Tier 2 evaluator — `required_emitted_fields` resolved against the asset emit, then `exposure_conditions` |
| 2.5 | Field-resolvability audit: every field a rule needs, proven present in our emit |
| 2.6 | Persist a verdict per asset — exposed / not / undetermined, with the rule id that decided it |
| 2.7 | Fixtures per rule: positive, negative, and **empty** |

### The story that will actually cost time

**2.5.** threat-engine's rules name fields from *its* inventory shape
(`resource_type: ec2_instance`, underscored). Ours is `ec2.instance`, dotted,
with a different emit. Every `check_field` has to be proven resolvable against
what our collector actually returns, or a rule silently never fires — which
reads as "nothing is exposed", the most dangerous wrong answer this feature can
give.

**Undetermined must be its own verdict**, distinct from "not exposed". A rule
that could not run because a field was missing has not cleared the resource.

### Gate

Every rule has three fixtures and passes. The field audit reports 100% of
required fields resolvable, or names the gaps. No rule fires on everything, and
no rule never fires.

---

## Sprint 2b — What "enterprise" changes about the verdict

Added after the field audit. The pragmatic design — *"if the payload exists, an
absent optional field is a negative"* — is the right call for a tool one team
runs against its own estate. It is the wrong call for a tool an enterprise
buys, and the difference is worth stating precisely rather than hand-waving at
"more rigour".

### The one rule that changes everything

**A verdict may never be inferred from an absence.**

An auditor's first question about any exposure report is *"what did you not
check, and why"*. A tool that silently converts "I could not tell" into "not
exposed" cannot answer it, and every number it produces becomes unfalsifiable.
Worse, it fails in the safe-looking direction: the estate looks cleaner than it
is, and nobody goes looking.

So optionality is **declared**, not inferred. Each tier-2 rule states which of
its fields may legitimately be absent and what an absence means:

```yaml
required_emitted_fields:
  - name: association
    optional: true
    absent_means: not_exposed   # an ENI with no public association has none
  - name: public_ip_address
    optional: false             # absent -> undetermined, never cleared
```

This diverges from threat-engine's catalog. That is accepted: the catalog
becomes **ours**, with provenance recorded per rule, because a verdict we cannot
defend is worth less than one we had to edit a YAML file to earn.

### Four verdicts, not two

| Verdict | Means | Counts toward |
|---|---|---|
| `exposed` | a rule fired and its conditions held | findings |
| `not_exposed` | a rule ran fully and its conditions did not hold | coverage |
| `undetermined` | a rule could not run — field absent, collection failed | **coverage gap** |
| `not_applicable` | no rule covers this resource type | **coverage gap** |

The last two are the ones that make the report defensible, and they are the two
a startup build leaves out. `not_applicable` is not a failure — it is the honest
statement that 4,647 catalog types exist and 27 rules cover some of them.

### Every verdict carries its provenance

Enough to reconstruct the decision without re-running the scan:

```
resource_uid, tenant_id, scan_id, rule_id, rule_hash,
verdict, origin_type, severity,
fields_read: {name: value}, evaluated_at
```

`rule_hash` is the content hash of the rule that produced it. Without it, a
verdict from March cannot be tied to the rule text that existed in March —
which is the difference between an audit trail and a log.

### Coverage is reported with its denominator

The headline number is never "N exposed". It is:

> **N exposed** · M evaluated · K undetermined · J not applicable — of T resources

A report that states only the numerator is the same defect as a list that stops
at 250 rows without saying so. The console already holds this line elsewhere
(`showing 250 of 1,030 — filter to narrow`), and this is the same rule applied
to risk.

### Revised Sprint 2 stories

| | Story | Changed? |
|---|---|---|
| 2.1 | Port the catalog | done |
| 2.2 | Loader, normaliser, `validate()` | done |
| 2.5 | Field resolver + audit | done |
| **2.3** | Tier 1 evaluator | — |
| **2.4** | Tier 2 evaluator, four verdicts, reason codes | **widened** |
| **2.6** | Verdict persistence with full provenance + `rule_hash` | **widened** |
| **2.8** | Declare optionality on every tier-2 field | **new** |
| **2.9** | Coverage report: exposed / evaluated / undetermined / N-A over total | **new** |
| **2.10** | Determinism test: same input, same verdicts, twice | **new** |
| 2.7 | Fixtures per rule: positive, negative, empty | — |

### Revised gate

Every rule fixtured three ways; no rule fires on everything or never; the
coverage report states all four denominators; and two runs over one estate
produce byte-identical verdicts.

---

## Enterprise bar — what it means for the other sprints

Recorded here so it is decided once rather than re-argued per sprint.

- **Multi-tenancy is not optional.** Every verdict, every asset and every
  finding is scoped by `tenant_id`. Sprint 5 already builds this for accounts;
  Sprint 2's tables must not be written without it.
- **Append-only per scan.** A verdict is never updated in place — a new scan
  writes new rows. "What did this look like in March" is a query, not a
  restore.
- **Rules are versioned content.** `rule_hash` on every verdict, and a rule
  change is a new hash rather than a silent edit.
- **RBAC before exposure.** Reachability findings are the most sensitive thing
  this platform produces — a list of exactly how to get in. They must not ship
  behind the bearer token that is currently the whole auth story.
- **Determinism is a test, not an aspiration.** The layout engine already runs
  under three hash seeds for this reason; the evaluator gets the same treatment.
- **Scale target stated.** This estate is 1,033 resources. The evaluator is
  designed and tested against 100k, because the shape of a per-resource
  Python loop that is fine at 1k is not fine at 100k.

## Sprint 3 — The hop chain

### Stories

| | Story |
|---|---|
| 3.1 | An `internet` origin node — drawable, anchored beyond the account's north edge, and the L1 anchor per Sprint 1's decision (a) |
| 3.2 | Tier 3 evaluator: walk `traversal_steps` over `inventory_edges` |
| 3.3 | Path assembly — `internet → hop → hop → target`, with the rule and the condition that justified each hop |
| 3.4 | Render the chain on the canvas, reusing `trace.ts` geometry and the pinned-trace register |
| 3.5 | Panel section: the full path for a selected resource, each hop stating why |

### Two design notes

**A path is evidence, not decoration.** Each hop carries the rule id and the
field that satisfied it, so "why is this instance exposed" is answerable from
the picture rather than from a rerun. This is what separates it from the hover
traces, which answer "what is this connected to".

**Reuse the pinned-trace machinery from the last sprint.** Chains are exactly
the thing a reader wants kept on screen while looking elsewhere, and pinning,
scroll re-measurement and the above-panel z-order already work.

### Gate

`internet → CloudFront → load balancer → EC2` drawn end to end on the live
estate, every hop justified by a named rule, and the chain surviving scroll and
a panel opening over it.

---

## Sprint 4 — Run and test

The explicit checkpoint. Full pipeline run against the live account, browser
verification of both new surfaces, screenshots, and a written read of what the
exposure evaluator found versus what we believed before it existed.

**Expect this to find rule gaps rather than code bugs.** The interesting output
is the diff between "types we assumed were exposed" and "resources the rules
prove are exposed".

---

## Sprint 5 — Onboarding, resumed

Already built and tested:

- `providers/aws/runtime/credentials.py` — external-id derivation, assume-role,
  access-key fallback, `session_for`, `whoami`. 27 tests.
- `providers/aws/onboarding/cloud-estate-scan-role.yaml` — read-only role,
  triple-enforced.
- Session threaded through `cmd_collect` and `discover.run`.

Outstanding:

| | Story |
|---|---|
| 5.1 | Migration 009 — `tenants`, `cloud_accounts` |
| 5.2 | `store/accounts.py` — CRUD through the existing backend split |
| 5.3 | Secrets Manager write-through from the API; the row keeps a ref only |
| 5.4 | `api/routers/accounts.py` — onboarding API, AWS only |
| 5.5 | CloudFormation template served with `ExternalId` pre-filled |
| 5.6 | Per-account scan trigger, using `session_for` |
| 5.7 | Tests: store, API contract, an end-to-end onboard → scan against a fixture |

**Blocking config:** `EXTERNAL_ID_SECRET` must be set, identically on every
replica, before any of this works. `derive_external_id` raises rather than
falling back — a predictable external ID is the same as none.

---

## Standing rules for every sprint

Carried from the personalisation sprint, because they worked:

1. **Plan → implement → test, per story.** No story is done without its gate.
2. **Pure logic in its own module, tested without a browser or a network.**
   `pack.ts`, `grid.ts`, `credentials.py` are the pattern.
3. **A browser driver per user-visible surface**, in `console-app/scripts/`,
   run before claiming a UI feature works. Four already exist.
4. **Every cap and every skipped rule is stated on screen**, never silent.
5. **No preference, no change.** Any new reader-facing behaviour must leave the
   default render identical.
