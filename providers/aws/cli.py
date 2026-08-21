#!/usr/bin/env python3
"""
discovery — collect AWS assets, validate relations, render a diagram.

    python -m discovery.cli collect  --region <r> [--scope scenario|primary|all] [--dry-run]
    python -m discovery.cli validate [--region <r>]
    python -m discovery.cli diagram  [--vpc vpc-123] [--overlays identity,encryption]

`collect` is the only command that calls AWS. Its results are cached under
`out/`, so validate and diagram re-run for free and can be re-filtered without
spending another call.

Always dry-run first on a new account. At full scope this plans ~1,400 root
calls across 327 services, and the plan tells you what that will cost before you
pay for it.
"""

import argparse
import csv
import json
import os
import sys

from cspm import paths
import time

OUT = paths.OUT

# The types the topology scenarios reference. A useful first run: small enough
# to eyeball against the console, complete enough to exercise every stage.
SCENARIO_TYPES = [
    'ec2.vpc', 'ec2.subnet', 'ec2.instance', 'ec2.volume',
    'ec2.network_interface', 'ec2.security_group', 'ec2.route_table',
    'ec2.internet_gateway', 'ec2.nat_gateway', 'ec2.vpc_endpoint',
    'ec2.vpc_endpoint_service', 'ec2.vpc_peering_connection',
    'ec2.transit_gateway', 'ec2.transit_gateway_attachment',
    'ec2.transit_gateway_route_table', 'ec2.vpn_connection', 'ec2.vpn_gateway',
    'ec2.customer_gateway', 'ec2.image', 'ec2.snapshot', 'ec2.elastic_ip',
    'elbv2.load_balancer', 'elbv2.target_group', 'elbv2.target_health',
    'elbv2.listener', 'elb.load_balancer',
    'directconnect.connection', 'directconnect.virtual_interface',
    'directconnect.direct_connect_gateway',
    'iam.role', 'iam.instance_profile', 'iam.user', 'iam.policy',
    's3.bucket', 'ram.resource_share', 'lambda.function', 'kms.key',
    'rds.db_instance', 'dynamodb.table', 'sqs.queue', 'sns.topic',
    'ecs.cluster', 'eks.cluster', 'autoscaling.auto_scaling_group',
    'route53.hosted_zone', 'cloudfront.distribution',
]


def _ensure_out():
    os.makedirs(OUT, exist_ok=True)
    return OUT


def _write_csv(path, rows, fields=None):
    if not rows:
        return 0
    fields = fields or list(rows[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v, default=str)
                                 if isinstance(v, (dict, list)) else v)
                             for k, v in row.items() if k in fields})
    return len(rows)


# ── collect ───────────────────────────────────────────────────────────

