"""
Layer tree tests — offline, no AWS.

The central property under test is the cascade: layers are projections over
their parent, so a change at one layer must be visible at every layer below
without anything being rebuilt.
"""

import pytest

from providers.aws.runtime.layers import (
    LayerTree, L_ACCOUNT, L_REGION, L_VPC, L_AZ, L_SUBNET, L_WORKLOAD,
    L_REGIONAL, L_GLOBAL,
)

ACCOUNT, REGION = '123456789012', 'ap-southeast-1'
AZ_A, AZ_B = 'ap-southeast-1a', 'ap-southeast-1b'


@pytest.fixture
def tree():
    """Two VPCs, two AZs, subnets in each, instances in the subnets."""
    t = LayerTree(ACCOUNT, REGION, location_paths={})
    t.add_resource('ec2.vpc', 'vpc-1')
    t.add_resource('ec2.vpc', 'vpc-2')
    t.add_resource('ec2.subnet', 'subnet-a', vpc='vpc-1', zone=AZ_A)
    t.add_resource('ec2.subnet', 'subnet-b', vpc='vpc-1', zone=AZ_B)
    t.add_resource('ec2.subnet', 'subnet-c', vpc='vpc-2', zone=AZ_A)
    t.add_resource('ec2.instance', 'i-1', subnet='subnet-a', vpc='vpc-1', zone=AZ_A)
    t.add_resource('ec2.instance', 'i-2', subnet='subnet-b', vpc='vpc-1', zone=AZ_B)
    t.add_resource('ec2.instance', 'i-3', subnet='subnet-c', vpc='vpc-2', zone=AZ_A)
    t.add_resource('s3.bucket', 'my-bucket')             # O6 regional overlay
    t.add_resource('iam.role', 'MyRole')                 # overlay
    t.add_resource('kms.key', 'key-1')                   # overlay
    return t.build()


# ── structure ─────────────────────────────────────────────────────────

def test_layer_assignment(tree):
    assert len(tree.layer(L_ACCOUNT)) == 1
    assert len(tree.layer(L_REGION)) == 1
    assert len(tree.layer(L_VPC)) == 2
    assert len(tree.layer(L_SUBNET)) == 3
    # s3 has no VPC presence, so it is an O6 overlay rather than a workload.
    assert {n.id for n in tree.layer(L_WORKLOAD)} == {'i-1', 'i-2', 'i-3'}


def test_az_nodes_are_scoped_per_vpc(tree):
    """Each VPC draws its own zone columns, so AZ nodes must not be shared."""
    az_keys = {n.key for n in tree.layer(L_AZ)}
    assert az_keys == {f'az:vpc-1/{AZ_A}', f'az:vpc-1/{AZ_B}', f'az:vpc-2/{AZ_A}'}


def test_containment_chain_reaches_the_account(tree):
    chain = [n.key for n in tree.ancestors('ec2.instance:i-1')]
    assert chain == ['ec2.subnet:subnet-a', f'az:vpc-1/{AZ_A}', 'vpc:vpc-1',
                     tree.region_key, tree.account_key]


def test_overlay_is_a_toggle_not_a_placement(tree):
    """
    Overlay-tagged nodes are still IN the tree.

    Treating "has an overlay group" as "is not in the tree" is what previously
    drew S3 outside the region box. The group exists so a renderer can hide
    identity or encryption, not because those nodes live nowhere.
    """
    overlays = tree.overlays()
    assert {n.id for n in overlays['identity']} == {'MyRole'}
    assert {n.id for n in overlays['encryption']} == {'key-1'}
    for bucket in overlays.values():
        for node in bucket:
            assert node.layer is not None, f'{node.key} was tagged but not placed'
            assert node.parent is not None


def test_regional_service_sits_in_the_region_beside_the_vpc(tree):
    """A bucket is in the region but in no VPC — beside the VPC, not outside it."""
    node = tree.nodes['s3.bucket:my-bucket']
    assert node.layer == L_REGIONAL
    assert node.parent == tree.region_key


def test_global_service_sits_outside_the_region(tree):
    """IAM has no region at all, so it hangs off the account."""
    node = tree.nodes['iam.role:MyRole']
    assert node.layer == L_GLOBAL
    assert node.parent == tree.account_key


def test_kms_is_regional_and_also_tagged_encryption(tree):
    """Placement and rendering group are independent facts about one node."""
    node = tree.nodes['kms.key:key-1']
    assert node.layer == L_REGIONAL
    assert node.overlay == 'encryption'


# ── the cascade ───────────────────────────────────────────────────────

def test_filtering_l2_cascades_to_every_layer_below(tree):
    """Filter at the VPC layer; subnets, AZs and instances must all follow."""
    assert len(tree.layer(L_SUBNET)) == 3
    assert len(tree.layer(L_WORKLOAD)) == 3

    tree.set_filter(L_VPC, {'vpc:vpc-1'})

    assert {n.id for n in tree.layer(L_VPC)} == {'vpc-1'}
    assert {n.id for n in tree.layer(L_SUBNET)} == {'subnet-a', 'subnet-b'}
    # i-3 lived in vpc-2 and disappears without being touched directly.
    assert {n.id for n in tree.layer(L_WORKLOAD)} == {'i-1', 'i-2'}


