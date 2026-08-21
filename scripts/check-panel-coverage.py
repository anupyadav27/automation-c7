#!/usr/bin/env python3
"""
Would any resource's panel be missing a section it should have?

    python3 scripts/check-panel-coverage.py          # report
    python3 scripts/check-panel-coverage.py --strict # non-zero exit on a miss

A panel has four data-driven sections and each is silent when it has nothing:
Configuration, Contained, Connections, Tags. Silence is usually correct — a
DynamoDB table encrypted with an AWS-owned key genuinely points at no KMS key,
and saying so is the honest answer. But silence is also what a MISSING RULE
looks like, and the two are indistinguishable by eye. That was the S3 bug: 55
buckets showed no connections for weeks because their only edges pointed at
themselves.

So this does not check that every type has every section — that would be a lie
about the estate. It checks the one thing that is always a defect:

    a payload value that names another COLLECTED resource,
    with no edge to show for it.

If the value resolves to something real and nothing connects them, either a
relation rule is missing or an existing one is broken. Both are ours to fix.
"""
import argparse
import collections
import csv
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ASSETS = os.path.join(ROOT, 'out', 'assets.json')
EDGES = os.path.join(ROOT, 'out', 'edges.csv')
CATALOG = os.path.join(ROOT, 'providers', 'aws', 'catalog')

# Fields that name something without relating to it. An AMI id on an instance
# says which image it booted, which is provenance rather than architecture, and
# the catalog deliberately draws those as records instead of edges.
IGNORE_FIELDS = ('ImageId', 'OwnerId', 'Owner', 'AccountId', 'RequestId',
                 'ClientToken', 'SnapshotId',
                 # A tag's `Value` is free text. It matches a cluster name
                 # because someone tagged the resource with it, which is a
                 # label, not a reference — 16 of the first findings were this.
                 'Value', 'Key',
                 # A region is not a resource, however much a GameLift
                 # location shares its name: 28 buckets "referenced"
                 # `gamelift.location` because both are called `ap-south-1`.
                 'LocationConstraint', 'AvailabilityZone', 'Region',
                 'IssuingAccount', 'RetiringPrincipal')

# An id shorter than this matches too much to be evidence of anything.
MIN_ID = 8

# Matches that are NAME COLLISIONS, not references. Each is a real value that
# resolves to a real resource, and the two still have nothing to do with each
# other — a Lambda called `c7n-automation-dev` matches an ECR repository of the
# same name because someone named both after the project, not because one
# points at the other.
#
# Declared rather than pattern-matched: a rule broad enough to catch these
# ("names are weaker evidence than ARNs") would also drop `cloudtrail.trail
# .S3BucketName -> s3.bucket`, which is a real reference to a bucket whose name
# is all AWS gives you. Every entry here is a judgement, so every entry says
# why.
COLLISIONS = {
    ("lambda.version", "FunctionName", "ecr.repository"):
        "the function and the image repository share a project name",
    ("lambda.version", "FunctionName", "events.rule"):
        "the function and the schedule that fires it share a name",
    ("iam.attached_role_policy", "PolicyName", "iam.role"):
        "a policy named after the role it is attached to",
    ("iam.account_authorization_detail", "UserName", "iam.group"):
        "a user and a group with the same name",
    ("iam.virtual_mfa_device", "Arn", "ec2.principal_id_format"):
        "both are keyed by the account root ARN; neither points at the other",
    # The authorization detail is a REPORT about policies, keyed by the same
    # AWS-managed ARNs the attached-policy records use. Two records of one
    # policy is an identity overlap, not a relationship between two resources.
    ("iam.account_authorization_detail", "PolicyArn", "iam.attached_role_policy"):
        "two records of the same managed policy, not two related resources",
    ("iam.account_authorization_detail", "PolicyArn", "iam.attached_user_policy"):
        "two records of the same managed policy, not two related resources",
    ("iam.account_authorization_detail", "PermissionsBoundaryArn",
     "iam.attached_role_policy"):
        "two records of the same managed policy, not two related resources",
}


def load():
    with open(ASSETS) as fh:
        assets = json.load(fh)
    assets = assets if isinstance(assets, list) else assets.get('assets', [])
    edges = []
    if os.path.exists(EDGES):
        with open(EDGES, newline='') as fh:
            edges = list(csv.DictReader(fh))
    return assets, edges


def scalars(payload, depth=0):
    """Every scalar in a payload, one level into nesting and lists."""
    for key, value in (payload or {}).items():
        if key in IGNORE_FIELDS:
            continue
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            yield key, str(value)
        elif depth == 0 and isinstance(value, dict):
            yield from scalars(value, depth + 1)
        elif depth == 0 and isinstance(value, list):
            for item in value[:20]:
                if isinstance(item, dict):
                    yield from scalars(item, depth + 1)
                elif isinstance(item, str):
                    yield key, item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', action='store_true',
                        help='exit non-zero when a reference has no edge')
    args = parser.parse_args(argv)

    if not os.path.exists(ASSETS):
        print(f'{ASSETS} not found — run the discover stage first', file=sys.stderr)
        return 1
    assets, edges = load()

    # Every identifier a collected resource answers to.
    owner = {}
    for asset in assets:
        for ident in (asset.get('arn'), asset.get('id'), asset.get('name')):
            if ident and len(str(ident)) >= MIN_ID:
                owner.setdefault(str(ident), asset)

    linked = collections.defaultdict(set)
    for edge in edges:
        linked[edge['source_asset_id']].add(edge['target_asset_id'])
        linked[edge['target_asset_id']].add(edge['source_asset_id'])

    misses = collections.Counter()
    examples = {}
    for asset in assets:
        mine = {asset.get('arn'), asset.get('id'), asset.get('name'), asset['asset_id']}
        for field, value in scalars(asset.get('raw') or {}):
            if value in mine:
                continue
            target = owner.get(value)
            if target is None or target['asset_id'] == asset['asset_id']:
                continue
            if target['asset_id'] in linked[asset['asset_id']]:
                continue
            # A bare region or account id is not a reference to anything, even
            # when some resource happens to be named after one.
            if re.fullmatch(r'\d{12}|[a-z]{2}-[a-z]+-\d', value):
                continue
            pair = (asset['resource_key'], field, target['resource_key'])
            if pair in COLLISIONS:
                continue
            misses[pair] += 1
            examples.setdefault(pair, (asset.get('name') or asset['id'], value))

    types = len({a['resource_key'] for a in assets})
    print(f'{len(assets)} resources across {types} types, {len(edges)} edges\n')
    if not misses:
        print(f'every value naming a collected resource has an edge '
              f'({len(COLLISIONS)} declared name collisions excluded).')
        return 0

    print(f'{len(misses)} reference shapes with no edge '
          f'({sum(misses.values())} occurrences):\n')
    print(f"  {'source type':30} {'field':26} {'names':24} n")
    for (src, field, tgt), n in misses.most_common(25):
        print(f'  {src:30} {field[:24]:26} {tgt:24} {n}')
    print('\nEach is a relation rule that is missing or broken. A value that '
          'resolves to\na real resource with nothing connecting them is not an '
          'empty account —\nit is the shape the S3 self-edge bug had.')
    return 1 if args.strict else 0


if __name__ == '__main__':
    sys.exit(main())
