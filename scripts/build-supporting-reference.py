#!/usr/bin/env python3
"""
Every supporting service: its domain, the border it attaches to, the arm it
rides, and its place in the sequence on that arm.

    python3 scripts/build-supporting-reference.py > docs/supporting-services.md

One table, because the question it answers is one question — "where does this
draw" — and four separate tables make a reader join them by hand.

Nothing here is decided by this file. It reads the model for the arms, the
containers and the taxonomy order, the binding for service→role→domain, and the
catalog for what is collectable, then prints what those three already say. It
imports `taxonomy_ranks` from the engine rather than reimplementing it, so the
sequence printed is the sequence drawn — a reference that computes the order a
second way is a reference that will eventually disagree with the diagram.

Written as a generator because a hand-kept list of 170 services is wrong within
a week, and a wrong reference is worse than none.
"""
import collections
import csv
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

from providers.common.topology.layout import resolve_slot, taxonomy_ranks  # noqa: E402

MODEL = os.path.join(ROOT, 'providers', 'common', 'topology', 'model.yaml')
BINDING = os.path.join(ROOT, 'providers', 'aws', 'catalog', 'topology_binding.yaml')
CATALOG = os.path.join(ROOT, 'providers', 'aws', 'catalog', 'resource_catalog.csv')
TYPES = os.path.join(ROOT, 'providers', 'aws', 'catalog', 'asset_types.csv')
LABELS = os.path.join(ROOT, 'console-app', 'src', 'components', 'console', 'service-labels.ts')

# The border a rail attaches to, outermost first. This is the reading order of
# the table and of the diagram: a rule on the account applies to everything
# inside it, so it is met before the ones that apply to less.
SCOPES = [
    ('account', 'Account', 'applies to the whole account'),
    ('region', 'Region', 'applies to everything in the region'),
    ('network', 'VPC', 'applies inside one network'),
    ('zone', 'AZ', 'applies inside one zone'),
    ('segment', 'Subnet', 'applies inside one subnet'),
]

ARMS = {
    'e': ('E', 'east', 'who may act, and what is sealed'),
    'w': ('W', 'west', 'how it is built, run and owned'),
    's': ('S', 'south', 'how traffic leaves, and would we notice'),
    'n': ('N', 'north', 'doors only — no rule tabs'),
}


def service_labels():
    """Product names, from the generated table the console already uses."""
    out = {}
    if not os.path.exists(LABELS):
        return out
    with open(LABELS) as fh:
        for line in fh:
            line = line.strip().rstrip(',')
            if ':' not in line or line.startswith(('*', '/', 'export')):
                continue
            key, _, value = line.partition(':')
            out[key.strip().strip('"')] = value.strip().strip('"')
    return out


