"""Offline tests for ARN construction and parsing — no AWS calls."""

import csv
import os

import pytest

from providers.aws.runtime import arn as arnlib

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog', 'arn_recipes.csv')
ACCOUNT = '123456789012'
REGION = 'ap-southeast-1'


@pytest.fixture(scope='module')
def recipes():
    return {r['resource']: r for r in csv.DictReader(open(CATALOG))}


# ── construction ──────────────────────────────────────────────────────

@pytest.mark.parametrize('resource,resource_json,expected', [
    ('ec2', {'InstanceId': 'i-0abc'},
     f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0abc'),
    ('ebs', {'VolumeId': 'vol-0abc'},
     f'arn:aws:ec2:{REGION}:{ACCOUNT}:volume/vol-0abc'),
    ('vpc', {'VpcId': 'vpc-999'},
     f'arn:aws:ec2:{REGION}:{ACCOUNT}:vpc/vpc-999'),
    ('security-group', {'GroupId': 'sg-111'},
     f'arn:aws:ec2:{REGION}:{ACCOUNT}:security-group/sg-111'),
    # S3 carries neither region nor account.
    ('s3', {'Name': 'my-bucket'}, 'arn:aws:s3:::my-bucket'),
])
def test_constructed(recipes, resource, resource_json, expected):
    assert arnlib.build(recipes[resource], resource_json, REGION, ACCOUNT) == expected


def test_global_resource_has_empty_region(recipes):
    # iam-role declares an arn_field, so force the construct path directly.
    got = arnlib.build_from_id(recipes['iam-role'], 'MyRole', REGION, ACCOUNT)
    assert got == f'arn:aws:iam::{ACCOUNT}:role/MyRole'
    assert ':iam::' in got, 'global resources must not carry a region'


def test_arn_field_is_read_not_constructed(recipes):
    real = 'arn:aws:lambda:ap-southeast-1:123456789012:function:my-func'
    assert arnlib.build(recipes['lambda'],
                        {'FunctionName': 'my-func', 'FunctionArn': real},
                        REGION, ACCOUNT) == real


def test_id_that_is_already_an_arn_passes_through(recipes):
    real = 'arn:aws:elasticloadbalancing:ap-southeast-1:1:loadbalancer/app/x/1'
    assert arnlib.build(recipes['app-elb'], {'LoadBalancerArn': real},
                        REGION, ACCOUNT) == real


def test_missing_arn_field_falls_back_to_construction(recipes):
    # Declared arn_field absent from the payload — must still yield an ARN.
    got = arnlib.build(recipes['kms-key'], {'KeyId': 'abc-123'}, REGION, ACCOUNT)
    assert got == f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abc-123'


def test_resource_without_arn_raises(recipes):
    none_types = [k for k, v in recipes.items() if v['has_arn'] == 'false']
    assert none_types, 'expected some types to declare no ARN'
    with pytest.raises(arnlib.NoArnForResource):
        arnlib.build(recipes[none_types[0]], {}, REGION, ACCOUNT)


def test_missing_id_returns_none(recipes):
    assert arnlib.build(recipes['ec2'], {'Foo': 'bar'}, REGION, ACCOUNT) is None


@pytest.mark.parametrize('region,partition', [
    ('ap-southeast-1', 'aws'),
    ('cn-north-1', 'aws-cn'),
    ('us-gov-west-1', 'aws-us-gov'),
    (None, 'aws'),
])
def test_partition_selection(region, partition):
    assert arnlib.partition_for(region) == partition


def test_every_recipe_builds_or_declines(recipes):
    """No recipe may crash: each either builds, declines, or returns None."""
    failures = []
    for name, r in recipes.items():
        payload = {r['id_field']: 'test-id'} if r['id_field'] else {}
        try:
            arnlib.build(r, payload, REGION, ACCOUNT)
        except arnlib.NoArnForResource:
            pass
        except Exception as exc:               # noqa: BLE001 - that's the point
            failures.append(f'{name}: {type(exc).__name__}: {exc}')
    assert not failures, failures


# ── parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,service,rtype,rid', [
    (f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0abc', 'ec2', 'instance', 'i-0abc'),
    ('arn:aws:lambda:ap-southeast-1:1:function:my-func', 'lambda', 'function', 'my-func'),
    ('arn:aws:s3:::my-bucket', 's3', '', 'my-bucket'),
    ('arn:aws:iam::1:role/MyRole', 'iam', 'role', 'MyRole'),
    # ALB ids embed slashes in the tail; only the first must split.
    ('arn:aws:elasticloadbalancing:r:1:loadbalancer/app/name/abc',
     'elasticloadbalancing', 'loadbalancer', 'app/name/abc'),
])
def test_parse(value, service, rtype, rid):
    got = arnlib.parse(value)
    assert got is not None
    assert (got.service, got.resource_type, got.resource_id) == (service, rtype, rid)


@pytest.mark.parametrize('value', ['i-0abc', 'vpc-123', '', None, 'arn:', 'not-an-arn'])
def test_parse_rejects_non_arns(value):
    assert arnlib.parse(value) is None


def test_round_trip_for_constructed_types(recipes):
    """Anything we build must parse back to the service and type we claimed."""
    mismatches = []
    for name, r in recipes.items():
        if r['strategy'] != 'construct' or not r['arn_type']:
            continue
        built = arnlib.build_from_id(r, 'test-id', REGION, ACCOUNT)
        parsed = arnlib.parse(built)
        if not parsed or parsed.service != r['service']:
            mismatches.append(f'{name}: {built}')
    assert not mismatches, mismatches


# ── validation ladder levels 2 and 3 ──────────────────────────────────

def test_matches_type(recipes):
    ec2_arn = f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0abc'
    assert arnlib.matches_type(ec2_arn, recipes['ec2']) is True
    assert arnlib.matches_type(ec2_arn, recipes['kms-key']) is False
    assert arnlib.matches_type('i-0abc', recipes['ec2']) is None   # not an ARN


def test_matches_prefix(recipes):
    assert arnlib.matches_prefix('vpc-0a1b', recipes['vpc']) is True
    assert arnlib.matches_prefix('sg-111', recipes['vpc']) is False
    assert arnlib.matches_prefix('anything', recipes['s3']) is None  # no prefix
