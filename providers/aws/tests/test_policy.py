"""Mechanism B (`policy-document`) tests — documents in, edges out. No AWS."""

import json
from urllib.parse import quote

import pytest

from providers.aws.runtime import policy

TRUST = {
    'Version': '2012-10-17',
    'Statement': [{
        'Effect': 'Allow',
        'Principal': {'Service': 'ec2.amazonaws.com'},
        'Action': 'sts:AssumeRole',
    }, {
        'Effect': 'Allow',
        'Principal': {'AWS': ['arn:aws:iam::123456789012:role/Deployer',
                              'arn:aws:iam::999999999999:root']},
        'Action': 'sts:AssumeRole',
    }],
}

IDENTITY = {
    'Version': '2012-10-17',
    'Statement': [{
        'Sid': 'ReadBuckets',
        'Effect': 'Allow',
        'Action': ['s3:GetObject', 's3:ListBucket'],
        'Resource': ['arn:aws:s3:::my-bucket', 'arn:aws:s3:::my-bucket/*'],
    }, {
        'Effect': 'Allow',
        'Action': 'kms:Decrypt',
        'Resource': 'arn:aws:kms:ap-southeast-1:123456789012:key/abc-123',
        'Condition': {'StringEquals': {
            'aws:SourceArn': 'arn:aws:lambda:ap-southeast-1:123456789012:function:f'}},
    }],
}

PUBLIC_RESOURCE = {
    'Statement': {                       # a bare dict, not a list
        'Effect': 'Allow',
        'Principal': '*',
        'Action': 's3:GetObject',
        'Resource': 'arn:aws:s3:::open-bucket/*',
    }
}


class FakeNode:
    def __init__(self, key, type_, id_):
        self.key, self.type, self.id = key, type_, id_


class FakeIndex:
    def __init__(self, mapping):
        self._m = mapping

    def lookup_any(self, value):
        return self._m.get(value)


# ── decoding ──────────────────────────────────────────────────────────

def test_decode_plain_json():
    assert policy.decode_document(json.dumps(TRUST)) == TRUST


def test_decode_url_encoded():
    assert policy.decode_document(quote(json.dumps(TRUST)), 'url') == TRUST


def test_decode_url_encoded_detected_without_being_told():
    encoded = quote(json.dumps(TRUST))
    assert policy.decode_document(encoded) == TRUST


def test_decode_passes_dicts_through():
    assert policy.decode_document(TRUST) == TRUST


@pytest.mark.parametrize('bad', [None, '', 'not json', '{"unclosed":', 42, []])
def test_decode_never_raises(bad):
    assert policy.decode_document(bad) is None


# ── shape normalisation ───────────────────────────────────────────────

def test_statement_may_be_a_bare_dict():
    assert len(list(policy.iter_statements(PUBLIC_RESOURCE))) == 1


@pytest.mark.parametrize('value,expected', [
    (None, []), ('a', ['a']), (['a', 'b'], ['a', 'b']),
])
def test_as_list(value, expected):
    assert policy.as_list(value) == expected


# ── principals ────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,kind', [
    ('*', 'wildcard'),
    ('123456789012', 'account'),
    ('ec2.amazonaws.com', 'service'),
    ('arn:aws:iam::123456789012:role/Deployer', 'arn'),
    # An account root ARN identifies an account, not a principal resource.
    ('arn:aws:iam::999999999999:root', 'account'),
])
def test_classify_principal(value, kind):
    assert policy.classify_principal(value)[0] == kind


def test_iter_principals_handles_service_and_aws_lists():
    kinds = dict(policy.iter_principals(TRUST['Statement'][0]))
    assert kinds == {'ec2.amazonaws.com': 'service'} or \
        ('service', 'ec2.amazonaws.com') in list(policy.iter_principals(TRUST['Statement'][0]))
    entries = list(policy.iter_principals(TRUST['Statement'][1]))
    assert ('arn', 'arn:aws:iam::123456789012:role/Deployer') in entries
    assert ('account', '999999999999') in entries


def test_not_principal_is_ignored():
    # NotPrincipal denies rather than grants; reading it as a grant inverts it.
    stmt = {'Effect': 'Allow', 'NotPrincipal': {'AWS': 'arn:aws:iam::1:role/X'}}
    assert list(policy.iter_principals(stmt)) == []


# ── patterns ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('value,pattern,prefix', [
    ('arn:aws:s3:::my-bucket', False, 'arn:aws:s3:::my-bucket'),
    ('arn:aws:s3:::my-bucket/*', True, 'arn:aws:s3:::my-bucket/'),
    ('*', True, ''),
])
def test_pattern_detection(value, pattern, prefix):
    assert policy.is_pattern(value) is pattern
    if pattern:
        assert policy.concrete_prefix(value) == prefix


# ── conditions ────────────────────────────────────────────────────────

