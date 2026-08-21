#!/usr/bin/env python3
"""
Offline validation — everything decidable without touching AWS.

Three checks, none of which needs credentials or a single API call:

  PATH EXISTENCE   does source_path actually exist in the source operation's
                   response shape? A path that cannot be walked can never yield
                   an edge. This also audits the curated relations for the first
                   time: c7n's RelatedIdsExpression values were trusted on
                   sight, never checked against the shape of the operation we
                   intend to call.

  JOIN MODE        a path yields an id, an ARN or a name. The target is indexed
                   by whichever handles it declares. If the path yields an ARN
                   and the target has no ARN at all, the edge is structurally
                   incapable of resolving - refutable now rather than after a
                   scan.

  CORROBORATION    two signals already latent in the data and unused:
                     * several distinct paths from A reaching the same target
                     * A referencing B while B references A
                   Both are independent agreement, which is what made the
                   original 54 cross-source relations trustworthy.

Only REFUTED is assigned here. Confirmation requires observing real values, so
everything else stays PENDING for the collector - an unwalkable path is provably
broken, but a walkable one is merely plausible.

Usage:
  python3 -m discovery.validate.offline
  python3 -m discovery.validate.offline --out /tmp/annotated.csv
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache

from providers.aws.validate.verdict import PENDING, REFUTED

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.normpath(os.path.join(HERE, '..', 'catalog'))

EXTRA_FIELDS = ['path_exists', 'join_mode', 'paths_to_target', 'bidirectional',
                'needs_operation', 'offline_note']


@lru_cache(maxsize=None)
def _session():
    import botocore.session
    return botocore.session.get_session()


def _snake(name):
    """PascalCase operation name -> the snake_case boto3 method.

    Delegates to botocore's own converter. A hand-rolled regex got acronyms
    wrong - ListWebACLs became list_web_ac_ls, which is not a method, so every
    WAF web ACL in the account was silently uncollectable. boto3 builds its
    method names with this exact function, so it is the only thing guaranteed
    to agree with the client.
    """
    from botocore import xform_name
    return xform_name(name)


@lru_cache(maxsize=None)
def item_paths(service, operation):
    """
    Every leaf path inside one resource item of an operation's response.

    Returns a frozenset, or None when the operation cannot be resolved - which
    is different from "the path is missing" and must not be reported as one.
    """
    try:
        model = _session().get_service_model(service)
    except Exception:
        return None
    wanted = operation.replace('_', '').lower()
    opn = next((o for o in model.operation_names
                if o.replace('_', '').lower() == wanted), None)
    if not opn:
        return None
    try:
        op = model.operation_model(opn)
    except Exception:
        return None
    if op.output_shape is None or op.output_shape.type_name != 'structure':
        return None

    # Several operations return more than one list - BatchGetProjects yields
    # both `projects` and `projectsNotFound` - so every list member is treated
    # as a candidate item container and their paths unioned. Assuming a single
    # container silently loses every field of such an operation.
    lists = [s.member for _, s in op.output_shape.members.items()
             if s.type_name == 'list']
    roots = lists or [op.output_shape]

    out = set()

    def walk(shape, path='', depth=0, seen=frozenset()):
        if depth > 8 or id(shape) in seen:
            return
        seen = seen | {id(shape)}
        if shape.type_name == 'structure':
            for name, sub in shape.members.items():
                walk(sub, f'{path}.{name}' if path else name, depth + 1, seen)
        elif shape.type_name == 'list':
            walk(shape.member, f'{path}[]', depth, seen)
        elif path:
            out.add(path)

    for root in roots:
        walk(root)
    return frozenset(out)


@lru_cache(maxsize=None)
def find_operation_with_path(service, path):
    """
    Any read operation in a service whose response contains `path`.

    A curated relation often names a field that the type's *enumerate* call does
    not return: c7n lists brokers with list_brokers but reads SecurityGroups
    from describe_broker. The relation is sound; the collector simply has to
    make a second call. Searching for the operation that does carry the field
    turns a false refutation into an actionable instruction.
    """
    try:
        model = _session().get_service_model(service)
    except Exception:
        return ''
    for opn in model.operation_names:
        if not opn.startswith(('Describe', 'List', 'Get', 'BatchGet')):
            continue
        paths = item_paths(service, _snake(opn))
        if paths and path in paths:
            return _snake(opn)
    return ''


def join_mode(leaf, target_row):
    """
    How this edge would have to resolve, or why it cannot.

    The index registers nodes by id, ARN and name, so a path is usable if the
    target declares the handle the path yields.
    """
    has_arn = bool(target_row.get('arn_field') or target_row.get('arn_type'))
    has_id = bool(target_row.get('id_field'))
    id_field = (target_row.get('id_field') or '')

    if leaf.endswith(('Arn', 'ARN', 'Arns')):
        if not has_arn and not id_field.lower().endswith('arn'):
            return 'impossible', 'path yields an ARN but the target declares none'
        return 'by_arn', ''
    if leaf.endswith(('Name', 'Names')):
        if id_field.endswith(('Name', 'Names')):
            return 'by_id', ''
        return 'by_name', 'resolves against the name index, not the id index'
    if not has_id:
        return 'impossible', 'target has no id field to match against'
    return 'by_id', ''


def main():
    ap = argparse.ArgumentParser(description='Offline relation validation')
    ap.add_argument('--relations', default=os.path.join(CATALOG, 'relations_full.csv'))
    ap.add_argument('--catalog', default=os.path.join(CATALOG, 'resource_catalog.csv'))
    ap.add_argument('--out', '-o', default=os.path.join(CATALOG, 'relations_full.csv'))
    args = ap.parse_args()

    cat = {r['key']: r for r in csv.DictReader(open(args.catalog))}
    rows = list(csv.DictReader(open(args.relations)))

    # ── corroboration signals, computed across the whole set first ────
    path_counts = Counter((r['source_key'], r['target_key']) for r in rows)
    pairs = {(r['source_key'], r['target_key']) for r in rows}

    stats = Counter()
    for r in rows:
        src = cat.get(r['source_key'], {})
        tgt = cat.get(r['target_key'], {})
        leaf = r['source_path'].split('.')[-1].replace('[]', '')
        notes = []

        # 1. path existence, checked against the operation the path was mined
        # from - not the type's canonical enumerate call. 799 relations come
        # from detail operations (get_app, not list_apps), and validating those
        # against the canonical shape reports a missing path that is really a
        # missing CALL.
        own_op = r.get('operation') or src.get('operation', '')
        canonical = src.get('operation', '')
        service = src.get('service', '')

        # parent_spec names the PARAMETER used to list the child, not a field of
        # the response. The collector supplies that value, so the relation holds
        # regardless of what the payload contains and path checks do not apply.
        if r.get('source') == 'parent_spec':
            r['path_exists'] = 'by_construction'
            r['join_mode'] = 'by_parent'
            r['paths_to_target'] = path_counts[(r['source_key'], r['target_key'])]
            r['bidirectional'] = 'yes' if (r['target_key'], r['source_key']) in pairs else 'no'
            r['needs_operation'] = ''
            r['offline_note'] = 'parent id supplied by the caller, not read from the response'
            r.setdefault('verdict', PENDING)
            stats['by_construction'] += 1
            continue

        # CloudFormation relationshipRef paths are JSON-schema pointers, not API
        # response paths. Comparing them to a botocore shape is meaningless.
        if r.get('source') == 'cfn':
            r['path_exists'] = 'schema_pointer'
            mode, why = join_mode(leaf, tgt)
            r['join_mode'] = mode
            r['paths_to_target'] = path_counts[(r['source_key'], r['target_key'])]
            r['bidirectional'] = 'yes' if (r['target_key'], r['source_key']) in pairs else 'no'
            r['needs_operation'] = ''
            r['offline_note'] = 'CloudFormation schema pointer; needs translation to an API path'
            r.setdefault('verdict', PENDING)
            stats['schema_pointer'] += 1
            continue

        # c7n declares 15 relations with no expression at all: the relation is
        # real but c7n resolves it in custom Python. There is no path to check,
        # and refuting them would discard a known-true edge.
        if not r['source_path']:
            r['path_exists'] = 'no_path_declared'
            r['join_mode'] = 'needs_hand_path'
            r['paths_to_target'] = path_counts[(r['source_key'], r['target_key'])]
            r['bidirectional'] = 'yes' if (r['target_key'], r['source_key']) in pairs else 'no'
            r['needs_operation'] = ''
            r['offline_note'] = 'relation declared without a path; needs a hand-written one'
            r.setdefault('verdict', PENDING)
            stats['no_path_declared'] += 1
            continue

        paths = item_paths(service, own_op)
        if paths is None:
            r['path_exists'] = 'unknown'
            stats['path_unknown'] += 1
        elif r['source_path'] in paths:
            r['path_exists'] = 'yes'
            stats['path_yes'] += 1
        else:
            # Before refuting, look for the operation that DOES return it.
            elsewhere = find_operation_with_path(service, r['source_path'])
            if elsewhere:
                r['path_exists'] = 'other_operation'
                r['needs_operation'] = elsewhere
                stats['found_elsewhere'] += 1
                notes.append(f'not in {own_op}; returned by {elsewhere}')
            else:
                r['path_exists'] = 'no'
                stats['path_no'] += 1
                notes.append(f'path absent from {own_op or "?"} response shape')

        # Whether the canonical collection call actually yields this path. When
        # it does not, the edge is real but needs an extra operation - which the
        # collector must be told, not silently denied.
        r['needs_operation'] = ''
        if r['path_exists'] == 'yes' and own_op and canonical and own_op != canonical:
            canon_paths = item_paths(service, canonical)
            if canon_paths is not None and r['source_path'] not in canon_paths:
                r['needs_operation'] = own_op
                stats['needs_extra_call'] += 1

        # 2. join mode
        mode, why = join_mode(leaf, tgt)
        r['join_mode'] = mode
        stats[f'join_{mode}'] += 1
        if why:
            notes.append(why)

        # 3. corroboration
        n_paths = path_counts[(r['source_key'], r['target_key'])]
        r['paths_to_target'] = n_paths
        r['bidirectional'] = 'yes' if (r['target_key'], r['source_key']) in pairs else 'no'

        # Independent agreement upgrades a mined guess. Several distinct paths
        # from the same resource to the same target, or a mutual reference, are
        # the same kind of evidence as two catalogs agreeing.
        if r.get('confidence') == 'medium' and not r.get('corroborated_by'):
            if n_paths > 1 or r['bidirectional'] == 'yes':
                r['confidence'] = 'high'
                r['corroborated_by'] = ('multi-path' if n_paths > 1 else '') + \
                    (',bidirectional' if r['bidirectional'] == 'yes' else '')
                r['corroborated_by'] = r['corroborated_by'].strip(',')
                stats['upgraded'] += 1

        # Only a structural impossibility refutes offline.
        if r['path_exists'] == 'no' or mode == 'impossible':
            r['verdict'] = REFUTED
            stats['refuted'] += 1
        else:
            r.setdefault('verdict', PENDING)
        r['offline_note'] = '; '.join(notes)

    fields = list(rows[0].keys())
    for extra in EXTRA_FIELDS + ['verdict']:
        if extra not in fields:
            fields.append(extra)

    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f'Annotated {len(rows)} relations → {args.out}', file=sys.stderr)
    print(f"\n  path exists      yes={stats['path_yes']}  no={stats['path_no']}  "
          f"unknown={stats['path_unknown']}", file=sys.stderr)
    print(f"  join mode        by_id={stats['join_by_id']}  by_arn={stats['join_by_arn']}  "
          f"by_name={stats['join_by_name']}  impossible={stats['join_impossible']}",
          file=sys.stderr)
    print(f"\n  REFUTED offline  : {stats['refuted']}", file=sys.stderr)
    print(f"  upgraded to high : {stats['upgraded']} "
          f"(multi-path or bidirectional)", file=sys.stderr)
    conf = Counter(r.get('confidence') for r in rows)
    print(f"  confidence now   : {dict(conf)}", file=sys.stderr)
    surviving = [r for r in rows if r.get('verdict') != REFUTED]
    print(f"  surviving        : {len(surviving)}", file=sys.stderr)


if __name__ == '__main__':
    main()
