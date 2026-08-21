#!/usr/bin/env python3
"""
Which fields each resource type shows, derived from what it actually emits.

    python3 scripts/build-detail-fields.py            # report what would change
    python3 scripts/build-detail-fields.py --write    # write detail_fields.csv

`detail_fields.csv` drives two things at once: what `emit._metadata()` stores in
`inventory_assets.metadata`, and what columns a resource's panel shows. Both
need the same answer — a field worth storing is worth showing — so there is one
list and this builds it.

DERIVED, not invented. It reads the real payloads in `out/assets.json` and
proposes only fields that are actually there, with the type they actually hold.
A column that cannot be filled is worse than a missing one: it reads as "this
resource has no encryption setting" when the truth is "nobody asked".

SOME TYPES GET NO COLUMNS, AND THAT IS THE ANSWER. Fourteen types — 35 of
1,030 resources, 3% of the estate — carry only an identifier or only lists.
`gamelift.location` is a name; `ec2.internet_gateway` is an id and an
`Attachments` list, which is Tier 3. Two of them (`iam.iam_oidc_provider`,
`eks.addon`) would gain real fields from a second API call, and that call would
run on every scan for two and three resources respectively. The cost is not
worth it, and a panel showing identity alone is honest about a resource that is
identity alone.

Hand-authored rows WIN. A row already carrying a label or a reason keeps both —
the generator fills coverage, humans decide what a thing is called and why it
earns a column. Re-running never silently rewrites a judgement.
"""
import argparse
import collections
import csv
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ASSETS = os.path.join(ROOT, 'out', 'assets.json')
CATALOG = os.path.join(ROOT, 'providers', 'aws', 'catalog')
OUT = os.path.join(CATALOG, 'detail_fields.csv')

# Columns a panel already has from the asset envelope — Tier 1. Repeating them
# as Tier 2 would show the same value twice under two names.
#
# Matched on VALUE, not on the field name. `TransitGatewayId`, `FileSystemArn`
# and `AlarmName` are all identity wearing a service prefix, and no name pattern
# catches every spelling AWS uses. Comparing what the field HOLDS against what
# the envelope already shows is exact.
IDENTITY = {'tags', 'region', 'availabilityzone', 'accountid', 'ownerid', 'owner'}

# Fields nobody reads on a diagram: request bookkeeping, opaque tokens, and the
# long-form text that belongs in a payload viewer rather than a column.
NOISE = ('requestid', 'nexttoken', 'marker', 'clienttoken', 'revisionid',
         'checksum', 'sha256', 'etag', 'signature', 'certificatebody',
         'policydocument', 'userdata', 'description')

# Noise only as the WHOLE leaf. `Timestamp` beside `SizeInBytes.Value` is when
# the measurement was taken, which no panel shows — but `CreationTimestamp` is
# when the resource was made, which every panel wants. Substring-matching the
# first would silently eat the second.
NOISE_EXACT = {'timestamp'}

# Whole subtrees that describe the CALL, not the resource. `ResponseMetadata` is
# the SDK's HTTP envelope — status code, host id, retry count — and it rides
# along on every `describe_*` payload. It is about our request, and a panel that
# showed `http_status_code: 200` would be reporting on itself.
NOISE_TREES = ('ResponseMetadata',)

# Leaves too generic to head a column. `Value`, `Size` and `Mode` mean nothing
# without their parent: `EphemeralStorage.Size` is a disk, `SizeInBytes.Value`
# is a byte count, and a column headed `size` next to another headed `value`
# tells the reader neither. These take the full path instead.
GENERIC_LEAVES = {'value', 'size', 'mode', 'code', 'name', 'key', 'type',
                  'status', 'state', 'enabled', 'quantity', 'count', 'id',
                  'arn', 'version'}

# How many columns one type may propose. Past this a panel is a payload dump,
# and the payload is one click away in full.
MAX_COLUMNS = 12

