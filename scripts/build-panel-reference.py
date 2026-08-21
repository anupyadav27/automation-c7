#!/usr/bin/env python3
"""
What every resource panel shows, and where each column comes from.

    python3 scripts/build-panel-reference.py > docs/panel-columns.md

A panel is built from four tiers. Three of them are the same for every resource
in the estate — identity, composition and governance are structural, so they are
stated once here rather than declared 139 times. Only the middle tier varies by
type, and that is `detail_fields.csv`, which this reads.

Nothing here is decided by this file. It reads the binding for kind and domain,
the catalog for what is collectable, `detail_fields.csv` for the columns, and
`enrich_specs.csv` for which call fetches them, then prints what those already
say. A hand-kept list of 139 panels is wrong within a week.

Coverage is reported honestly, including the types with no columns and the
reason each has none — a reference that silently omits its gaps reads as
complete when it is not.
"""
import collections
import csv
import json
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The generator decides which fields earn a column. Importing its classifier
# rather than re-deriving one is what keeps this reference from disagreeing
# with the catalog it documents.
from importlib import import_module  # noqa: E402

classify = import_module('build-detail-fields').classify

CATALOG = os.path.join(ROOT, 'providers', 'aws', 'catalog')
BINDING = os.path.join(CATALOG, 'topology_binding.yaml')
FIELDS = os.path.join(CATALOG, 'detail_fields.csv')
ENRICH = os.path.join(CATALOG, 'enrich_specs.csv')
ASSETS = os.path.join(ROOT, 'out', 'assets.json')

# The three structural tiers. Every panel has them, whatever the resource, so
# they are described once. Only Tier 2 is per-type.
TIERS = [
    ('1', 'Identity and placement',
     'name · type · ARN · account · region · AZ · the containers it sits in · tags',
     '`inventory_assets` columns',
     'the envelope every asset carries. Present for all 139 types, no catalog needed'),
    ('2', 'What this resource IS',
     'per type — see the table below',
     '`metadata`, written from `rule_diagram_discovery`',
     'the only tier that varies. An EC2 instance shows its type and state; a '
     'bucket shows encryption and versioning'),
    ('3', 'What it is made of',
     'child resources — an instance\'s ENIs and volumes, a cluster\'s node groups',
     '`out/edges.csv`, outgoing',
     'composition, read from edges rather than declared. A field holding a list '
     'is a child, not a column'),
    ('4', 'What governs it, and what it governs',
     'security groups · IAM roles · KMS keys · log destinations',
     '`out/edges.csv`, both directions',
     'the supporting services, seen from the resource rather than from the '
     'border. Incoming edges are phrased from this end: a security group '
     '*protects* the interfaces whose edges point at it'),
]

# Why each rejection exists, keyed by the exact string `classify` emits. The
# counts beside them are measured, not stated, so a rule that stops firing
# shows up as a zero rather than as prose nobody rechecked.
SKIP_NOTE = {
    'already in the envelope':
        'Tier 1 already shows it. Matched on value, not on name — '
        '`TransitGatewayId` and `FileSystemArn` are identity wearing a service prefix',
    'a list or nested object — Tier 3 reads it':
        'a field holding a list is composition. `BlockDeviceMappings` is the '
        'volumes, and volumes are children with panels of their own',
    'noise':
        'request bookkeeping — tokens, markers, checksums — and the long-form '
        'text that belongs in a payload viewer rather than a column',
    'about the call, not the resource':
        'the `ResponseMetadata` subtree: HTTP status, host id, retry count. A '
        'panel showing `http_status_code: 200` is reporting on itself',
    'numeric twin of a named state':
        '`State.Code` = 16 beside `State.Name` = "running" is one fact in two '
        'forms, and nobody reads the number',
    'too long to be a cell':
        'longer than a cell can hold. SNS calls its 468-character IAM document '
        '`Policy`, while `BlockPublicPolicy` is a boolean — length separates '
        'them where no name pattern can',
    'empty across the estate':
        'a column no resource in this account can fill',
}

KIND_NOTE = {
    'resident': 'drawn as a box in the layered diagram',
    'boundary': 'drawn as a container everything else sits inside',
    'part': 'drawn inside its parent',
    'door': 'drawn on the north border — traffic crosses here',
    'rule': 'drawn as a rail tab — applies to things rather than running',
    'record': 'not drawn; carried for reference and edges',
}


def rows(path):
    with open(path, newline='') as fh:
        return [r for r in csv.DictReader(fh) if any(r.values())]