def cmd_collect(args):
    from providers.aws.runtime.collector import Collector

    only = SCENARIO_TYPES if args.scope == 'scenario' else None
    if args.types:
        only = [t.strip() for t in args.types.split(',') if t.strip()]
    scope = 'all' if args.scope == 'all' else 'primary'

    # The session, when the caller has one.
    #
    # `None` keeps the historic behaviour exactly: `Collector` falls back to a
    # bare `boto3.Session()` and resolves the ambient default chain, which is
    # right for someone running this against their own account from a laptop.
    # An onboarded account passes a session scoped to ITS credentials, and that
    # is the whole difference between a single-tenant tool and a multi-tenant
    # one — see `providers/aws/runtime/credentials.py`.
    collector = Collector(args.region, account_id=args.account,
                          account_name=args.account_name, workers=args.workers,
                          session=getattr(args, 'session', None))
    collector.policy_scope = args.policies
    roots, children = collector.plan(scope, only)

    print(f'plan: {len(roots)} root calls · {len(children)} child types · '
          f'{len({r.service for r in roots})} services', file=sys.stderr)
    if args.dry_run:
        # Prove read-only before anything is spent, not after.
        from providers.aws.runtime.collector import _snake_to_pascal, READ_VERBS
        offenders = [c for c in roots + children
                     if not _snake_to_pascal(c.operation).startswith(READ_VERBS)]
        print(f'  non-read operations : {len(offenders)}', file=sys.stderr)
        print(f'  with selector args  : {sum(1 for c in roots if c.params)}',
              file=sys.stderr)
        for call in roots[:15]:
            print(f'    {call.service}.{call.operation}', file=sys.stderr)
        if len(roots) > 15:
            print(f'    ... and {len(roots) - 15} more', file=sys.stderr)
        return 0

    started = time.time()
    collector.collect(scope, only)
    elapsed = time.time() - started

    out = _ensure_out()
    fields = ['asset_id', 'arn', 'arn_source', 'resource_key', 'resource_name',
              'service', 'cfn_type', 'id', 'name', 'account_id', 'account_name',
              'region', 'availability_zone', 'tags', 'layer_id', 'layer_name',
              'overlay_group', 'owner_account', 'parent_asset_id', 'discovered_by']
    _write_csv(os.path.join(out, 'assets.csv'), collector.assets, fields)
    with open(os.path.join(out, 'assets.json'), 'w') as fh:
        json.dump(collector.assets, fh, default=str)
    _write_csv(os.path.join(out, 'accounts.csv'),
               collector.graph.rows() if collector.graph else [])
    _write_csv(os.path.join(out, 'failures.csv'), collector.failures)
    with open(os.path.join(out, 'policy_edges.json'), 'w') as fh:
        json.dump(collector.policy_edges, fh, default=str)

    with open(os.path.join(out, 'failures.json'), 'w') as fh:
        json.dump({'failures': collector.failures,
                   'truncated': collector.truncated}, fh, indent=2, default=str)

    # A type that answered and produced nothing is the failure mode that hides
    # a whole service without raising - EKS sat in this account for weeks. The
    # count belongs in the summary; the list belongs somewhere someone can work
    # through it, which a number never is.
    with open(os.path.join(out, 'barren.json'), 'w') as fh:
        json.dump({'barren': collector.barren,
                   'skipped_calls': collector.skipped_calls},
                  fh, indent=2, default=str)

    summary = collector.summary()
    summary['elapsed_seconds'] = round(elapsed, 1)
    with open(os.path.join(out, 'collection.json'), 'w') as fh:
        json.dump(summary, fh, indent=2, default=str)

    print(json.dumps(summary, indent=2, default=str))
    return 0


# ── validate ──────────────────────────────────────────────────────────

def cmd_validate(args):
    from providers.aws.validate.live import validate

    path = os.path.join(OUT, 'assets.json')
    if not os.path.exists(path):
        print('no assets found; run `collect` first', file=sys.stderr)
        return 1
    with open(path) as fh:
        assets = json.load(fh)

    policy_edges = []
    policy_path = os.path.join(OUT, 'policy_edges.json')
    if os.path.exists(policy_path):
        with open(policy_path) as fh:
            policy_edges = json.load(fh)

    edges, report = validate(assets, write_back=not args.no_write_back,
                             policy_edges=policy_edges)
    out = _ensure_out()
    _write_csv(os.path.join(out, 'edges.csv'), edges)
    with open(os.path.join(out, 'validation.json'), 'w') as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str))
    return 0


# ── diagram ───────────────────────────────────────────────────────────

def cmd_diagram(args):
    from providers.aws.render import mermaid
    from providers.aws.runtime.layers import L_VPC
    from providers.aws.runtime.scene import build_scene

    assets_path = os.path.join(OUT, 'assets.json')
    if not os.path.exists(assets_path):
        print('no assets found; run `collect` first', file=sys.stderr)
        return 1
    with open(assets_path) as fh:
        assets = json.load(fh)

    edges = []
    edges_path = os.path.join(OUT, 'edges.csv')
    if os.path.exists(edges_path):
        with open(edges_path) as fh:
            edges = list(csv.DictReader(fh))

    account = assets[0]['account_id'] if assets else 'unknown'
    # Global resources (iam, route53, cloudfront) carry no region by design, and
    # one of them is usually first in the file - so take the first NON-empty
    # region rather than the first asset's.
    region = args.region or next(
        (a['region'] for a in assets if a.get('region')), '')
    name = assets[0].get('account_name') if assets else None
    scene = build_scene(assets, edges, account, region, account_name=name)

    if args.vpc:
        scene.filter_layer(L_VPC, {f'vpc:{args.vpc}'})

    overlays = ('*' if args.overlays == 'all'
                else tuple(o.strip() for o in args.overlays.split(',') if o.strip()))
    text = (mermaid.render_summary(scene) if args.summary
            else mermaid.render(scene, overlays=overlays))

    if args.out:
        with open(args.out, 'w') as fh:
            fh.write(text)
        print(f'written {args.out}', file=sys.stderr)
    else:
        print(text)
    print(json.dumps(scene.meta, indent=2, default=str), file=sys.stderr)
    return 0