def test_filtering_az_cascades_across_vpcs(tree):
    tree.set_filter(L_AZ, {f'az:vpc-1/{AZ_A}'})
    assert {n.id for n in tree.layer(L_SUBNET)} == {'subnet-a'}
    assert {n.id for n in tree.layer(L_WORKLOAD)} == {'i-1'}


def test_clearing_a_filter_restores_lower_layers(tree):
    tree.set_filter(L_VPC, {'vpc:vpc-1'})
    assert len(tree.layer(L_WORKLOAD)) == 2
    tree.set_filter(L_VPC, None)
    assert len(tree.layer(L_WORKLOAD)) == 3


def test_filters_at_two_layers_intersect(tree):
    tree.set_filter(L_VPC, {'vpc:vpc-1'}).set_filter(L_AZ, {f'az:vpc-1/{AZ_B}'})
    assert {n.id for n in tree.layer(L_WORKLOAD)} == {'i-2'}


def test_subtree_is_the_cascade_made_explicit(tree):
    keys = {n.key for n in tree.subtree('vpc:vpc-1')}
    assert 'ec2.instance:i-1' in keys and 'ec2.instance:i-2' in keys
    assert 'ec2.instance:i-3' not in keys                      # belongs to vpc-2


def test_children_respect_filters(tree):
    assert len(tree.children('vpc:vpc-1')) == 2      # two AZ columns
    tree.set_filter(L_AZ, {f'az:vpc-1/{AZ_A}'})
    assert len(tree.children('vpc:vpc-1')) == 1


def test_to_dict_reflects_the_active_filter(tree):
    tree.set_filter(L_VPC, {'vpc:vpc-1'})
    out = tree.to_dict()
    assert out['counts']['vpc'] == 1
    assert out['counts']['subnet'] == 2
    assert out['tree']['key'] == tree.account_key
    # Identity is global, so a VPC filter does not remove it.
    assert out['overlays']['identity'][0]['id'] == 'MyRole'


def test_build_is_idempotent(tree):
    before = tree.to_dict()['counts']
    tree.build()
    assert tree.to_dict()['counts'] == before


# ── location resolution from raw payloads ─────────────────────────────

def test_zone_read_from_raw_via_location_paths():
    paths = {'ec2.instance': {'resource': 'ec2.instance', 'az_path': 'Placement.AvailabilityZone',
                     'az_kind': 'dotted'}}
    t = LayerTree(ACCOUNT, REGION, location_paths=paths)
    t.add_resource('ec2.vpc', 'vpc-1')
    t.add_resource('ec2.instance', 'i-9', vpc='vpc-1',
                   raw={'InstanceId': 'i-9', 'Placement': {'AvailabilityZone': AZ_A}})
    t.build()
    assert t.nodes['ec2.instance:i-9'].zone == AZ_A
    assert t.nodes['ec2.instance:i-9'].parent == f'az:vpc-1/{AZ_A}'


def test_depth_is_only_comparable_within_one_axis():
    """
    `R1` is 8 and `L6` is 6, but that 8 does not mean "deeper than a volume" —
    it means "not in the network at all". Compared across axes it said an API
    Gateway is deeper than its own stage, so three stages refused to nest in
    the API that owns them and sat on a rail belonging to nothing.
    """
    from providers.aws.runtime.layers import LayerTree

    tree = LayerTree('1', 'ap-south-1')
    api = tree.add_resource('apigatewayv2.api', 'api-1')
    stage = tree.add_resource('apigatewayv2.stage', 'prod',
                              attached_to=f'apigatewayv2.api:{api.id}')
    assert tree._would_nest(stage, api.key), \
        'a regional host must be able to hold its own component'


def test_a_cycle_is_still_refused_across_axes():
    """
    Dropping the cross-axis depth check must not drop the cycle check with it —
    that is the one that stops `to_dict()` recursing forever.
    """
    from providers.aws.runtime.layers import LayerTree

    tree = LayerTree('1', 'ap-south-1')
    a = tree.add_resource('apigatewayv2.api', 'api-1')
    b = tree.add_resource('apigatewayv2.stage', 'prod')
    b.parent = a.key
    a.parent = b.key
    assert not tree._would_nest(a, b.key), 'a loop must still be refused'


def test_two_children_named_the_same_stay_two_resources():
    """
    Stage names are unique within an API, not within an account: two APIs each
    have a `$default`. Keyed on the name alone they collapsed onto one node —
    two real resources drawn as one, with no error anywhere.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [
        {'asset_id': 'api-a', 'resource_key': 'apigatewayv2.api', 'id': 'aaa'},
        {'asset_id': 'api-b', 'resource_key': 'apigatewayv2.api', 'id': 'bbb'},
        {'asset_id': 'stage-a', 'resource_key': 'apigatewayv2.stage',
         'id': '$default', 'parent_asset_id': 'api-a'},
        {'asset_id': 'stage-b', 'resource_key': 'apigatewayv2.stage',
         'id': '$default', 'parent_asset_id': 'api-b'},
    ]
    scene = build_scene(assets, [], '1', 'ap-south-1')
    stages = [n for n in scene.tree.nodes.values()
              if n.type == 'apigatewayv2.stage']
    assert len(stages) == 2, f'two stages collapsed into {len(stages)}'
