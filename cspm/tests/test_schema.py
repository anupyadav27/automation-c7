"""
The shared asset contract.

These tests guard the boundary between providers and engines. A record that
passes here must be readable by a cost rule, a compliance join and the UI
without any of them knowing which cloud it came from.
"""
import pytest

from cspm import schema, uid as uidlib


def a_record(**over):
    base = dict(provider='aws', account_id='588989875114', region='ap-southeast-1',
                resource_type='s3.bucket', resource_id='my-bucket',
                resource_uid='arn:aws:s3:::my-bucket', name='my-bucket')
    base.update(over)
    return schema.make(**base)


def test_a_well_formed_record_validates():
    assert schema.validate(a_record()) == []


def test_identity_hash_ignores_mutable_state():
    """Tagging a resource must not make it look like a different resource."""
    plain = a_record()
    tagged = a_record(tags={'env': 'prod'})
    assert plain['hash_sha256'] == tagged['hash_sha256']


def test_identity_hash_changes_when_identity_changes():
    assert a_record()['hash_sha256'] != a_record(resource_id='other')['hash_sha256']


def test_a_tampered_hash_is_caught():
    record = a_record()
    record['resource_id'] = 'something-else'
    assert any('hash' in p for p in schema.validate(record))


def test_missing_identity_is_rejected():
    record = a_record()
    record['resource_uid'] = ''
    assert any('resource_uid' in p for p in schema.validate(record))


def test_regional_asset_must_name_its_region():
    record = a_record(region='')
    assert any('region' in p for p in schema.validate(record))


def test_global_asset_needs_no_region():
    record = a_record(region='', scope='global',
                      resource_uid='arn:aws:iam::588989875114:role/app',
                      resource_type='iam.role', resource_id='app')
    assert schema.validate(record) == []


def test_provider_specific_keys_cannot_smuggle_into_topology():
    """The rule that keeps the contract multi-cloud: no `vpc_id` in a shared shape."""
    record = a_record()
    record['topology']['vpc_id'] = 'vpc-123'
    problems = schema.validate(record)
    assert any('provider-specific' in p for p in problems)


def test_unknown_provider_is_rejected():
    assert any('provider' in p for p in schema.validate(a_record(provider='ovh')))


def test_tags_must_be_a_mapping_not_aws_key_value_pairs():
    record = a_record()
    record['tags'] = [{'Key': 'env', 'Value': 'prod'}]
    assert any('tags' in p for p in schema.validate(record))


def test_v2_narrows_to_v1_for_the_finops_platform():
    """The FinOps Asset model pins schema_version to the v1 literal."""
    v1 = schema.to_v1(a_record())
    assert v1['schema_version'] == 'cspm_asset.v1'
    assert 'topology' not in v1
    assert v1['resource_uid'] == 'arn:aws:s3:::my-bucket'


def test_topology_never_leaks_into_metadata():
    """Cost rules match on metadata; seeding it with position changes results."""
    record = a_record()
    assert 'layer_id' not in record['metadata']
    assert 'container_uid' not in record['metadata']


# ── uid ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('provider,value', [
    ('aws', 'arn:aws:s3:::my-bucket'),
    ('aws', 'arn:aws:ec2:ap-southeast-1:588989875114:instance/i-0abc'),
    ('azure', '/subscriptions/abc-123/resourceGroups/rg1/providers/'
              'Microsoft.Compute/virtualMachines/vm1'),
    ('gcp', '//compute.googleapis.com/projects/p1/zones/us-central1-a/instances/i1'),
    ('oci', 'ocid1.instance.oc1.phx.aaaaaaaa'),
    ('kubernetes', 'prod-cluster/default/Deployment/api'),
])
def test_native_identifiers_are_accepted(provider, value):
    assert uidlib.looks_valid(provider, value)


@pytest.mark.parametrize('provider,value', [
    ('aws', 'my-bucket'),
    ('aws', 'arn:incomplete'),
    ('azure', 'resourceGroups/rg1'),
    ('gcp', 'projects/p1/instances/i1'),
])
def test_malformed_identifiers_are_rejected(provider, value):
    assert not uidlib.looks_valid(provider, value)


def test_account_is_read_from_the_identifier():
    """How cross-account sharing is spotted without a second API call."""
    assert uidlib.account_of('aws', 'arn:aws:iam::999988887777:role/x') == '999988887777'
    assert uidlib.account_of(
        'azure', '/subscriptions/sub-1/resourceGroups/rg/providers/x/y/z') == 'sub-1'
    assert uidlib.account_of(
        'gcp', '//compute.googleapis.com/projects/proj-9/zones/z/instances/i') == 'proj-9'


def test_a_malformed_uid_is_graded_none_however_it_was_obtained():
    """Grading a broken identifier `real` would hide that it joins to nothing."""
    assert uidlib.grade('aws', 'not-an-arn', 'field') == ('not-an-arn', 'none')


def test_grade_distinguishes_returned_from_assembled():
    assert uidlib.grade('aws', 'arn:aws:s3:::b', 'field')[1] == 'real'
    assert uidlib.grade('aws', 'arn:aws:s3:::b', 'construct')[1] == 'derived'


def test_kubernetes_uid_is_always_synthetic():
    value = uidlib.kubernetes_uid('prod', 'default', 'Deployment', 'api')
    assert uidlib.grade('kubernetes', value, 'synthetic')[1] == 'synthetic'