def load_estate():
    """Live counts, so the reference says what is real rather than what is possible."""
    if not os.path.exists(ASSETS):
        return {}, {}
    with open(ASSETS) as fh:
        assets = json.load(fh)
    assets = assets if isinstance(assets, list) else assets.get('assets', [])
    counts = collections.Counter(a['resource_key'] for a in assets)
    payloads = collections.defaultdict(list)
    for a in assets:
        envelope = {str(a.get(k) or '') for k in ('id', 'arn', 'name')} - {''}
        payloads[a['resource_key']].append((a.get('raw') or {}, envelope))
    return counts, payloads


def why_empty(raws):
    """
    Why a type has no columns — answered by the generator, not guessed here.

    The first version of this guessed from the payload's key names and said
    "everything it carries is a list" about `ChannelArn`, a string. Asking the
    code that made the decision is the only way the reference cannot drift from
    it.
    """
    _, rejected = classify(raws)
    if not rejected:
        return 'the list call returns nothing at all'
    counts = collections.Counter(rejected.values())
    return ' · '.join(f'{why} ({n})' for why, n in counts.most_common(3))


def main():
    binding = yaml.safe_load(open(BINDING))
    overrides = binding.get('overrides') or {}
    services = binding.get('services') or {}
    fields = rows(FIELDS)
    enrich = rows(ENRICH)
    counts, payloads = load_estate()

    by_type = collections.defaultdict(list)
    for r in fields:
        by_type[r['resource_key']].append(r)
    # The spine wins over the binding role. `ec2.vpc` is bound as `record`, but
    # the spine names it as the `network` container and the engine draws it as
    # one — filing it under "not drawn" would be a plain falsehood.
    spine = {t: level for level, spec in (binding.get('spine') or {}).items()
             for t in (spec.get('types') or [])}

    def role_of(t):
        if t in spine:
            return f'boundary.{spine[t]}'
        return str(overrides.get(t) or services.get(t.split('.')[0]) or '?')

    out = []
    w = out.append
    w('# Resource panel columns')
    w('')
    w('Click a resource in the diagram and a panel opens. This is what it shows,')
    w('for every type in the estate, and where each column is read from.')
    w('')
    w('**Generated** — `python3 scripts/build-panel-reference.py > docs/panel-columns.md`.')
    w('')
    w('---')
    w('')
    w('## The four tiers')
    w('')
    w('Three tiers are structural and identical for every resource. One varies.')
    w('')
    w('| Tier | Shows | Columns | Read from | |')
    w('|---|---|---|---|---|')
    for n, title, cols, src, note in TIERS:
        w(f'| **{n}** | {title} | {cols} | {src} | {note} |')
    w('')
    w('Tiers 3 and 4 are one section in the panel — **Related** — because the')
    w('question is one question: what does this touch, and how. It is drawn as')
    w('a tree, because the hierarchy IS the answer: a key sits under the volume')
    w('it encrypts, an interface under the group that protects it.')
    w('')
    w('```')
    w('Related · 5')
    w('  ▾ attached-to    vol-0f86d867…      100 GB · gp3')
    w('      encrypted-by   ad688fb2-569a…   kms.key')
    w('  ▾ attached-to    eni-054ed2af…      in-use')
    w('      protected-by   eks-cluster-sg…  ec2.security_group')
    w('    assumes        onam-eks-node-…    iam.instance_profile')
    w('```')
    w('')
    w('Every branch opens by default and each one collapses. Measured: 280')
    w('assets reach depth 1, 19 reach 2, 11 reach 3, one reaches 4; the median')
    w('asset has **one** distinct relation. That shallowness is why opening by')
    w('default is safe — and why a security group with ten interfaces still')
    w('needs the collapse, so it cannot push the rest of the panel off screen.')
    w('')
    w('Three rules the walk follows, each pinned by a test in `related.test.ts`:')
    w('')
    w('- **The tree is assembled on keys, not names.** Two EKS nodes share a')
    w('  Name tag, and matching on the displayed name hangs a key under the')
    w('  wrong volume.')
    w('- **Placement is skipped.** Every resource is `contained-in` its subnet,')
    w('  VPC, region and account, and the panel header states all four already.')
    w('- **Incoming edges are inverted.** A security group\'s panel lists what it')
    w('  *protects*. Reusing the outbound word would claim the group is')
    w('  protected by the thing it protects.')
    w('- **A node is visited once.** The graph has 34 bidirectional pairs, and')
    w('  without the guard an instance appears beneath its own volume.')
    w('')
    w('An oversized group collapses to a summary row carrying the true total —')
    w('356 rule records point at one security group, and showing five of them')
    w('without saying so would be a panel that lies. The roll-up happens per')
    w('BRANCH: five interfaces under one group and five under another are two')
    w('groups of five, not one of ten.')
    w('')
    w('---')
    w('')
    w('Tier 2 is the only tier that needs a catalog, because it is the only one')
    w('whose answer differs per resource. `rule_diagram_discovery` holds it, and')
    w('it drives two things at once: which fields `emit` stores in')
    w('`inventory_assets.metadata`, and which columns the panel shows. One list,')
    w('so a field worth storing is a field worth showing.')
    w('')
    w('---')
    w('')
    w('## Where a Tier 2 column comes from')
    w('')
    w('| `source` | Meaning |')
    w('|---|---|')
    w('| `list` | the field arrived in the collector\'s own list or describe call — free |')
    w('| `enrich:<operation>` | it needed a second, per-resource call |')
    w('')
    paying = len({r['resource_key'] for r in enrich})
    w(f'{paying} types pay for a second call — {len(enrich)} calls in all — because')
    w('their list call returns an identifier and little else:')
    w('')
    w('| Type | Second call | Why |')
    w('|---|---|---|')
    for r in sorted(enrich, key=lambda r: (r['resource_key'], r['operation'])):
        w(f'| `{r["resource_key"]}` | `{r["operation"]}` | {r["reason"]} |')
    w('')
    w('---')
    w('')
    w('## Every type, and its Tier 2 columns')
    w('')
    covered = sum(1 for t in counts if t in by_type)
    w(f'{len(counts)} types in the estate; {covered} carry Tier 2 columns and')
    w(f'{len(counts) - covered} do not. The ones that do not are listed after the')
    w('table with the reason — every one of them still has Tiers 1, 3 and 4.')
    w('')

    order = {k: i for i, k in enumerate(
        ['boundary', 'resident', 'part', 'door', 'rule', 'record'])}
    listed = sorted(
        (t for t in counts if t in by_type),
        key=lambda t: (order.get(role_of(t).split('.')[0], 9), role_of(t), t))

    kind = None
    for t in listed:
        k = role_of(t).split('.')[0]
        if k != kind:
            kind = k
            w('')
            w(f'### {kind} — {KIND_NOTE.get(kind, "")}')
            w('')
            w('| Type | n | Domain | Columns | From |')
            w('|---|---|---|---|---|')
        cols = sorted(r['label'] for r in by_type[t])
        srcs = {r['source'].split(':')[0] for r in by_type[t]}
        src = 'list + enrich' if len(srcs) > 1 else next(iter(srcs), 'list')
        domain = role_of(t)
        w(f'| `{t}` | {counts[t]} | {domain} | {" · ".join(f"`{c}`" for c in cols)} | {src} |')

    bare = sorted(t for t in counts if t not in by_type)
    if bare:
        w('')
        w('### Types with no Tier 2 columns')
        w('')
        w('| Type | n | Why |')
        w('|---|---|---|')
        for t in bare:
            w(f'| `{t}` | {counts[t]} | {why_empty(payloads.get(t) or [])} |')

    w('')
    w('---')
    w('')
    w('## How this list is kept true')
    w('')
    w('`scripts/build-detail-fields.py` reads the real payloads in')
    w('`out/assets.json` and proposes columns from what is actually there. It')
    w('never invents a field: a column that cannot be filled reads as "this')
    w('resource has no encryption setting" when the truth is "nobody asked".')
    w('')
    w('It rejects a field for one of these reasons. The counts are measured')
    w('across the estate, so a rule that stops firing shows as a zero rather')
    w('than as prose nobody rechecked.')
    w('')
    w('| Rejected | n | Because |')
    w('|---|---|---|')
    tally = collections.Counter()
    for raws in payloads.values():
        _, rejected = classify(raws)
        tally.update(rejected.values())
    for why, n in tally.most_common():
        w(f'| {why} | {n} | {SKIP_NOTE.get(why, "")} |')
    for why in SKIP_NOTE:
        if why not in tally:
            w(f'| {why} | 0 | {SKIP_NOTE[why]} |')
    w('')
    w('Hand-authored rows win. The generator fills coverage; a human decides what')
    w('a thing is called and why it earns a column, and re-running never')
    w('overwrites that judgement.')
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
