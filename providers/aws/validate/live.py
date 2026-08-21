"""
Validate the relation catalog against real collected assets.

Offline validation could only prove a path was *walkable*. This proves it
*resolves*: the path yields values on real resources, and those values name
resources that actually exist. Verdicts are written back into the catalog, so
every run makes the next one better informed.

The distinction the verdict vocabulary exists for is `absent` versus `refuted`.
A relation nothing exercises in this account and a relation that is simply wrong
look identical if you only count resolved edges. Only a type-condition violation
refutes; an unexercised path is recorded and kept.
"""

import csv
import os
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone

from providers.aws.runtime import arn as arnlib
from providers.aws.runtime.index import NodeIndex
from providers.aws.runtime import valuematch
from providers.aws.runtime.resolver import resolve_path, resolve_with_attributes
from providers.aws.validate import verdict as vd

CATALOG = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'catalog'))


class _AssetNode:
    """Adapter so collected assets can go into the runtime NodeIndex."""

    __slots__ = ('key', 'type', 'id', 'name', 'arn', 'asset')

    def __init__(self, asset):
        self.key = asset['asset_id']
        self.type = asset['resource_key']
        self.id = asset.get('id') or ''
        self.name = asset.get('name') or ''
        self.arn = asset.get('arn') or ''
        self.asset = asset


def build_index(assets, recipes=None):
    index = NodeIndex(recipes)
    for asset in assets:
        index.add(_AssetNode(asset))
    return index


CONFIDENCE_RANK = {'high': 3, 'medium': 2, 'low': 1, '': 0}


def collapse_duplicates(edges):
    """
    One relationship per (source, target, edge_type).

    The same fact arrives several times for two reasons, and neither is a
    second relationship. An instance with three ENIs in one security group
    resolves `NetworkInterfaces[].Groups[].GroupId` three times; and the same
    group is found again by GroupName, and again by the instance's own
    `SecurityGroups[]`. That was 8 rows for one membership, and a panel drew
    the group 8 times.

    The strongest row wins — highest confidence, then resolved over dangling.
    The paths that agreed are not discarded but counted into `corroborations`
    and joined into `via`: several independent paths finding the same target is
    evidence the edge is real, which is exactly what the mined relation table
    needs to distinguish a good rule from a lucky one.
    """
    groups = OrderedDict()
    for edge in edges:
        source = edge.get('source_asset_id') or ''
        target = edge.get('target_asset_id') or ''
        # A resource is not related to itself. Bucket policies produced 20 of
        # these: the holder's ARN as source and the bucket's bare NAME as
        # target, so the edge read "this bucket is accessible by itself". The
        # exposure it was trying to express is already a fact on the resource —
        # `block_public_acls` and friends are Tier 2 columns — and as an edge it
        # only made every bucket look like it connected to nothing, because a
        # self-edge is the one thing a relation walk must refuse to follow.
        if source == target or (target and source.endswith(f':{target}')):
            continue
        key = (source, target, edge.get('edge_type'))
        groups.setdefault(key, []).append(edge)

    out = []
    for rows in groups.values():
        best = max(rows, key=lambda e: (
            CONFIDENCE_RANK.get(e.get('confidence', ''), 0),
            str(e.get('resolved')).lower() == 'true',
        ))
        paths = sorted({e.get('via', '') for e in rows if e.get('via')})
        edge = dict(best)
        edge['via'] = ' | '.join(paths)
        edge['corroborations'] = len(paths)
        out.append(edge)
    return out


