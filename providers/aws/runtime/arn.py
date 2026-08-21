"""
ARN construction and parsing.

An ARN is the only globally unique, self-describing handle a resource has.
That makes it two things at once here:

  * the join key for edges. `lambda -> KMSKeyArn` yields an ARN, but kms-key
    nodes are keyed by KeyId. Without ARNs that edge dangles forever.
  * the strongest validation signal available. An ARN names its own service
    and resource type, so `parse()` alone can confirm or refute a relation
    with no API call and no docstring.

The build algorithm is ported from c7n 0.9.35 - `c7n.utils.generate_arn` and
`QueryResourceManager.get_arns` - because c7n already solved the per-service
irregularities and its `resource_type` metadata is what `arn_recipes.csv` is
generated from. Deviating from it would desync the recipes and the builder.
"""

import re
from collections import namedtuple

# arn:partition:service:region:account-id:resource
# `resource` is the whole remainder: it may itself contain ':' or '/', so the
# split is capped at 5 and the tail kept intact.
_ARN_RE = re.compile(r'^arn:([^:]*):([^:]*):([^:]*):([^:]*):(.+)$', re.S)

Arn = namedtuple('Arn', 'partition service region account resource_type resource_id raw')

# c7n's REGION_PARTITION_MAP is keyed by full region name; prefix matching
# covers regions newer than the installed c7n.
_PARTITION_PREFIX = (
    ('cn-', 'aws-cn'),
    ('us-gov-', 'aws-us-gov'),
    ('us-iso', 'aws-iso'),
)

# S3 ARNs carry neither region nor account: arn:aws:s3:::bucket. c7n blanks the
# region for s3; the account must be blanked too or every bucket ARN is wrong.
_NO_REGION = {'s3', 'iam', 'route53', 'cloudfront', 'organizations', 'waf'}
_NO_ACCOUNT = {'s3'}


class NoArnForResource(ValueError):
    """Raised for the resource types that genuinely have no ARN."""


def partition_for(region):
    """Pick the ARN partition from a region name."""
    if not region:
        return 'aws'
    for prefix, partition in _PARTITION_PREFIX:
        if region.startswith(prefix):
            return partition
    return 'aws'


def parse(value):
    """
    Decompose an ARN string, or return None if it is not one.

    The resource tail comes in three documented shapes, all handled:
        instance/i-abc          type + '/' + id
        function:my-func        type + ':' + id
        my-bucket               bare id, no type
    """
    if not isinstance(value, str) or not value.startswith('arn:'):
        return None
    m = _ARN_RE.match(value)
    if not m:
        return None
    partition, service, region, account, tail = m.groups()

    if '/' in tail:
        rtype, _, rid = tail.partition('/')
    elif ':' in tail:
        rtype, _, rid = tail.partition(':')
    else:
        rtype, rid = '', tail
    return Arn(partition, service, region, account, rtype, rid, value)


def build(recipe, resource, region=None, account_id=None):
    """
    Produce the ARN for one resource.

    `recipe` is a row from arn_recipes.csv; `resource` is the raw AWS dict.
    Mirrors c7n's three-way rule in QueryResourceManager.get_arns:
      1. the type declares an ARN field  -> read it straight out of the JSON
      2. the id is itself already an ARN -> use it
      3. otherwise                       -> construct
    """
    if recipe.get('has_arn') == 'false':
        raise NoArnForResource(f"{recipe['resource']} has no ARN")

    arn_field = recipe.get('arn_field')
    if arn_field:
        existing = resource.get(arn_field)
        if existing:
            return existing
        # Fall through and construct: the field is declared but some responses
        # omit it (notably list-then-describe types seen only in list form).

    rid = resource.get(recipe['id_field'])
    if rid is None:
        return None
    rid = str(rid)
    if rid.startswith('arn:'):
        return rid

    return build_from_id(recipe, rid, region, account_id)


def build_from_id(recipe, rid, region=None, account_id=None):
    """Construct an ARN from a bare id. Split out so validation can call it."""
    service = recipe['service']
    if not service:
        return None

    if recipe.get('global_resource') == 'true' or service in _NO_REGION:
        region = ''
    if service in _NO_ACCOUNT:
        account_id = ''

    partition = partition_for(region)
    arn = f"arn:{partition}:{service}:{region or ''}:{account_id or ''}:"

    arn_type = recipe.get('arn_type') or ''
    if arn_type:
        separator = recipe.get('arn_separator') or '/'
        if rid.startswith(separator):
            separator = ''
        return f'{arn}{arn_type}{separator}{rid}'
    return f'{arn}{rid}'


def matches_type(value, recipe):
    """
    True if an ARN string is consistent with a resource type's recipe.

    Ladder level 3 - the strongest offline check we have. An ARN states its own
    service and resource type, so a claimed `-> kms-key` edge whose value parses
    to service 'ec2' is provably wrong before any API call.
    """
    arn = parse(value)
    if not arn:
        return None                      # not an ARN; this check does not apply
    if recipe.get('service') and arn.service != recipe['service']:
        return False
    expected = recipe.get('arn_type')
    if expected and arn.resource_type and arn.resource_type != expected:
        return False
    return True


def matches_prefix(value, recipe):
    """
    True if a bare id carries the target type's id_prefix.

    Ladder level 2. `vpc-0a1b2c` can only be a VPC, so a relation pointing at
    vpc whose value lacks `vpc-` is wrong. Returns None when the type declares
    no prefix and the check cannot be applied.
    """
    prefix = recipe.get('id_prefix')
    if not prefix or not isinstance(value, str):
        return None
    if value.startswith('arn:'):
        return None                      # ARN-valued; use matches_type instead
    return value.startswith(prefix)
