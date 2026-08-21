"""
The canonical asset record — the contract every provider fills and every
engine reads.

`cspm_asset.v2` extends the `v1` shape already in use by the FinOps platform.
Everything v1 declared is kept, with the same names and meanings, so a v1
consumer can read a v2 record unchanged. v2 adds one block: `topology`.

Why the extension is needed: v1 describes an asset in isolation — what it is,
where it lives, what it costs. It has no way to say what an asset is *inside*
or what *reaches* it, which is exactly what a security or blast-radius question
turns on. A public bucket nothing reaches is not the emergency that one behind
an internet gateway is, and v1 cannot express the difference.

Why it is a separate module: both the collectors that produce assets and the
engines that consume them depend on this contract, and neither may depend on
the other. Keeping the schema here is what stops that dependency forming.

Deliberately plain dicts rather than Pydantic models: the AWS collector runs in
a Lambda whose dependencies are pinned by Cloud Custodian, and a schema is not
worth a dependency conflict. A dict validated here drops straight into the
FinOps platform's Pydantic `Asset` as `Asset(**record)`.
"""
import hashlib
import json

SCHEMA_VERSION = 'cspm_asset.v2'

PROVIDERS = ('aws', 'azure', 'gcp', 'oci', 'ibm', 'kubernetes')

# Whether the resource belongs to a region or sits above all of them. IAM and
# Route 53 are global in AWS; the same split exists in every provider, which is
# why it belongs in the shared contract rather than in the AWS layer model.
SCOPES = ('global', 'regional')

# v1 fields, unchanged.
V1_FIELDS = (
    'schema_version', 'tenant_id', 'scan_run_id', 'provider', 'account_id',
    'region', 'scope', 'resource_type', 'resource_id', 'resource_uid',
    'name', 'tags', 'metadata', 'hash_sha256',
)

# v2 adds exactly one field, holding everything positional.
V2_FIELDS = V1_FIELDS + ('topology',)

# The keys `topology` may carry. Named here so a provider cannot invent its own
# vocabulary: `vpc_id` is an AWS word, `container_uid` is not.
TOPOLOGY_FIELDS = (
    'layer_id',         # where it sits in the drawn hierarchy
    'layer_name',
    'container_uid',    # the uid of the thing it is inside - VPC, subnet, RG
    'parent_uid',       # the uid of the thing it hangs off - instance, cluster
    'zone',             # availability zone / zone / datacenter
    'owner_account',    # set when the asset is shared in from elsewhere
    'uid_quality',      # how the uid was arrived at; see cspm.uid
    'native_type',      # the provider's own type string, kept for round-trips
)

# Identity is what makes two records the same asset across scans, so the hash
# covers exactly the fields that decide identity - never mutable state like
# tags or metadata, which would make every tag edit look like a new resource.
IDENTITY_FIELDS = ('provider', 'account_id', 'region', 'resource_type',
                   'resource_id', 'resource_uid')


class SchemaError(ValueError):
    """A record that cannot be trusted to describe anything."""


def compute_hash(record):
    """SHA256 over the identity fields. Matches the v1 platform's intent."""
    payload = {field: str(record.get(field) or '') for field in IDENTITY_FIELDS}
    payload['name'] = str(record.get('name') or '')
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()


def make(provider, account_id, region, resource_type, resource_id,
         resource_uid, name='', tags=None, metadata=None, topology=None,
         scope='regional', tenant_id='', scan_run_id=''):
    """Build a canonical record. The hash is derived, never passed in."""
    record = {
        'schema_version': SCHEMA_VERSION,
        'tenant_id': tenant_id,
        'scan_run_id': scan_run_id,
        'provider': provider,
        'account_id': str(account_id or ''),
        'region': region or '',
        'scope': scope,
        'resource_type': resource_type,
        'resource_id': str(resource_id or ''),
        'resource_uid': resource_uid,
        'name': name or '',
        'tags': dict(tags or {}),
        'metadata': dict(metadata or {}),
        'topology': {k: v for k, v in (topology or {}).items() if k in TOPOLOGY_FIELDS},
    }
    record['hash_sha256'] = compute_hash(record)
    return record


def validate(record, strict=True):
    """
    Check one record against the contract.

    Returns a list of problems; empty means valid. `strict` also rejects
    unknown top-level keys, which is what catches a provider quietly smuggling
    its own vocabulary into the shared shape.
    """
    problems = []
    for field in ('provider', 'account_id', 'resource_type', 'resource_id',
                  'resource_uid'):
        if not record.get(field):
            problems.append(f'missing required field: {field}')

    provider = record.get('provider')
    if provider and provider not in PROVIDERS:
        problems.append(f'unknown provider: {provider!r}')

    scope = record.get('scope')
    if scope and scope not in SCOPES:
        problems.append(f'scope must be one of {SCOPES}, got {scope!r}')

    if scope == 'regional' and not record.get('region'):
        problems.append('a regional asset must name its region')

    if not isinstance(record.get('tags', {}), dict):
        problems.append('tags must be a mapping, not a list of Key/Value pairs')

    topology = record.get('topology') or {}
    if not isinstance(topology, dict):
        problems.append('topology must be a mapping')
    else:
        unknown = sorted(set(topology) - set(TOPOLOGY_FIELDS))
        if unknown:
            problems.append(f'topology carries provider-specific keys: {unknown}')

    if strict:
        extra = sorted(set(record) - set(V2_FIELDS))
        if extra:
            problems.append(f'unknown top-level fields: {extra}')

    expected = compute_hash(record)
    if record.get('hash_sha256') and record['hash_sha256'] != expected:
        problems.append('hash_sha256 does not match the identity fields')

    return problems


def check(record):
    """validate(), but raising. For call sites that cannot continue on error."""
    problems = validate(record)
    if problems:
        raise SchemaError('; '.join(problems))
    return record


def to_v1(record):
    """
    Drop to the v1 shape.

    The FinOps platform's Pydantic model declares
    `schema_version: Literal["cspm_asset.v1"]`, so a v2 record must be narrowed
    before it can be constructed there. Topology is dropped rather than folded
    into metadata: metadata is evaluated by cost rules, and quietly seeding it
    with positional keys would change what those rules match on.
    """
    out = {field: record[field] for field in V1_FIELDS if field in record}
    out['schema_version'] = 'cspm_asset.v1'
    return out