def validate(assets, relations_path=None, catalog_path=None, write_back=True,
             policy_edges=None):
    """
    Resolve every relation against the assets. Returns (edges, report).

    Relations whose source type produced no assets are `absent` rather than
    failing: an account that runs no Redshift says nothing about whether the
    Redshift relations are correct.
    """
    relations_path = relations_path or os.path.join(CATALOG, 'relations_full.csv')
    catalog_path = catalog_path or os.path.join(CATALOG, 'resource_catalog.csv')

    with open(catalog_path) as fh:
        catalog = {r['key']: r for r in csv.DictReader(fh)}
    with open(relations_path) as fh:
        relations = list(csv.DictReader(fh))

    by_type = defaultdict(list)
    for asset in assets:
        by_type[asset['resource_key']].append(asset)
    index = build_index(assets, catalog)

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    edges, verdicts = [], Counter()

    for rel in relations:
        src_key, tgt_key = rel['source_key'], rel['target_key']
        sources = by_type.get(src_key, [])
        target_recipe = catalog.get(tgt_key, {})
        target_collected = bool(by_type.get(tgt_key))

        hits = values = resolved = dangling = violations = 0
        for asset in sources:
            # Sibling fields ride along with the value. `Routes[].NatGatewayId`
            # means nothing without the DestinationCidrBlock beside it, so the
            # edge carries what is needed to judge it, not just to draw it.
            found = resolve_with_attributes(asset.get('raw') or {}, rel['source_path'])
            if not found:
                continue
            hits += 1
            for value, attributes in found:
                values += 1
                text = str(value)
                node = index.lookup(tgt_key, text)
                if node is None:
                    node = index.lookup_any(text)
                    if node is not None and node.type != tgt_key:
                        node = None
                if node is not None:
                    resolved += 1
                    edges.append({
                        'source_asset_id': asset['asset_id'],
                        'target_asset_id': node.key,
                        'source_key': src_key, 'target_key': tgt_key,
                        'edge_type': rel.get('edge_type', 'references'),
                        'via': rel['source_path'],
                        'mechanism': rel.get('source', ''),
                        'confidence': rel.get('confidence', ''),
                        'value': text, 'resolved': 'true',
                        'attributes': attributes,
                        # The single value that separates an internet path from
                        # an internal one, surfaced rather than buried.
                        'default_route': valuematch.is_default_route(
                            attributes.get('DestinationCidrBlock', '')),
                    })
                else:
                    dangling += 1
                    # A value that fails the type conditions is evidence the
                    # relation is wrong; one that merely finds nothing may just
                    # mean the target type was not collected.
                    prefix_ok = arnlib.matches_prefix(text, target_recipe)
                    arn_ok = arnlib.matches_type(text, target_recipe)
                    if prefix_ok is False or arn_ok is False:
                        violations += 1

        obs = vd.Observation(sources=len(sources), hits=hits, values=values,
                             resolved=resolved, dangling=dangling,
                             violations=violations,
                             target_collected=target_collected)
        result, detail = vd.classify(obs)
        verdicts[result] += 1
        if write_back:
            rel.update(vd.to_signals(obs, result, detail, now))

    if write_back and relations:
        fields = list(relations[0].keys())
        for extra in vd.SIGNAL_FIELDS:
            if extra not in fields:
                fields.append(extra)
        with open(relations_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(relations)

    # Mechanism C: edges where neither end carries the other's id.
    value_edges = []
    for edge in valuematch.derive_edges(assets):
        source = next((a for a in assets
                       if a['asset_id'] == edge['source_asset_id']), None)
        value_edges.append({
            'source_asset_id': edge['source_asset_id'],
            'target_asset_id': edge['target_asset_id'],
            'source_key': source['resource_key'] if source else '',
            'target_key': '', 'edge_type': edge['edge_type'],
            'via': edge.get('match_kind', ''), 'mechanism': 'value-match',
            'confidence': edge.get('confidence', ''), 'value': edge.get('value', ''),
            'resolved': 'true', 'external': str(edge.get('external', False)).lower(),
        })
    edges.extend(value_edges)

    # Mechanism B edges are produced during collection, not here - they come
    # from documents rather than from resource fields - but they belong in the
    # same edge file so downstream code sees one graph.
    for edge in policy_edges or []:
        edges.append({
            'source_asset_id': edge.get('holder_asset_id') or edge.get('source_id', ''),
            'target_asset_id': edge.get('target_id', ''),
            'source_key': edge.get('source_key', ''), 'target_key': edge.get('target_key') or '',
            'edge_type': edge.get('edge_type', ''), 'via': 'policy-document',
            'mechanism': 'policy-document', 'confidence': 'high',
            'value': edge.get('target_id', ''),
            'resolved': str(bool(edge.get('resolved'))).lower(),
            'public': str(bool(edge.get('public'))).lower(),
            'principal_kind': edge.get('principal_kind', ''),
        })

    raw_edges = len(edges)
    edges = collapse_duplicates(edges)

    report = {
        'assets': len(assets),
        'types_with_assets': len(by_type),
        'relations_checked': len(relations),
        'edges': len(edges),
        'edges_before_collapse': raw_edges,
        'edges_collapsed': raw_edges - len(edges),
        'verdicts': dict(verdicts),
        'edges_by_type': dict(Counter(e['edge_type'] for e in edges)),
        'edges_by_mechanism': dict(Counter(e['mechanism'] for e in edges)),
        'value_match_edges': len(value_edges),
        'default_route_edges': sum(1 for e in edges if e.get('default_route')),
        'verdicts_written_back': bool(write_back),
    }
    return edges, report
