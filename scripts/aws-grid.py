#!/usr/bin/env python3
"""
The KIND × DOMAIN grid for every AWS type in the catalog — not just what one
account happens to own.

    python3 scripts/aws-grid.py                  # the matrix
    python3 scripts/aws-grid.py --gaps           # only what needs a decision
    python3 scripts/aws-grid.py --domain compute.instances
    python3 scripts/aws-grid.py --json

`kind-grid.py` reads the built scene, so it only ever shows the ~140 types this
estate collected. This resolves all 4,743 catalog types straight through the
binding, which is the only way to review a classification before the day a
customer's account produces it.

That review has never been possible, and it is how 228 security group rules came
to be filed under `compute.instances`: the type had no explicit domain, fell
through to the `ec2` service default, and nothing looked.

Nothing here touches AWS or the scene. It reads catalogs and the binding.
"""

import argparse
import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from providers.common.topology.layout import (  # noqa: E402
    load_binding, load_model, resolve_role, resolve_taxonomy,
)

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'providers', 'aws', 'catalog')
BINDING = os.path.join(CATALOG, 'topology_binding.yaml')
ORDER = ['boundary', 'resident', 'part', 'door', 'rule', 'record']


def catalog_types():
    """
    Every type the collector will actually fetch.

    Filtered on `collect: yes` — 1,666 of 4,739 are marked no (no read
    operation, an API readout rather than a resource), and classifying a type
    that never arrives is work nobody will ever see the result of.
    """
    with open(os.path.join(CATALOG, 'asset_types.csv')) as fh:
        return [(r['key'], r['service']) for r in csv.DictReader(fh)
                if r.get('key') and '.' in r['key'] and r.get('collect') == 'yes']


def explicit_domains():
    """Types whose domain is stated outright rather than inherited."""
    import yaml
    with open(BINDING) as fh:
        b = yaml.safe_load(fh)
    return set(b.get('taxonomy_types') or {}), set(b.get('taxonomy') or {})


def build():
    model, binding = load_model(), load_binding(BINDING)
    kind_of_role = {r: (s or {}).get('kind') for r, s in (model['roles'] or {}).items()}
    for lane in model['categories']['lanes']:
        kind_of_role.setdefault(lane['role'], 'resident')
    for c in model['containers']:
        if c.get('kind'):
            kind_of_role[c['role']] = c['kind']

    # The spine is consulted first, exactly as the engine does it. A VPC is a
    # boundary because the binding lists it as one - ask `resolve_role` and it
    # answers `record` from the `ec2` service default, which is true of nothing.
    import yaml
    with open(BINDING) as fh:
        spine = {t: role for role, spec in (yaml.safe_load(fh).get('spine') or {}).items()
                 for t in (spec or {}).get('types') or []}

    typed, service_typed = explicit_domains()

    grid = collections.defaultdict(collections.Counter)
    rows, gaps = [], []
    for key, service in catalog_types():
        role = spine.get(key) or resolve_role(key, {}, binding)
        kind = kind_of_role.get(role) if role else None
        cat, sub = resolve_taxonomy(key, binding)
        domain = f'{cat}.{sub}' if cat else None

        # Where did the domain come from? An explicit per-type mapping is a
        # decision somebody made; a service default is one nobody made.
        if key in typed:
            source = 'type'
        elif service in service_typed:
            source = 'service'
        else:
            source = 'none'

        rows.append(dict(key=key, service=service, role=role, kind=kind,
                         domain=domain, domain_source=source))
        if kind and domain:
            grid[domain][kind] += 1

        if not role or not kind:
            gaps.append((key, 'no role', role or '—'))
        elif not domain:
            gaps.append((key, 'no domain', role))

    return model, rows, grid, gaps


def sibling_conflicts(rows):
    """
    A type that EXTENDS another type's name but disagrees with it.

    `ec2.security_group_rule` is `ec2.security_group` plus a suffix, so it is a
    detail of that thing and belongs in the same domain. It inherited the `ec2`
    service default instead and landed in `compute.instances` — 228 firewall
    rules filed under compute, with nothing to notice.

    Keyed on the name rather than on the service, because "some sibling was
    named explicitly" flags every RDS type the moment one security group is
    named, and misses this case entirely — `compute.instances` IS explicitly
    stated for `ec2.instance`, so a service-level check sees no disagreement.
    """
    explicit = {r['key']: r for r in rows if r['domain_source'] == 'type'}
    out = []
    for r in rows:
        if r['key'] in explicit:
            continue
        # longest stated ancestor wins: `a.b_c_d` prefers `a.b_c` over `a.b`
        parents = [k for k in explicit
                   if r['key'].startswith(k + '_') or r['key'].startswith(k + '.')]
        if not parents:
            continue
        parent = max(parents, key=len)
        if explicit[parent]['domain'] != r['domain']:
            out.append((r['key'], r['domain'], [explicit[parent]['domain'],
                                                f'(from {parent})']))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--gaps', action='store_true', help='only what needs a decision')
    ap.add_argument('--domain', help='list the types in one cell')
    args = ap.parse_args()

    model, rows, grid, gaps = build()
    conflicts = sibling_conflicts(rows)

    if args.json:
        print(json.dumps({
            'types': len(rows),
            'grid': {d: dict(c) for d, c in grid.items()},
            'gaps': gaps,
            'sibling_conflicts': conflicts,
            'rows': rows,
        }, indent=2))
        return

    if args.domain:
        hits = [r for r in rows if r['domain'] == args.domain]
        print(f'{args.domain} — {len(hits)} types')
        for kind in ORDER:
            here = sorted(r['key'] for r in hits if r['kind'] == kind)
            if here:
                print(f'\n  {kind} ({len(here)})')
                for k in here:
                    print(f'    {k}')
        return

    if args.gaps:
        print(f'TYPES NEEDING A DECISION\n')
        print(f'unclassified: {len(gaps)}')
        for key, why, role in gaps[:40]:
            print(f'   {key:46} {why:12} {role}')
        if len(gaps) > 40:
            print(f'   … and {len(gaps) - 40} more')
        print(f'\ninherited a service default while a sibling states its own: '
              f'{len(conflicts)}')
        for key, got, stated in conflicts[:40]:
            print(f'   {key:46} got {got:24} siblings say {stated}')
        if len(conflicts) > 40:
            print(f'   … and {len(conflicts) - 40} more')
        return

    print(f'{len(rows):,} collectable AWS types\n')
    hdr = f'{"DOMAIN":30}' + ''.join(f'{k[:9]:>10}' for k in ORDER) + f'{"total":>8}'
    print(hdr)
    print('-' * len(hdr))
    for domain in sorted(grid, key=lambda d: (-sum(grid[d].values()), d)):
        cells = grid[domain]
        line = f'{domain:30}'
        for k in ORDER:
            line += f'{cells.get(k, "·"):>10}'
        print(line + f'{sum(cells.values()):>8}')
    totals = collections.Counter()
    for c in grid.values():
        totals.update(c)
    print('-' * len(hdr))
    print(f'{"TOTAL":30}' + ''.join(f'{totals.get(k, 0):>10}' for k in ORDER)
          + f'{sum(totals.values()):>8}')
    print(f'\n{len(grid)} domains populated of '
          f'{sum(len(v) for v in model["taxonomy"].values())} declared')
    print(f'unclassified types: {len(gaps)} · '
          f'inherited-while-sibling-explicit: {len(conflicts)}')
    print('\nrun with --gaps to see what needs a decision')


if __name__ == '__main__':
    main()