# Longest value that still reads as a cell. Judged on the VALUE, not the name,
# for the same reason identity is: SNS calls its 468-character IAM document
# `Policy` and its delivery config `EffectiveDeliveryPolicy`, while
# `BlockPublicPolicy` is a boolean and `PolicyName` is a short string. No name
# pattern separates those; length does.
MAX_CELL = 120


def flatten(payload, prefix='', depth=0):
    """`{'State': {'Name': 'running'}}` -> `State.Name`. One level only.

    Deeper nesting is structure, not a column: `BlockDeviceMappings[*].Ebs` is
    the composition tier, which reads the node's children instead.
    """
    for key, value in (payload or {}).items():
        path = f'{prefix}{key}'
        if isinstance(value, dict) and depth == 0:
            yield from flatten(value, f'{path}.', depth + 1)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            yield path, value


def kind_of(values):
    """The `type` column: how `emit` should coerce this field."""
    real = [v for v in values if v not in (None, '')]
    if not real:
        return 'str'
    if all(isinstance(v, bool) for v in real):
        return 'bool'
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in real):
        return 'num'
    return 'str'


def _snake(text):
    import re

    snake = re.sub(r'(?<!^)(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])', '_', text).lower()
    return re.sub(r'_+', '_', snake).strip('_')


def label_for(path, taken=()):
    """
    `State.Name` -> `state`, `DBInstanceClass` -> `db_instance_class`.

    The leaf alone is the readable name and usually unique, but not always: a
    CloudFront distribution carries `Aliases.Quantity` AND
    `CacheBehaviors.Quantity`, which both leaf to `quantity` and would write the
    same metadata key twice. When the leaf is taken, the parent joins it — and
    a leaf too generic to stand alone takes the parent whether it collides or
    not, because `size` is not a column heading, `ephemeral_storage_size` is.
    """
    leaf = _snake(path.split('.')[-1])
    if leaf not in taken and not ('.' in path and leaf in GENERIC_LEAVES):
        return leaf
    full = _snake(path.replace('.', '_'))
    if full not in taken:
        return full
    n = 2
    while f'{full}_{n}' in taken:
        n += 1
    return f'{full}_{n}'


def classify(raws):
    """
    Sort one type's payload fields into columns and rejects.

    Returns `(scored, rejected)` — the fields worth a column, ranked, and a
    `{path: why}` map for the rest. The reasons are returned rather than merely
    counted so `build-panel-reference.py` can print the true reason a type has
    no columns. A reference that guesses the reason separately will eventually
    print something the generator does not believe.
    """
    seen = collections.defaultdict(list)
    identity_paths = set()
    for raw, envelope in raws:
        for path, value in flatten(raw):
            seen[path].append(value)
            # This field IS the id, the ARN or the name the envelope shows.
            if value is not None and str(value) in envelope:
                identity_paths.add(path)

    scored, rejected = [], {}
    for path, values in seen.items():
        head, _, tail = path.rpartition('.')
        leaf = tail.lower()
        if path in identity_paths:
            rejected[path] = 'already in the envelope'
        elif leaf in IDENTITY or leaf in NOISE_EXACT or any(n in leaf for n in NOISE):
            rejected[path] = 'noise'
        elif path.split('.')[0] in NOISE_TREES:
            rejected[path] = 'about the call, not the resource'
        # AWS states arrive twice: `State.Name` = "running" beside
        # `State.Code` = 16. The number is the same fact in a form nobody
        # reads, so the word wins wherever both are present.
        elif leaf == 'code' and f'{head}.Name' in seen:
            rejected[path] = 'numeric twin of a named state'
        elif not any(v not in (None, '', [], {}) for v in values):
            rejected[path] = 'empty across the estate'
        elif max((len(str(v)) for v in values if v is not None), default=0) > MAX_CELL:
            rejected[path] = 'too long to be a cell'
        else:
            filled = sum(1 for v in values if v not in (None, '', [], {}))
            # Fill rate first — a field two resources in ten carry says less
            # than one they all do. Path length breaks ties toward the shallow.
            scored.append((-filled / len(raws), len(path), path, values))

    # A payload key holding a list or a nested object never reaches `flatten`,
    # so it is absent from both maps. That absence is itself an answer — the
    # content is composition, which Tier 3 reads from edges.
    for raw, _ in raws:
        for key, value in (raw or {}).items():
            if isinstance(value, (list, dict)) and key not in seen:
                rejected.setdefault(key, 'a list or nested object — Tier 3 reads it')
    return scored, rejected