def test_condition_arns_are_extracted():
    found = list(policy.iter_condition_arns(IDENTITY['Statement'][1]))
    assert found == [('aws:SourceArn',
                      'arn:aws:lambda:ap-southeast-1:123456789012:function:f')]


# ── edges ─────────────────────────────────────────────────────────────

def test_trust_policy_points_principal_at_the_role():
    edges = policy.derive_edges('iam.role', 'MyRole', TRUST, 'trust')
    assert all(e['target_id'] == 'MyRole' for e in edges)
    assert all(e['edge_type'] == 'assumes' for e in edges)
    kinds = {e['principal_kind'] for e in edges}
    assert kinds == {'service', 'arn', 'account'}


def test_identity_policy_points_holder_at_resources():
    edges = policy.derive_edges('iam.role', 'MyRole', IDENTITY, 'identity')
    access = [e for e in edges if e['edge_type'] == 'can-access']
    assert {e['target_id'] for e in access} == {
        'arn:aws:s3:::my-bucket', 'arn:aws:s3:::my-bucket/*',
        'arn:aws:kms:ap-southeast-1:123456789012:key/abc-123'}
    assert all(e['source_id'] == 'MyRole' for e in access)
    # The wildcard object grant is kept, flagged rather than dropped.
    assert any(e['is_pattern'] for e in access)


def test_identity_policy_emits_condition_edges():
    edges = policy.derive_edges('iam.role', 'MyRole', IDENTITY, 'identity')
    cond = [e for e in edges if e['edge_type'] == 'constrained-by']
    assert len(cond) == 1
    assert cond[0]['condition_key'] == 'aws:SourceArn'


def test_resource_policy_flags_public_access():
    edges = policy.derive_edges('s3.bucket', 'open-bucket', PUBLIC_RESOURCE, 'resource')
    assert len(edges) == 1
    assert edges[0]['edge_type'] == 'accessible-by'
    assert edges[0]['public'] is True


def test_wildcard_principal_with_a_restricting_condition_is_not_public():
    """
    AWS's own default SNS topic policy is `Principal: *` narrowed by
    `AWS:SourceOwner`. Reading it as public reports every account's default
    topics as world-readable — a false positive on the signal that matters most.
    """
    doc = {'Statement': [{
        'Sid': '__default_statement_ID', 'Effect': 'Allow', 'Principal': '*',
        'Action': ['SNS:GetTopicAttributes'], 'Resource': 'arn:aws:sns:r:1:t',
        'Condition': {'StringEquals': {'AWS:SourceOwner': '111111111111'}},
    }]}
    edges = policy.derive_edges('sns.topic', 't', doc, 'resource')
    assert edges
    assert all(e['public'] is False for e in edges)
    assert all(e['restricted_by_condition'] is True for e in edges)


def test_wildcard_with_an_unrelated_condition_is_still_public():
    """A condition on what may be done does not limit WHO may do it."""
    doc = {'Statement': [{
        'Effect': 'Allow', 'Principal': '*', 'Action': 's3:GetObject',
        'Resource': 'arn:aws:s3:::b/*',
        'Condition': {'StringLike': {'s3:prefix': 'public/*'}},
    }]}
    edges = policy.derive_edges('s3.bucket', 'b', doc, 'resource')
    assert edges and all(e['public'] is True for e in edges)


def test_deny_statements_are_not_marked_public():
    doc = {'Statement': [{'Effect': 'Deny', 'Principal': '*',
                          'Action': '*', 'Resource': '*'}]}
    edges = policy.derive_edges('s3.bucket', 'b', doc, 'resource')
    assert edges and all(e['public'] is False for e in edges)
    assert all(e['effect'] == 'Deny' for e in edges)


def test_edges_resolve_through_the_index():
    node = FakeNode('kms.key:abc-123', 'kms.key', 'abc-123')
    index = FakeIndex({'arn:aws:kms:ap-southeast-1:123456789012:key/abc-123': node})
    edges = policy.derive_edges('iam.role', 'MyRole', IDENTITY, 'identity', index)
    resolved = [e for e in edges if e['resolved']]
    assert len(resolved) == 1
    assert resolved[0]['target_key'] == 'kms.key:abc-123'


def test_unresolved_references_are_kept():
    edges = policy.derive_edges('iam.role', 'MyRole', IDENTITY, 'identity',
                                FakeIndex({}))
    assert edges and all(e['resolved'] is False for e in edges)


def test_actions_are_carried_on_the_edge():
    edges = policy.derive_edges('iam.role', 'MyRole', IDENTITY, 'identity')
    read = [e for e in edges if e['sid'] == 'ReadBuckets']
    assert read and read[0]['actions'] == ['s3:GetObject', 's3:ListBucket']


def test_malformed_document_yields_no_edges():
    assert policy.derive_edges('s3.bucket', 'b', 'garbage', 'resource') == []
