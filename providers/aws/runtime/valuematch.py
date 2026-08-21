"""
Mechanism C (`value-match`) — edges where neither end carries the other's id.

Mechanism A follows an id. This one exists for the cases where there is no id to
follow: a Route 53 alias names a load balancer by DNS name, a VPC endpoint names
the service it fronts as `com.amazonaws.<region>.s3`, a security-group rule
names a network by CIDR. No amount of better documentation would let a
field-pointer resolver find these, because the value has to be *interpreted*
before it identifies anything.

One matcher per `match_kind` in value_joins.csv. They are deliberately separate
functions rather than one clever comparison, because the notion of "matches"
genuinely differs: string equality, substring extraction, CIDR containment.

The `aws_service_name` matcher is the one that completes the private-service
path - it is what turns "this VPC has an endpoint" into "this VPC reaches S3
without traversing the internet".
"""

import csv
import ipaddress
import os
import re

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')

# com.amazonaws.<region>.<service>          an AWS-published service
# com.amazonaws.vpce.<region>.vpce-svc-xxx  a CUSTOMER-published one
AWS_SERVICE_RE = re.compile(r'^com\.amazonaws\.(?!vpce\.)[a-z0-9-]+\.(?P<service>.+)$')
CUSTOMER_SERVICE_RE = re.compile(
    r'^com\.amazonaws\.vpce\.[a-z0-9-]+\.(?P<service_id>vpce-svc-[0-9a-f]+)$')

# <bucket>.s3.<region>.amazonaws.com, and the older <bucket>.s3.amazonaws.com
S3_ORIGIN_RE = re.compile(r'^(?P<bucket>[^.]+)\.s3[.-](?:[a-z0-9-]+\.)?amazonaws\.com$')

DEFAULT_ROUTES = {'0.0.0.0/0', '::/0'}


def load_rules(path=None):
    path = path or os.path.join(CATALOG, 'value_joins.csv')
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


# ── matchers ──────────────────────────────────────────────────────────

def match_aws_service_name(value, _target=None):
    """
    Resolve a VPC endpoint's ServiceName.

    Returns (kind, identifier): `aws` with the service name for an AWS-published
    endpoint, `customer` with the vpce-svc id for one published by another
    account. The distinction matters more than the parse - a customer service is
    a dependency on someone else's account.
    """
    if not isinstance(value, str):
        return None, None
    customer = CUSTOMER_SERVICE_RE.match(value)
    if customer:
        return 'customer', customer.group('service_id')
    aws = AWS_SERVICE_RE.match(value)
    if aws:
        # `s3`, but also compound names like `execute-api` and `s3-outposts`.
        return 'aws', aws.group('service')
    return None, None


def match_dns_name(value, target_value):
    """
    DNS-name equality, case-insensitively and ignoring a trailing dot.

    Route 53 stores alias targets with a trailing dot and sometimes a `dualstack.`
    prefix that the load balancer's own DNSName does not carry, so a raw string
    comparison misses the match it is there to make.
    """
    if not isinstance(value, str) or not isinstance(target_value, str):
        return False
    left = value.rstrip('.').lower()
    right = target_value.rstrip('.').lower()
    for prefix in ('dualstack.', 'ipv6.'):
        if left.startswith(prefix):
            left = left[len(prefix):]
        if right.startswith(prefix):
            right = right[len(prefix):]
    return left == right


def match_s3_origin(value, bucket_name):
    """A CloudFront origin domain embeds the bucket name; pull it out first."""
    if not isinstance(value, str):
        return False
    found = S3_ORIGIN_RE.match(value.rstrip('.').lower())
    return bool(found) and found.group('bucket') == str(bucket_name).lower()


def match_arn(value, target_value):
    return isinstance(value, str) and value == target_value