def cmd_scene(args):
    """
    Write the scene graph as JSON.

    The UI consumes this file rather than calling the collector, which keeps the
    boundary in ARCHITECTURE.md intact: nothing in the React app imports or
    triggers anything that talks to AWS.
    """
    from providers.aws.runtime.scene import build_scene

    assets_path = os.path.join(OUT, 'assets.json')
    if not os.path.exists(assets_path):
        print('no assets found; run `collect` first', file=sys.stderr)
        return 1
    with open(assets_path) as fh:
        assets = json.load(fh)

    edges = []
    edges_path = os.path.join(OUT, 'edges.csv')
    if os.path.exists(edges_path):
        with open(edges_path) as fh:
            edges = list(csv.DictReader(fh))

    account = assets[0]['account_id'] if assets else 'unknown'
    region = args.region or next((a['region'] for a in assets if a.get('region')), '')
    scene = build_scene(assets, edges, account, region,
                        account_name=assets[0].get('account_name') if assets else None)
    doc = scene.to_dict()

    # Accounts and icons travel with the scene so the page needs one fetch.
    accounts_path = os.path.join(OUT, 'accounts.csv')
    if os.path.exists(accounts_path):
        with open(accounts_path) as fh:
            doc['accounts'] = list(csv.DictReader(fh))
    # Column schema per resource type, derived from the relation catalog: a
    # type's columns ARE the distinct things it can point at. Hand-listing them
    # per service would drift from the relations the moment either changed.
    rel_path = os.path.join(os.path.dirname(__file__), 'catalog', 'relations_full.csv')
    if os.path.exists(rel_path):
        columns = {}
        with open(rel_path) as fh:
            for row in csv.DictReader(fh):
                if row.get('verdict') == 'refuted' or not row.get('target_key'):
                    continue
                entry = columns.setdefault(row['source_key'], {})
                # Keep the strongest edge type seen for this target, so a column
                # is labelled by what the relationship actually is.
                entry.setdefault(row['target_key'], row.get('edge_type', 'references'))
        doc['columns'] = {k: sorted(v.items()) for k, v in columns.items()}

    icons_path = os.path.join(os.path.dirname(__file__), 'catalog', 'icon_map.csv')
    if os.path.exists(icons_path):
        with open(icons_path) as fh:
            doc['icons'] = {r['key']: r['icon_class']
                            for r in csv.DictReader(fh) if r['icon_class']}

    targets = [os.path.join(_ensure_out(), 'scene.json')]
    if args.ui:
        targets.append(os.path.join(paths.ROOT, 'ui',
                                    'public', 'scene.json'))
    for target in targets:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as fh:
            json.dump(doc, fh, default=str)
        print(f'written {os.path.normpath(target)}', file=sys.stderr)
    print(json.dumps(doc['meta'], indent=2, default=str))
    return 0