def existing_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline='') as fh:
        return [r for r in csv.DictReader(fh) if r.get('resource_key')]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--max', type=int, default=MAX_COLUMNS)
    args = parser.parse_args(argv)

    if not os.path.exists(ASSETS):
        print(f'{ASSETS} not found — run the discover stage first', file=sys.stderr)
        return 1
    with open(ASSETS) as fh:
        assets = json.load(fh)
    assets = assets if isinstance(assets, list) else assets.get('assets', [])

    # Every payload for a type, so fill rate can decide what is worth a column.
    payloads = collections.defaultdict(list)
    # Which top-level key each enrich call contributed, recorded by the
    # collector while it still knew. After the merge the payload is flat, and a
    # field that cost a second API call looks exactly like a free one.
    origin = collections.defaultdict(dict)
    for asset in assets:
        envelope = {str(asset.get(k) or '') for k in ('id', 'arn', 'name')} - {''}
        payloads[asset['resource_key']].append((asset.get('raw') or {}, envelope))
        for operation, keys in (asset.get('enriched_by') or {}).items():
            for k in keys:
                origin[asset['resource_key']][k] = f'enrich:{operation}'

    kept = existing_rows(OUT)
    authored = {(r['resource_key'], r['field']): r for r in kept}
    # Labels a type has already spent, hand-authored or proposed. One label per
    # type, or two paths write the same metadata key and the panel shows a
    # column twice.
    used = collections.defaultdict(set)
    for r in kept:
        used[r['resource_key']].add(r['label'])
    proposed, skipped = [], collections.Counter()

    for rtype, raws in sorted(payloads.items()):
        scored, rejected = classify(raws)
        skipped.update(collections.Counter(rejected.values()))

        for _, _, path, values in sorted(scored)[:args.max]:
            key = (rtype, path)
            if key in authored:
                continue
            label = label_for(path, used[rtype])
            used[rtype].add(label)
            proposed.append({
                'resource_key': rtype, 'field': path, 'label': label,
                'type': kind_of(values),
                'source': origin[rtype].get(path.split('.')[0], 'list'),
                'reason': f'{sum(1 for v in values if v not in (None, ""))}'
                          f'/{len(values)} carry it',
            })

    by_type = collections.Counter(r['resource_key'] for r in proposed)
    print(f'types with payloads      : {len(payloads)}')
    print(f'types already declared   : {len({r["resource_key"] for r in kept})}')
    print(f'columns already authored : {len(kept)}')
    print(f'columns proposed         : {len(proposed)} across {len(by_type)} types')
    print(f'skipped                  : {dict(skipped)}')
    if not args.write:
        print('\ntop proposals:')
        for rtype, n in by_type.most_common(8):
            cols = [p['label'] for p in proposed if p['resource_key'] == rtype][:6]
            print(f'  {rtype:34} +{n:3}  {", ".join(cols)}')
        print('\n--write to apply')
        return 0

    rows = kept + proposed
    rows.sort(key=lambda r: (r['resource_key'], r['label']))
    with open(OUT, 'w', newline='') as fh:
        writer = csv.DictWriter(
            fh, fieldnames=['resource_key', 'field', 'label', 'type', 'source', 'reason'])
        writer.writeheader()
        writer.writerows(rows)
    print(f'\nwrote {len(rows)} rows across '
          f'{len({r["resource_key"] for r in rows})} types -> {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