def match_cidr_contains(value, target_cidr):
    """
    True when `value` is a CIDR that contains `target_cidr`.

    0.0.0.0/0 is excluded deliberately: it contains every subnet, so treating it
    as a match would draw an edge from an open rule to every network in the
    estate. An open rule is a finding about the internet, not about a subnet.
    """
    try:
        rule = ipaddress.ip_network(str(value), strict=False)
        target = ipaddress.ip_network(str(target_cidr), strict=False)
    except (ValueError, TypeError):
        return False
    if str(rule) in DEFAULT_ROUTES:
        return False
    return rule.version == target.version and target.subnet_of(rule)


def match_cidr_is_default(value, _target=None):
    """True for 0.0.0.0/0 or ::/0 — the value that means 'the internet'."""
    return str(value).strip() in DEFAULT_ROUTES


def match_instance_or_ip(value, target_value):
    """
    An ELB target is an instance id when TargetType is `instance` and a raw IP
    when it is `ip`. The value's own shape decides which, so no target-type
    lookup is needed.
    """
    if not isinstance(value, str):
        return False
    if value.startswith('i-'):
        return value == target_value
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return value == target_value


MATCHERS = {
    'aws_service_name': match_aws_service_name,
    'dns_name': match_dns_name,
    'arn': match_arn,
    'cidr_contains': match_cidr_contains,
    'cidr_is_default': match_cidr_is_default,
    'instance_or_ip': match_instance_or_ip,
}


def is_default_route(value):
    return match_cidr_is_default(value)


def derive_edges(assets, rules=None, resolve_path=None):
    """
    Apply the value-join rules across collected assets.

    Yields edge dicts in the same shape mechanism A produces, so downstream code
    does not care which mechanism found an edge - only how confident it is.
    """
    from providers.aws.runtime.resolver import resolve_path as default_resolve
    resolve_path = resolve_path or default_resolve
    rules = rules if rules is not None else load_rules()

    by_type = {}
    for asset in assets:
        by_type.setdefault(asset['resource_key'], []).append(asset)

    for rule in rules:
        sources = by_type.get(rule['source_key'], [])
        if not sources:
            continue
        matcher = MATCHERS.get(rule['match_kind'])
        if matcher is None:
            continue

        # A rule with no target_key describes the value itself rather than a
        # join - `cidr_is_default` marks a route as internet-bound, and
        # `aws_service_name` names a service that is not a collected resource.
        if not rule.get('target_key'):
            for asset in sources:
                for value in resolve_path(asset.get('raw') or {}, rule['source_path']):
                    kind, identifier = (matcher(value)
                                        if rule['match_kind'] == 'aws_service_name'
                                        else (matcher(value), value))
                    if not kind:
                        continue
                    yield {
                        'source_asset_id': asset['asset_id'],
                        'target_asset_id': f'aws-service:{identifier}'
                        if rule['match_kind'] == 'aws_service_name' else str(value),
                        'edge_type': rule['edge_type'],
                        'source': 'value-match', 'match_kind': rule['match_kind'],
                        'confidence': rule.get('confidence', 'medium'),
                        'external': rule['match_kind'] == 'aws_service_name'
                        and kind == 'customer',
                        'value': str(value),
                    }
            continue

        targets = by_type.get(rule['target_key'], [])
        if not targets:
            continue
        for asset in sources:
            for value in resolve_path(asset.get('raw') or {}, rule['source_path']):
                for target in targets:
                    target_value = (target.get('raw') or {}).get(rule['target_path'])
                    if target_value is None:
                        continue
                    hit = (match_s3_origin(value, target_value)
                           if rule['target_key'] == 's3.bucket'
                           and rule['match_kind'] == 'dns_name'
                           else matcher(value, target_value))
                    if hit:
                        yield {
                            'source_asset_id': asset['asset_id'],
                            'target_asset_id': target['asset_id'],
                            'edge_type': rule['edge_type'],
                            'source': 'value-match',
                            'match_kind': rule['match_kind'],
                            'confidence': rule.get('confidence', 'medium'),
                            'external': False,
                            'value': str(value),
                        }
