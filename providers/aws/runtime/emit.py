"""
Discovery's AWS assets, expressed in the shared `cspm_asset` contract.

This is the AWS provider's side of the multi-cloud boundary. Everything above
it — cost rules, compliance findings, the UI — reads canonical records and
never an AWS-shaped one, which is what lets a second provider be added without
touching any consumer.

Almost all of it is renaming, because the two designs converged independently:
discovery's `resource_key` is already `s3.bucket` and its `asset_id` is already
the ARN. The real work is the split between `metadata` and `topology` — cost
rules evaluate metadata, so anything positional must stay out of it.
"""
import csv
import os
import re
from datetime import datetime, timezone

from cspm import schema, uid as uidlib

from . import arn as arnlib

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')

PROVIDER = 'aws'

# Discovery's layer ids, mapped to the contract's two-value scope. G0 is the
# global layer - IAM, Route 53, CloudFront - which every provider has an
# equivalent of, which is why scope is in the shared contract and layer is not.
GLOBAL_LAYERS = {'G0'}

# Fields the collector attaches for its own bookkeeping. They describe the
# scan, not the resource, so they do not belong in a canonical record.
INTERNAL = {'asset_id', 'raw', 'discovered_by', 'resource_key', 'resource_name',
            'service', 'cfn_type', 'id', 'arn', 'arn_source', 'account_name',
            'availability_zone', 'layer_id', 'layer_name', 'overlay_group',
            'owner_account', 'parent_asset_id', 'tags', 'name', 'account_id',
            'region'}


def _tags(value):
    """AWS returns tags three different ways; the contract wants a mapping."""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        out = {}
        for tag in value:
            if isinstance(tag, dict):
                key = tag.get('Key', tag.get('key'))
                if key is not None:
                    out[str(key)] = str(tag.get('Value', tag.get('value', '')))
        return out
    return {}


# The semantic fields cost rules and the pricer evaluate, mapped from the raw
# AWS payload the collector already holds. Extracting here costs no extra API
# call - the payload is in hand - and it is what turns "685 assets
# unpriceable" into dollars. One entry per type: (metadata key, raw key,
# coercion).
_NUM = lambda v: float(v) if isinstance(v, (int, float, str)) and str(v).strip() else None
_STR = lambda v: str(v) if v not in (None, '') else None
_BOOL = lambda v: bool(v) if isinstance(v, bool) else None

# Which raw fields are worth keeping, per resource type.
#
# Read from `detail_fields.csv`, not declared here, because there were TWO of
# these lists: this one drove `inventory_assets.metadata` and the CSV drove the
# detail panel, and where they overlapped they had drifted apart —
# `ec2.instance` shared only `state` between them, `s3.bucket` shared nothing.
# Two lists of the same thing with nothing keeping them in step is the defect
# this catalog exists to prevent.
#
# One list now, two consumers: a field worth storing for a cost rule is worth
# showing in a panel, and a field worth showing is worth storing.
_COERCE = {
    'str': lambda v: str(v) if v not in (None, '') else None,
    'num': lambda v: float(v) if isinstance(v, (int, float, str)) and str(v).strip() else None,
    'bool': lambda v: bool(v) if isinstance(v, bool) else None,
    # Truthy at all — a volume with any attachment, an address with any
    # association. The question is "is this attached", not "to what".
    'present': lambda v: bool(v) if v is not None else None,
    # CloudWatch reports bytes; every rule and every reader wants GB.
    'bytes_gb': lambda v: (round(float(v) / 1024 ** 3, 4)
                           if v not in (None, '') else None),
}


def _load_detail_fields(path=None):
    """`detail_fields.csv` -> {resource_key: [(label, raw_path, coerce), ...]}."""
    path = path or os.path.join(CATALOG, 'detail_fields.csv')
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            key = (row.get('resource_key') or '').strip()
            field = (row.get('field') or '').strip()
            label = (row.get('label') or '').strip()
            if not (key and field and label):
                continue
            coerce = _COERCE.get((row.get('type') or 'str').strip(), _COERCE['str'])
            out.setdefault(key, []).append((label, field, coerce))
    return out


RAW_FIELDS = _load_detail_fields()