def cmd_resources(args):
    """
    Write resources.json — the per-resource detail the diagram does not carry.

    Kept separate from scene.json on purpose. The scene is the diagram and is
    fetched on every page view; this is depth, fetched once when a table is
    first opened. Raw payloads alone are 121 KB of 292 KB, and they only matter
    in a detail view.
    """
    assets_path = os.path.join(OUT, 'assets.json')
    if not os.path.exists(assets_path):
        print('no assets found; run `collect` first', file=sys.stderr)
        return 1
    with open(assets_path) as fh:
        assets = json.load(fh)

    edges = []
    edges_path = os.path.join(OUT, 'edges.csv')
    if os.path.exists(edges_path):
        with open(edges_path) as fh:
            edges = list(csv.DictReader(fh))

    by_key = {a['asset_id']: a for a in assets}
    name_of = {a['asset_id']: (a.get('name') or a.get('id')) for a in assets}

    ATTRS = ('arn', 'arn_source', 'resource_key', 'resource_name', 'service',
             'cfn_type', 'id', 'name', 'account_id', 'account_name', 'region',
             'availability_zone', 'tags', 'layer_id', 'layer_name',
             'overlay_group', 'owner_account', 'parent_asset_id', 'discovered_by')

    out = {}
    for asset in assets:
        out[asset['asset_id']] = {
            'attributes': {k: asset.get(k) for k in ATTRS},
            'out': [], 'in': [],
            'raw': asset.get('raw') if args.raw else None,
        }

    def side(edge, other_id):
        return {
            'edge_type': edge.get('edge_type', ''),
            'other_id': other_id,
            'other_name': name_of.get(other_id, other_id),
            'other_type': (edge.get('target_key') or edge.get('source_key') or '').split(':')[0],
            'mechanism': edge.get('mechanism', ''),
            'confidence': edge.get('confidence', ''),
            'verdict': edge.get('verdict', ''),
            'via': edge.get('via', ''),
            'value': edge.get('value', ''),
        }

    for edge in edges:
        src, tgt = edge.get('source_asset_id'), edge.get('target_asset_id')
        if src in out:
            entry = side(edge, tgt)
            entry['other_type'] = (edge.get('target_key') or '').split(':')[0]
            out[src]['out'].append(entry)
        # An edge pointing at something we did not collect still belongs to its
        # source; only the reverse index needs the target to exist.
        if tgt in out:
            entry = side(edge, src)
            entry['other_type'] = (edge.get('source_key') or '').split(':')[0]
            out[tgt]['in'].append(entry)

    targets = [os.path.join(_ensure_out(), 'resources.json')]
    if args.ui:
        targets.append(os.path.join(paths.ROOT, 'ui',
                                    'public', 'resources.json'))
    for target in targets:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as fh:
            json.dump(out, fh, default=str)
        size = os.path.getsize(target) / 1024
        print(f'written {os.path.normpath(target)} ({size:.0f} KB)', file=sys.stderr)

    print(json.dumps({
        'resources': len(out),
        'with_outgoing': sum(1 for v in out.values() if v['out']),
        'with_incoming': sum(1 for v in out.values() if v['in']),
        'raw_included': bool(args.raw),
    }, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='aws-discovery', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('collect', help='call AWS and write out/assets.csv')
    p.add_argument('--region', required=True)
    p.add_argument('--scope', default='scenario',
                   choices=['scenario', 'primary', 'all'])
    p.add_argument('--types', help='comma-separated resource keys, overrides scope')
    p.add_argument('--account', help='account id (else resolved via STS)')
    p.add_argument('--account-name')
    p.add_argument('--policies', default='core', choices=['core', 'all', 'none'],
                   help='policy documents to fetch: core services, all, or none. '
                        'A policy read costs one call PER RESOURCE.')
    p.add_argument('--workers', type=int, default=12,
                   help='concurrent API calls (default 12; more mainly buys throttling)')
    p.add_argument('--dry-run', action='store_true',
                   help='print the call plan without calling AWS')
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser('validate', help='resolve relations against collected assets')
    p.add_argument('--region')
    p.add_argument('--no-write-back', action='store_true',
                   help='do not update verdicts in the relation catalog')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('scene', help='write the scene graph as JSON for the UI')
    p.add_argument('--region')
    p.add_argument('--ui', action='store_true',
                   help='also write ui/public/scene.json')
    p.set_defaults(func=cmd_scene)

    p = sub.add_parser('resources', help='write per-resource detail for the UI')
    p.add_argument('--ui', action='store_true', help='also write ui/public/resources.json')
    p.add_argument('--raw', action='store_true', default=True,
                   help='include the raw AWS payload (default on)')
    p.add_argument('--no-raw', dest='raw', action='store_false')
    p.set_defaults(func=cmd_resources)

    p = sub.add_parser('diagram', help='render the scene graph')
    p.add_argument('--region')
    p.add_argument('--vpc', help='restrict to one VPC id')
    p.add_argument('--overlays', default='',
                   help="comma-separated overlay groups, or 'all'")
    p.add_argument('--summary', action='store_true', help='counts only')
    p.add_argument('--out', help='write to a file instead of stdout')
    p.set_defaults(func=cmd_diagram)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
