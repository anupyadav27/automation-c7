"""
Identity, split from what identity is allowed to do.

Two questions an access review asks — who exists, and what are they permitted —
were one rail tab reading `identity 251`. These tests hold the split in place,
and hold the line on which of AWS's own identity objects count as ours.
"""

import pytest

from providers.aws.runtime.scene import prune_unused_aws_identity
from providers.common.topology.layout import (
    load_binding, load_model, resolve_slot, resolve_taxonomy,
)

BINDING_PATH = 'providers/aws/catalog/topology_binding.yaml'


@pytest.fixture(scope='module')
def binding():
    return load_binding(BINDING_PATH)


@pytest.fixture(scope='module')
def model():
    return load_model()


# ── the taxonomy split ────────────────────────────────────────────────

PRINCIPALS = ['iam.role', 'iam.user', 'iam.group', 'iam.instance_profile']
PERMISSIONS = [
    'iam.policy', 'iam.policy_version',
    'iam.attached_role_policy', 'iam.attached_user_policy',
    'iam.attached_group_policy',
    'iam.role_policy', 'iam.user_policy', 'iam.group_policy',
]


@pytest.mark.parametrize('type_', PRINCIPALS)
def test_a_principal_stays_on_the_identity_rail(type_, binding):
    assert resolve_taxonomy(type_, binding) == ('security', 'identity')


@pytest.mark.parametrize('type_', PERMISSIONS)
def test_a_permission_document_is_not_a_principal(type_, binding):
    # An inline policy is bound by TYPE for the same reason a managed one is:
    # the `iam` service supplies both halves, so the service default cannot
    # tell them apart and swept every policy in with the roles.
    assert resolve_taxonomy(type_, binding) == ('security', 'policy')


def test_the_model_knows_the_new_subcategory(model):
    security = model['taxonomy']['security']
    assert 'policy' in security
    # Order is meaning in this file: the two are read together, so they draw
    # together rather than with `policy` at the end beside posture.
    assert security.index('policy') == security.index('identity') + 1


def test_both_halves_ride_the_same_wall(model):
    # Who may act and what they may do belong on one arm; splitting them
    # across two walls would make an access review read left and right.
    assert (resolve_slot('security', 'policy', model)[1]
            == resolve_slot('security', 'identity', model)[1])


# ── whose identity it is ──────────────────────────────────────────────

def asset(id_, key, arn):
    return {'asset_id': id_, 'resource_key': key, 'arn': arn}


ACCT = 'arn:aws:iam::123456789012'


def test_keeps_everything_we_made():
    assets = [
        asset('1', 'iam.role', f'{ACCT}:role/my-app'),
        # Created through a console wizard, but in our account and ours to
        # answer for — the `/service-role/` path is not AWS ownership.
        asset('2', 'iam.role', f'{ACCT}:role/service-role/AWSGlueServiceRole'),
        asset('3', 'iam.policy', f'{ACCT}:policy/my-policy'),
    ]
    assert len(prune_unused_aws_identity(assets, [])) == 3


def test_drops_aws_identity_nothing_refers_to():
    assets = [
        asset('1', 'iam.policy', 'arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess'),
        asset('2', 'iam.role', f'{ACCT}:role/aws-reserved/sso.amazonaws.com/eu-west-1/AWSReservedSSO_Admin'),
        asset('3', 'iam.role', f'{ACCT}:role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS'),
    ]
    assert prune_unused_aws_identity(assets, []) == []


def test_keeps_aws_identity_this_estate_actually_uses():
    assets = [asset('3', 'iam.role',
                    f'{ACCT}:role/aws-service-role/ecs.amazonaws.com/AWSServiceRoleForECS')]
    edges = [{'source_asset_id': '3', 'target_asset_id': 'x', 'edge_type': 'assumes'}]

    assert len(prune_unused_aws_identity(assets, edges)) == 1


def test_an_attachment_record_is_itself_the_evidence_of_use():
    # `role X has AdministratorAccess attached` carries an AWS-managed ARN and
    # no edges. Read as an ordinary managed policy it would be pruned — which
    # would delete the only proof that the managed policies we DO rely on are
    # attached to anything.
    assets = [asset('1', 'iam.attached_role_policy',
                    'arn:aws:iam::aws:policy/AdministratorAccess')]

    assert len(prune_unused_aws_identity(assets, [])) == 1


def test_leaves_everything_that_is_not_identity_alone():
    assets = [
        asset('1', 'ec2.instance', 'arn:aws:ec2:ap-south-1:123456789012:instance/i-1'),
        asset('2', 's3.bucket', 'arn:aws:s3:::my-bucket'),
        {'asset_id': '3', 'resource_key': 'kms.key'},  # no arn at all
    ]
    assert len(prune_unused_aws_identity(assets, [])) == 3