def main():
    with open(MODEL) as fh:
        model = yaml.safe_load(fh)
    with open(BINDING) as fh:
        binding = yaml.safe_load(fh)

    roles = model['roles']
    rule_roles = {r: s for r, s in roles.items() if s.get('kind') == 'rule'}
    sub_rank = taxonomy_ranks(model)

    overrides = binding.get('overrides') or {}
    services = binding.get('services') or {}
    tax_types = binding.get('taxonomy_types') or {}
    tax_services = binding.get('taxonomy') or {}
    labels = service_labels()

    with open(TYPES) as fh:
        collectable = {r['key'] for r in csv.DictReader(fh) if r.get('collect') == 'yes'}
    with open(CATALOG) as fh:
        catalog = list(csv.DictReader(fh))

    def role_of(key):
        r = overrides.get(key)
        if isinstance(r, dict):
            r = r.get('default')
        return r or services.get(key.split('.')[0])

    def domain_of(key):
        return tax_types.get(key) or tax_services.get(key.split('.')[0])

    # (scope, arm, domain) -> {service -> type count}
    cells = collections.defaultdict(lambda: collections.Counter())
    roles_seen = collections.defaultdict(set)
    for row in catalog:
        key = row['key']
        if key not in collectable:
            continue
        role = role_of(key)
        spec = rule_roles.get(role)
        if not spec:
            continue
        container = spec.get('container') or 'region'
        if isinstance(container, list):
            container = container[0]
        domain = domain_of(key) or 'unclassified'
        cat, _, sub = domain.partition('.')
        found = resolve_slot(cat, sub, model)
        # The arm comes from the DOMAIN now; the role only says which box.
        arm = found[1] if found else (spec.get('anchor') or 'rail.s').split('.')[-1]
        slot = found[0] if found else '—'
        cell = (container, arm, slot, domain)
        cells[cell][key.split('.')[0]] += 1
        roles_seen[cell].add(role)

    total_types = sum(sum(c.values()) for c in cells.values())
    total_services = len({s for c in cells.values() for s in c})

    out = sys.stdout.write
    out('# Supporting services — domain, scope, arm, sequence\n\n')
    out('<!-- GENERATED by scripts/build-supporting-reference.py — do not edit. -->\n\n')
    out(f'**{total_services} services, {total_types} collectable types.** A supporting\n'
        'service governs the estate rather than serving traffic in it: it holds\n'
        '`kind: rule` in the model, and that is what puts it on a border rail rather\n'
        'than inline among the workloads.\n\n')

    out('Four things decide where one draws, and each comes from somewhere different:\n\n')
    out('| Column | Answers | Comes from |\n|---|---|---|\n')
    out('| **Scope** | *which box* — whose border it hangs on | `roles.*.container` |\n')
    out('| **Arm** | *which side* of that box | `rail_slots` — from the DOMAIN |\n')
    out('| **Slot** | *where on that side* | `rail_slots.slots` |\n')
    out('| **Domain** | *what it is* — the heading on the tab | `taxonomy` in the binding |\n')
    out('| **Seq** | *where in the stack* along that arm | order of the `taxonomy` block |\n\n')

    out('**Seq is relative, not absolute.** It is a reading order, not a slot: if the\n'
        'estate has no `firewall`, `routing` moves up and takes its place. Nothing is\n'
        'reserved and no gap is drawn for something that is not there — an empty tab\n'
        'would be a claim about an estate nobody has.\n\n')
    out('The numbers come from the *order of the taxonomy block in the model*, which is\n'
        'the same list the engine sorts by. Moving a line in that block moves a tab on\n'
        'the canvas; there is no second table to keep in step.\n\n')

    out('| Seq | Scope | Arm | Slot | Domain | Services | Types |\n')
    out('|---:|---|---|---|---|---|---:|\n')

    order = {name: i for i, (name, _, _) in enumerate(SCOPES)}
    scope_label = {name: label for name, label, _ in SCOPES}
    grouped = collections.defaultdict(list)
    for (scope, arm, slot, domain), svcs in cells.items():
        grouped[(scope, arm)].append((sub_rank.get(domain, 9999), domain, slot, svcs))

    for (scope, anchor) in sorted(grouped, key=lambda k: (order.get(k[0], 9), k[1])):
        rows = sorted(grouped[(scope, anchor)])
        letter, arm_name, _ = ARMS.get(anchor, ('?', anchor, ''))
        for seq, (_, domain, slot, svcs) in enumerate(rows, start=1):
            # By LABEL, not by service id: `cognitoidp` and `cognito-idp` are both
            # "Cognito", and printing it twice says there are two products.
            by_label = collections.Counter()
            for sid, n in svcs.items():
                by_label[labels.get(sid, sid)] += n
            named = sorted(by_label.items(), key=lambda kv: (-kv[1], kv[0]))
            shown = ' · '.join(f'{lbl} {n}' for lbl, n in named[:6])
            if len(named) > 6:
                shown += f' · +{len(named) - 6} more'
            out(f'| {seq} | {scope_label.get(scope, scope)} | {letter} · {arm_name} '
                f'| `{slot}` | `{domain}` | {shown} | {sum(svcs.values())} |\n')

    out('\n## What each arm means\n\n')
    out('| Arm | Question it answers | On the canvas |\n|---|---|---|\n')
    for anchor in ('e', 'w', 's', 'n'):
        letter, name, question = ARMS[anchor]
        n = sum(sum(c.values()) for k, c in cells.items() if k[1] == anchor)
        out(f'| **{letter} · {name}** | {question} | {n} types |\n')

    out('\n## How to read a rail\n\n')
    out('Each row above is one **tab** on the border named in *Scope*, on the side named\n'
        'in *Arm*, stacked in *Seq* order. The tab is open on the side facing the box, so\n'
        'it reads as attached to that container rather than floating near it, and it is\n'
        'tinted by the code family its domain belongs to. Clicking one lists the\n'
        'resources.\n\n')
    out('A resource governed by one of these carries its **code** — `sg-2`, `iam-1`,\n'
        '`kms-1` — in the same hue as the arm the governing resource rides, so a reader\n'
        'goes to the right border without reading a word. Codes are only issued to\n'
        'governing resources with at least one **drawn** member: a code pointing at\n'
        'something nobody can find is worse than no code.\n')


if __name__ == '__main__':
    main()