def _dig(payload, path):
    """`State.Name` → payload['State']['Name'], tolerating absence."""
    node = payload
    for part in path.split('.'):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _metadata(asset, keep_raw=False):
    """
    The semantic fields a rule evaluates.

    Two sources: the collector's own non-internal fields, plus the mapped raw
    payload above. A rule that needs a field it cannot get still finds it
    absent rather than wrong, which is the safer failure.
    """
    metadata = {}
    for key, value in asset.items():
        if key not in INTERNAL and value not in (None, '', [], {}):
            metadata[key] = value

    payload = asset.get('raw')
    if isinstance(payload, dict):
        for name, path, coerce in RAW_FIELDS.get(asset.get('resource_key'), ()):
            try:
                value = coerce(_dig(payload, path))
            except (TypeError, ValueError):
                value = None
            if value is not None:
                metadata[name] = value

    # `age_days` is the single most-used condition across the cost rules
    # (stale snapshots, orphaned AMIs, unattached IPs, lifecycle gaps), and
    # every one of these types already carries a creation timestamp.
    age = _age_days(metadata)
    if age is not None:
        metadata['age_days'] = age

    if keep_raw and payload:
        metadata['raw'] = payload
    return metadata


_TIME_FIELDS = ('start_time', 'create_time', 'creation_date', 'launch_time',
                'last_modified')


def _age_days(metadata):
    for field in _TIME_FIELDS:
        raw = metadata.get(field)
        if not raw:
            continue
        text = str(raw).strip().replace('Z', '+00:00')
        # AWS returns several shapes: ISO, ISO with millis and no colon in the
        # offset, and boto's stringified datetime.
        for cleanup in (lambda s: s,
                        lambda s: s.replace(' ', 'T', 1),
                        lambda s: re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', s),
                        lambda s: re.sub(r'\.\d+', '', s)):
            try:
                parsed = datetime.fromisoformat(cleanup(text))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return round((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 1)
    return None


def _topology(asset):
    """Where the asset sits. The v2 extension, and the reason for it."""
    return {
        'layer_id': asset.get('layer_id', ''),
        'layer_name': asset.get('layer_name', ''),
        'container_uid': asset.get('parent_asset_id', ''),
        'parent_uid': asset.get('parent_asset_id', ''),
        'zone': asset.get('availability_zone', ''),
        'owner_account': asset.get('owner_account', ''),
        'uid_quality': '',            # filled below, once the uid is graded
        'native_type': asset.get('cfn_type', ''),
    }


def _resource_id(asset, arn):
    """
    The provider-specific id, recovered from the ARN where the API did not
    return one in a field of its own.

    911 of one account's assets had a real ARN and an empty id - log streams,
    attached policies, parameter groups - because the operation that lists them
    returns only the ARN. The id is the ARN's own tail, so deriving it costs
    nothing and keeps `resource_id` meaning the same thing for every record.
    """
    if asset.get('id'):
        return str(asset['id'])
    parsed = arnlib.parse(arn)
    return parsed.resource_id if parsed and parsed.resource_id else ''


def to_cspm(asset, tenant_id='', scan_run_id='', keep_raw=False):
    """One discovery asset as a canonical record."""
    arn = asset.get('arn') or ''
    resource_uid, quality = uidlib.grade(
        PROVIDER, arn, asset.get('arn_source') or 'field')

    # An asset with no usable ARN still exists and must stay visible, so it is
    # keyed on what it does have. Grading records that this is weaker evidence
    # than an ARN the API returned.
    if not resource_uid:
        resource_uid = (f"{PROVIDER}:{asset.get('account_id', '')}:"
                        f"{asset.get('region', '')}:"
                        f"{asset.get('resource_key', '')}:"
                        f"{asset.get('id', '')}")
        quality = 'synthetic'

    topology = _topology(asset)
    topology['uid_quality'] = quality

    layer = asset.get('layer_id', '')
    scope = 'global' if layer in GLOBAL_LAYERS else 'regional'

    return schema.make(
        provider=PROVIDER,
        account_id=asset.get('account_id', ''),
        # A global asset has no region, and claiming one would place it in
        # whichever region happened to be scanned first.
        region='' if scope == 'global' else asset.get('region', ''),
        scope=scope,
        resource_type=asset.get('resource_key', ''),
        resource_id=_resource_id(asset, arn),
        resource_uid=resource_uid,
        name=asset.get('name', ''),
        tags=_tags(asset.get('tags')),
        metadata=_metadata(asset, keep_raw=keep_raw),
        topology=topology,
        tenant_id=tenant_id,
        scan_run_id=scan_run_id,
    )


def emit(assets, tenant_id='', scan_run_id='', keep_raw=False, validate=True):
    """
    Canonical records for a whole collection.

    Returns (records, problems). Invalid records are still returned - dropping
    them would make a broken mapping look like an empty account - but each is
    reported with what is wrong.
    """
    records, problems = [], []
    for asset in assets:
        record = to_cspm(asset, tenant_id, scan_run_id, keep_raw)
        records.append(record)
        if validate:
            for issue in schema.validate(record):
                problems.append({'resource_uid': record['resource_uid'],
                                 'resource_type': record['resource_type'],
                                 'problem': issue})
    return records, problems
