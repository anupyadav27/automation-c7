#!/usr/bin/env python3
"""
Every figure in the KIND reference model, read out of the built scene.

    python3 scripts/kind-grid.py            # human-readable
    python3 scripts/kind-grid.py --json     # for the artifact

Exists so the reference is refreshable rather than re-typed. A document full of
hand-copied counts is accurate exactly once, and this one makes claims about the
shape of an estate that changes every collection - "20 of 43 domains span more
than one kind" is an argument, and an argument resting on a stale number is
worse than no number.

Reads `out/scene.json` only. No AWS calls, no side effects.
"""

import argparse
import collections
import json
import os
import sys

SCENE = os.path.join(os.path.dirname(__file__), '..', 'out', 'scene.json')

# The engine emits the kind directly now. This map is what the translation
# layer collapsed to when the rename landed - kept empty rather than deleted so
# the shape is obvious if a second vocabulary ever appears again.
KIND = {}
ORDER = ['boundary', 'resident', 'part', 'door', 'rule', 'record']


def walk(node, parent=None, depth=0):
    """Every node, with the parent and depth the tree gave it."""
    yield node, parent, depth
    for child in node.get('children') or []:
        yield from walk(child, node, depth + 1)


def kind_of(node):
    pos = node.get('position') or {}
    kind = KIND.get(pos.get('kind'), pos.get('kind'))
    # Everything declares its kind now, including the spine. A node without one
    # is a defect, not a boundary, and saying so beats quietly counting it.
    return kind or 'unclassified'


def domain_of(node):
    pos = node.get('position') or {}
    if not pos.get('category'):
        return None
    return f"{pos['category']}.{pos.get('subcategory')}"


def collect(scene):
    nodes = list(walk(scene['tree']))
    parent_of = {n['key']: (p['key'] if p else None) for n, p, _ in nodes}

    kinds = collections.Counter(kind_of(n) for n, _, _ in nodes)
    anchors = collections.Counter((n.get('position') or {}).get('anchor') or '—'
                                  for n, _, _ in nodes)
    exposure = collections.Counter((n.get('position') or {}).get('exposure')
                                   for n, _, _ in nodes
                                   if (n.get('position') or {}).get('exposure'))

    grid = collections.defaultdict(collections.Counter)
    types = collections.defaultdict(collections.Counter)
    for n, _, _ in nodes:
        d = domain_of(n)
        if d:
            grid[d][kind_of(n)] += 1
            types[(d, kind_of(n))][n['type']] += 1

    # A box is one cell of (container x anchor x kind x domain). Records are
    # excluded because they are the one kind that never draws.
    boxes = collections.Counter()
    drawn = 0
    for n, p, _ in nodes:
        if kind_of(n) == 'record':
            continue
        drawn += 1
        pos = n.get('position') or {}
        boxes[(p['key'] if p else None, pos.get('anchor'),
               kind_of(n), domain_of(n))] += 1

    # Does a rule govern members that all sit in one container? That is what
    # decides whether it can be drawn AS a box round them, the way AWS's own
    # icon set does, or has to fall back to the border rail.
    governs = collections.defaultdict(set)
    for edge in scene.get('edges') or []:
        if edge['edge_type'] == 'protected-by':
            governs[edge['target_key']].add(parent_of.get(edge['source_key']))
    spread = collections.Counter()
    for members in governs.values():
        spread[len({m for m in members if m})] += 1

    mixed = {d: dict(v) for d, v in grid.items() if len(v) > 1}
    return {
        'account': scene['meta'].get('account_id'),
        'region': scene['meta'].get('region'),
        'nodes': len(nodes),
        'drawn': drawn,
        'not_drawn': len(nodes) - drawn,
        'boxes': len(boxes),
        'kinds': {k: kinds.get(k, 0) for k in ORDER},
        'anchors': dict(anchors.most_common()),
        'exposure': {str(k): v for k, v in sorted(exposure.items())},
        'edges': scene['meta'].get('visible_edges'),
        'domains': len(grid),
        'domains_spanning_kinds': len(mixed),
        'grid': {d: dict(v) for d, v in grid.items()},
        'mixed': mixed,
        'kind_spans_domains': {k: sum(1 for v in grid.values() if v.get(k))
                               for k in ORDER},
        'largest_cells': [
            {'domain': d, 'kind': k, 'count': sum(t.values()),
             'types': dict(t.most_common(4))}
            for (d, k), t in sorted(types.items(),
                                    key=lambda kv: -sum(kv[1].values()))[:8]
        ],
        'rule_member_spread': dict(sorted(spread.items())),
        'rules_contiguous': sum(v for k, v in spread.items() if k <= 1),
        'rules_scattered': sum(v for k, v in spread.items() if k > 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', action='store_true', help='machine-readable')
    ap.add_argument('--scene', default=SCENE)
    args = ap.parse_args()

    if not os.path.exists(args.scene):
        sys.exit(f'{args.scene} not found — build the scene first')
    with open(args.scene) as fh:
        data = collect(json.load(fh))

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"account {data['account']} · {data['region']}")
    print(f"{data['nodes']} nodes · {data['drawn']} drawn · "
          f"{data['not_drawn']} records off-canvas · {data['boxes']} boxes\n")
    print('KIND'.ljust(12), 'count'.rjust(6), '  domains it spans')
    for k in ORDER:
        print(f"  {k:10} {data['kinds'][k]:>6}   {data['kind_spans_domains'][k]}")
    print(f"\n{data['domains']} domains populated, "
          f"{data['domains_spanning_kinds']} span more than one kind")
    print(f"rules governing one container: {data['rules_contiguous']}, "
          f"scattered: {data['rules_scattered']}")
    print('\nlargest cells:')
    for c in data['largest_cells']:
        print(f"  {c['domain']:26} {c['kind']:9} {c['count']:>4}  "
              f"{', '.join(list(c['types'])[:3])}")


if __name__ == '__main__':
    main()