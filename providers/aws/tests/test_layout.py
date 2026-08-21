"""
Placement tests — the rules that make a diagram reproducible.

Split in two on purpose:

  * tests against the MODEL are provider-neutral and would hold for any cloud;
  * tests against the AWS BINDING check that this provider's types land on the
    right roles.

The determinism tests are the ones that matter most. Layout replaced three
different ordering rules - insertion order in the tree, member count in the UI,
insertion order again in the renderer - and the whole point was that the same
estate must render identically every time. A test that only checks "it produced
something" would have passed against all three of those bugs.
"""

import json

import pytest

from providers.common.topology.layout import (
    layout, load_binding, load_model, resolve_role, sort_key, taxonomy_ranks,
)

BINDING_PATH = 'providers/aws/catalog/topology_binding.yaml'


@pytest.fixture(scope='module')
def binding():
    return load_binding(BINDING_PATH)


@pytest.fixture(scope='module')
def model():
    return load_model()


# ── a minimal stand-in for the tree's Node ────────────────────────────

class Node:
    """Only the attributes layout() reads. Keeps the tests free of LayerTree."""

    __slots__ = ('key', 'type', 'id', 'name', 'raw', 'parent')

    def __init__(self, type_, id_, name=None, raw=None, parent=None):
        self.key = f'{type_}:{id_}'
        self.type = type_
        self.id = id_
        self.name = name or id_
        self.raw = raw or {}
        self.parent = parent


def build(node_list, edges=(), links=None):
    """(nodes, children) from a flat list, with explicit parent links."""
    nodes = {n.key: n for n in node_list}
    children = {}
    for parent, kids in (links or {}).items():
        children[parent] = list(kids)
    return nodes, children, list(edges)


def hosted(node, at='segment'):
    """
    Put a node inside a real network, and return the whole chain.

    A `flow.*` role is a claim that traffic reaches this thing at an address
    inside a segment, so it is only meaningful for a node that HAS a container.
    Testing one floating free would assert placement the engine is right to
    reject - a NAT gateway attached to nothing is not a NAT gateway in a subnet.
    """
    vpc = Node('vpc', 'vpc-1')
    zone = Node('az', 'vpc-1/az-a', parent=vpc.key)
    segment = Node('ec2.subnet', 'subnet-a', parent=zone.key)
    parent = {'segment': segment, 'zone': zone, 'network': vpc}[at]
    node.parent = parent.key
    return [vpc, zone, segment, node]


# ══════════════════════════════════════════════════════════════════════
# the model is provider-neutral — enforced, not just asserted in a docstring
# ══════════════════════════════════════════════════════════════════════

def test_model_names_no_provider_types(model):
    """
    No provider type slug may appear in the loaded model.

    This is the constraint that keeps one grammar serving every cloud. The
    moment `ec2.vpc` appears here, Azure needs a fork - so it is a test rather
    than a convention someone remembers.
    """
    blob = json.dumps(model).lower()
    for token in ('ec2.', 's3.', 'lambda.', 'iam.', 'arn:', 'aws:',
                  'microsoft.', 'compute.googleapis'):
        assert token not in blob, f'provider type {token!r} leaked into the model'


def test_every_binding_role_exists_in_the_model(binding, model):
    """A binding may only name roles the model defines — typos fail loudly."""
    known = set(model['roles']) | {c['role'] for c in model['categories']['lanes']}
    known |= {c['role'] for c in model['containers']}

    used = set((binding.get('overrides') or {}).values())
    used |= set((binding.get('services') or {}).values())
    for disc in (binding.get('discriminators') or {}).values():
        used |= set((disc.get('cases') or {}).values())
        if disc.get('default'):
            used.add(disc['default'])

    assert not (used - known), f'binding names unknown roles: {sorted(used - known)}'


def test_cluster_precedence_covers_every_binding_cluster(binding, model):
    """An unranked cluster kind would make ownership nondeterministic."""
    assert set(binding.get('clusters') or {}) <= set(model['cluster_precedence'])


# ══════════════════════════════════════════════════════════════════════
# determinism — the reason this module exists
# ══════════════════════════════════════════════════════════════════════

def _fixture_nodes():
    vpc = Node('vpc', 'vpc-1')
    zone_a = Node('az', 'vpc-1/az-a', parent=vpc.key)
    zone_b = Node('az', 'vpc-1/az-b', parent=vpc.key)
    sub_a = Node('ec2.subnet', 'subnet-a', parent=zone_a.key)
    sub_b = Node('ec2.subnet', 'subnet-b', parent=zone_b.key)
    return [
        vpc, zone_a, zone_b, sub_a, sub_b,
        Node('ec2.instance', 'i-002', parent=sub_a.key),
        Node('ec2.instance', 'i-001', parent=sub_a.key),
        Node('rds.db_instance', 'db-1', parent=sub_b.key),
        Node('sqs.queue', 'q-1'),
        Node('s3.bucket', 'bucket-1'),
        Node('ec2.internet_gateway', 'igw-1', parent=vpc.key),
    ]


def _links():
    return {
        'vpc:vpc-1': ['az:vpc-1/az-a', 'az:vpc-1/az-b', 'ec2.internet_gateway:igw-1'],
        'az:vpc-1/az-a': ['ec2.subnet:subnet-a'],
        'az:vpc-1/az-b': ['ec2.subnet:subnet-b'],
        'ec2.subnet:subnet-a': ['ec2.instance:i-002', 'ec2.instance:i-001'],
        'ec2.subnet:subnet-b': ['rds.db_instance:db-1'],
    }


def _signature(positions):
    """A comparable dump of every placement decision."""
    return sorted((k, p.role, p.band, p.lane, p.rank, p.anchor, p.order)
                  for k, p in positions.items())


def test_layout_is_stable_across_runs(binding):
    nodes, children, edges = build(_fixture_nodes(), links=_links())
    first = layout(nodes, children, edges, binding)
    second = layout(nodes, children, edges, binding)
    assert _signature(first) == _signature(second)


def test_layout_ignores_input_order(binding):
    """
    Shuffling the collector's output must not move a single box.

    This is the test that would have caught the original bug: children were
    appended in insertion order, so a diagram silently depended on the order
    the collector happened to return resources in.
    """
    ordered = _fixture_nodes()
    nodes_a, children_a, edges = build(ordered, links=_links())
    nodes_b, children_b, _ = build(list(reversed(ordered)), links=_links())

    assert _signature(layout(nodes_a, children_a, edges, binding)) == \
           _signature(layout(nodes_b, children_b, edges, binding))


def test_emitted_child_order_ignores_input_order():
    """
    The end-to-end version, through the real tree and its JSON payload.

    The signature comparison above sorts by key, which would hide an ordering
    bug rather than catch it - the emitted `children` LIST is the thing that was
    actually wrong, so this test compares that. Two collectors returning the
    same estate in different orders must produce identical JSON.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [
        {'asset_id': 'a-vpc', 'resource_key': 'ec2.vpc', 'id': 'vpc-1'},
        {'asset_id': 'a-sub', 'resource_key': 'ec2.subnet', 'id': 'subnet-a',
         'availability_zone': 'ap-southeast-1a'},
        {'asset_id': 'a-i2', 'resource_key': 'ec2.instance', 'id': 'i-002'},
        {'asset_id': 'a-i1', 'resource_key': 'ec2.instance', 'id': 'i-001'},
        {'asset_id': 'a-q', 'resource_key': 'sqs.queue', 'id': 'q-1'},
        {'asset_id': 'a-b', 'resource_key': 's3.bucket', 'id': 'bucket-1'},
    ]
    edges = [
        {'source_asset_id': 'a-sub', 'target_asset_id': 'a-vpc',
         'edge_type': 'contained-in'},
        {'source_asset_id': 'a-i1', 'target_asset_id': 'a-sub',
         'edge_type': 'contained-in'},
        {'source_asset_id': 'a-i2', 'target_asset_id': 'a-sub',
         'edge_type': 'contained-in'},
    ]

    forward = build_scene(list(assets), edges, '111', 'ap-southeast-1').to_dict()
    reverse = build_scene(list(reversed(assets)), edges, '111',
                          'ap-southeast-1').to_dict()
    assert json.dumps(forward['tree'], sort_keys=True) == \
           json.dumps(reverse['tree'], sort_keys=True)


def test_layout_is_independent_of_the_hash_seed():
    """
    Two processes with different hash seeds must emit identical placement.

    Python randomises string hashing per process, so iterating a set and sorting
    it with a key that can TIE silently makes layout depend on the seed - the
    same estate renders differently between runs, and a normal test suite only
    catches it on the unlucky seed. Grouping bands by minimum rank had exactly
    that bug. Running it out-of-process is the only way to test it honestly.
    """
    import subprocess
    import sys

    script = '''
import json, sys
sys.path.insert(0, ".")
from providers.aws.runtime.scene import build_scene
assets = [
    {"asset_id": "a-vpc", "resource_key": "ec2.vpc", "id": "vpc-1"},
    {"asset_id": "a-sub", "resource_key": "ec2.subnet", "id": "subnet-a",
     "availability_zone": "ap-southeast-1a"},
    {"asset_id": "a-i1", "resource_key": "ec2.instance", "id": "i-001"},
    {"asset_id": "a-nat", "resource_key": "ec2.nat_gateway", "id": "nat-1"},
    {"asset_id": "a-igw", "resource_key": "ec2.internet_gateway", "id": "igw-1"},
    {"asset_id": "a-q", "resource_key": "sqs.queue", "id": "q-1"},
    {"asset_id": "a-b", "resource_key": "s3.bucket", "id": "bucket-1"},
    {"asset_id": "a-k", "resource_key": "kms.key", "id": "key-1"},
]
edges = [
    {"source_asset_id": "a-sub", "target_asset_id": "a-vpc", "edge_type": "contained-in"},
    {"source_asset_id": "a-i1", "target_asset_id": "a-sub", "edge_type": "contained-in"},
    {"source_asset_id": "a-nat", "target_asset_id": "a-sub", "edge_type": "contained-in"},
]
doc = build_scene(assets, edges, "111", "ap-southeast-1").to_dict()
print(json.dumps(doc["tree"], sort_keys=True))
'''
    runs = []
    for seed in ('0', '4', '17'):
        result = subprocess.run([sys.executable, '-c', script],
                                capture_output=True, text=True,
                                env={'PYTHONHASHSEED': seed, 'PATH': ''})
        assert result.returncode == 0, result.stderr
        runs.append(result.stdout)
    assert len(set(runs)) == 1, 'placement changed with the hash seed'


def test_orphaned_structural_twins_are_not_placed_twice():
    """
    A VPC is registered twice and must be placed once.

    The tree registers a structural resource under its collected key
    (`ec2.vpc:vpc-1`) and again under the synthetic container key it mints for
    it (`vpc:vpc-1`), leaving the collected one orphaned - in `nodes`, in no
    child list, never drawn. Handing both to layout placed three VPCs as six and
    numbered their connectivity groups from 3.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [{'asset_id': f'a-{i}', 'resource_key': 'ec2.vpc', 'id': f'vpc-{i}'}
              for i in range(3)]
    scene = build_scene(assets, [], '111', 'ap-southeast-1')
    positions = scene.positions()

    networks = [p for p in positions.values() if p.role == 'network']
    assert len(networks) == 3, 'each VPC must be placed exactly once'
    assert sorted(p.lane for p in networks) == ['group-0', 'group-1', 'group-2']


def test_attachment_to_a_collected_container_still_renders():
    """
    An internet gateway attaches to the COLLECTED vpc key, not the synthetic one.

    The tree registers a VPC twice - `ec2.vpc:X` from the collector and `vpc:X`
    minted to hold its contents - and hangs children off the synthetic one. An
    `attached-to` edge naming the collected key therefore parented the gateway
    to a node that is in `nodes`, reports visible, and appears in no child list.
    The gateway silently disappeared from the diagram while every count still
    said it was there. It must resolve through the alias and render.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [
        {'asset_id': 'a-vpc', 'resource_key': 'ec2.vpc', 'id': 'vpc-1'},
        {'asset_id': 'a-igw', 'resource_key': 'ec2.internet_gateway', 'id': 'igw-1',
         'raw': {'Attachments': [{'State': 'available', 'VpcId': 'vpc-1'}]}},
    ]
    edges = [{'source_asset_id': 'a-igw', 'target_asset_id': 'a-vpc',
              'edge_type': 'attached-to'}]

    doc = build_scene(assets, edges, '111', 'ap-southeast-1').to_dict()

    seen, stack = {}, [doc['tree']]
    while stack:
        node = stack.pop()
        for child in node.get('children', []):
            seen[child['key']] = node['key']
            stack.append(child)

    key = 'ec2.internet_gateway:igw-1'
    assert key in seen, 'the gateway was collected but never drawn'
    assert seen[key] == 'vpc:vpc-1', 'must hang off the container, not the twin'


def test_mutual_attachment_does_not_hang_the_renderer():
    """
    AWS reports attachment from BOTH ends, and taking both literally loops.

    A volume is attached-to its instance and the instance carries the volume.
    Believing both makes each the other's parent; the scene builds fine and
    `to_dict()` then recurses between them until the process is killed. This
    was not hypothetical - it hung a real region for seven minutes.

    The first of the pair placed wins and the second falls back to its own
    spatial home. Placement is sorted by key, so which one wins is stable.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [
        {'asset_id': 'a-i', 'resource_key': 'ec2.instance', 'id': 'i-1'},
        {'asset_id': 'a-v', 'resource_key': 'ec2.volume', 'id': 'vol-1'},
    ]
    edges = [
        {'source_asset_id': 'a-v', 'target_asset_id': 'a-i', 'edge_type': 'attached-to'},
        {'source_asset_id': 'a-i', 'target_asset_id': 'a-v', 'edge_type': 'attached-to'},
    ]

    doc = build_scene(assets, edges, '111', 'ap-south-1').to_dict()

    count, stack = 0, [doc['tree']]
    while stack:
        node = stack.pop()
        count += 1
        assert count < 500, 'the walk is looping'
        stack.extend(node.get('children', []))

    parent, stack = {}, [doc['tree']]
    while stack:
        node = stack.pop()
        for child in node.get('children', []):
            parent[child['key']] = node['key']
            stack.append(child)

    assert len(parent) == len(set(parent)), 'a node was emitted more than once'
    # Direction is decided by DEPTH, not by sort order. A volume's natural
    # layer is deeper than an instance's, so the volume goes inside - breaking
    # the tie on the key instead put instances inside their own root volume.
    assert parent.get('ec2.volume:vol-1') == 'ec2.instance:i-1'
    assert parent.get('ec2.instance:i-1') != 'ec2.volume:vol-1'


def test_sort_key_is_total(binding):
    """No two nodes may tie, or ordering falls back to dict iteration."""
    nodes, children, edges = build(_fixture_nodes(), links=_links())
    positions = layout(nodes, children, edges, binding)
    keys = [sort_key(nodes[k], positions[k]) for k in nodes]
    assert len(set(keys)) == len(keys)


# ══════════════════════════════════════════════════════════════════════
# boundary objects sit on the boundary (C2)
# ══════════════════════════════════════════════════════════════════════

def test_internet_gateway_straddles_the_network_border(binding):
    nodes, children, edges = build(_fixture_nodes(), links=_links())
    positions = layout(nodes, children, edges, binding)
    igw = positions['ec2.internet_gateway:igw-1']
    assert igw.role == 'door.internet'
    assert igw.anchor == 'edge.n'
    # A border anchor takes the node out of band flow entirely.
    assert igw.band is None


@pytest.mark.parametrize('endpoint_type, at, expected_role, expected_anchor', [
    ('Gateway', 'network', 'door.service', 'edge.n'),
    ('Interface', 'segment', 'resident.ingress', 'in'),
])
def test_endpoint_placement_follows_its_own_data(
        binding, endpoint_type, at, expected_role, expected_anchor):
    """
    Same type, two places, decided by the payload.

    A gateway endpoint is a route-table entry with no address inside the
    network, so it is a border — the north one, alongside every other way out.
    An interface endpoint has an address, so it is a resident of a segment. A
    lookup table cannot express that difference.
    """
    node = Node('ec2.vpc_endpoint', 'vpce-1', raw={'VpcEndpointType': endpoint_type})
    nodes, children, edges = build(hosted(node, at))
    pos = layout(nodes, children, edges, binding)[node.key]
    assert pos.role == expected_role
    assert pos.anchor == expected_anchor


@pytest.mark.parametrize('raw, expected', [
    ({'VpcConfig': {'SubnetIds': ['subnet-a']}}, 'resident.compute'),
    ({'VpcConfig': {'SubnetIds': []}}, 'resident.serverless'),
    ({}, 'resident.serverless'),
])
def test_function_placement_follows_its_own_network_config(binding, raw, expected):
    """Two functions of one type legitimately land in different boxes."""
    assert resolve_role('lambda.function', raw, binding) == expected


# ══════════════════════════════════════════════════════════════════════
# cross-cutting things leave the flow (C1)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('type_, slot, anchor', [
    # the west wall — how it is run, watched and owned. Governance and
    # monitoring moved off the south line, which now carries traffic only.
    ('cloudtrail.trail', 'w-middle', 'rail.w'),
    ('config.config_rule', 'w-middle', 'rail.w'),
    ('guardduty.detector', 'w-middle', 'rail.w'),
    ('securityhub.hub', 'w-middle', 'rail.w'),
    # the south line, east end — both decide a packet's fate
    ('ec2.security_group', 'se', 'rail.s'),
    ('ec2.network_acl', 'se', 'rail.s'),
    ('ec2.route_table', 'se', 'rail.s'),
    # the south line, middle — out of the box. `ec2.vpc_endpoint` is NOT here:
    # it is a door, drawn on the boundary itself rather than on a rail beside it.
    # the east wall — who may act, what is sealed. Nothing else lives there.
    ('iam.role', 'e-upper', 'rail.e'),
    ('kms.key', 'e-upper', 'rail.e'),
    ('secretsmanager.secret', 'e-upper', 'rail.e'),
    ('acm.certificate', 'e-upper', 'rail.e'),
    # the NE corner — names resolve before anything moves
    ('route53resolver.resolver_rule', 'ne', 'rail.e'),
    # the west wall — how it is built, run and owned
    ('codedeploy.application', 'w-upper', 'rail.w'),
    ('autoscaling.auto_scaling_group', 'w-middle', 'rail.w'),
    ('organizations.account', 'w-bottom', 'rail.w'),
])
def test_cross_cutting_services_render_on_a_rail(binding, type_, slot, anchor):
    """
    A supporting service draws on a border, and WHICH border comes from its
    domain.

    It used to come from its role, and role is assigned per service — so the
    same domain landed on two arms depending on which service happened to carry
    it. `network.firewall` was north as WAF Regional and west as WAF;
    `devtools.deploy` was north as CodePipeline and east as CodeDeploy. Five of
    twelve categories were in two places at once.
    """
    node = Node(type_, 'x-1')
    nodes, children, edges = build([node])
    pos = layout(nodes, children, edges, binding)[node.key]
    assert pos.anchor == anchor, f'{type_} should be a rail, not a band'
    assert pos.slot == slot
    assert pos.band is None


def test_a_domain_can_only_be_in_one_place(binding):
    """
    The property the slot map exists for: no domain may resolve to two arms.

    Checked over the whole taxonomy rather than a sample, because the failure
    mode is a domain nobody thought about inheriting a second home from a
    service-level default.
    """
    import collections

    import yaml

    from providers.common.topology.layout import resolve_slot

    with open('providers/common/topology/model.yaml') as fh:
        model = yaml.safe_load(fh)

    arms = collections.defaultdict(set)
    for category, subs in (model.get('taxonomy') or {}).items():
        for sub in subs:
            found = resolve_slot(category, sub, model)
            assert found, f'{category}.{sub} resolves to no slot at all'
            arms[f'{category}.{sub}'].add(found[1])
    split = {d: a for d, a in arms.items() if len(a) > 1}
    assert not split, f'domains on more than one arm: {split}'


def test_every_slot_the_map_names_is_a_slot_that_exists(binding):
    """
    A domain pointed at a slot the model never declared would silently fall
    through to the default and draw somewhere nobody chose.
    """
    import yaml

    with open('providers/common/topology/model.yaml') as fh:
        cfg = (yaml.safe_load(fh).get('rail_slots') or {})

    declared = set(cfg.get('slots') or {})
    for domain, slot in (cfg.get('of') or {}).items():
        assert slot in declared, f'{domain} points at undeclared slot {slot!r}'
    assert cfg.get('default') in declared, 'the default slot is not declared'


# ══════════════════════════════════════════════════════════════════════
# presence collapsing (§5)
# ══════════════════════════════════════════════════════════════════════

def test_absent_bands_leave_no_gap(binding):
    """
    Rank is a relative order, not a coordinate.

    A subnet holding only data draws that data at position 0 - it does not
    reserve an empty slot where compute would have been.
    """
    sub = Node('ec2.subnet', 'subnet-x')
    db = Node('rds.db_instance', 'db-1', parent=sub.key)
    nodes, children, edges = build(
        [sub, db], links={'ec2.subnet:subnet-x': [db.key]})
    positions = layout(nodes, children, edges, binding)
    assert positions[db.key].order == 0


def test_estate_with_no_network_has_no_zone_lanes(binding):
    """No VPC means the zone axis disappears, not that it renders empty."""
    nodes, children, edges = build([Node('s3.bucket', 'b-1'),
                                    Node('sqs.queue', 'q-1')])
    positions = layout(nodes, children, edges, binding)
    assert all(p.role not in ('zone', 'network', 'segment')
               for p in positions.values())


# ══════════════════════════════════════════════════════════════════════
# derived facts — never read off a name or a tag
# ══════════════════════════════════════════════════════════════════════

def test_segment_tier_comes_from_routes_not_from_the_name(binding):
    """
    A segment NAMED private that routes to the internet is public.

    The contradiction is a finding, not a labelling preference, so the diagram
    has to report what the routes say.
    """
    sub = Node('ec2.subnet', 'subnet-a', name='private-subnet')
    nodes, children, edges = build(
        [sub], edges=[{'source_key': sub.key, 'target_key': 'ec2.internet_gateway:igw-1',
                       'edge_type': 'routes-to-internet'}])
    positions = layout(nodes, children, edges, binding)
    assert positions[sub.key].tier == 'public'
    assert positions[sub.key].derived is True


def test_segment_with_no_route_data_is_flagged_not_guessed(binding):
    """An absence is reported as an absence, not dressed up as a derivation."""
    sub = Node('ec2.subnet', 'subnet-a')
    nodes, children, edges = build([sub])
    pos = layout(nodes, children, edges, binding)[sub.key]
    assert pos.tier == 'unknown'
    assert pos.derived is False
    assert pos.to_dict()['assumed'] is True


def test_zones_order_by_stable_id_not_display_name(binding):
    """
    Providers shuffle the user-facing zone letter per account, so ordering by
    name makes two accounts disagree about the same physical zone.
    """
    early = Node('az', 'vpc-1/zone-c', raw={'ZoneId': 'apse1-az1'})
    late = Node('az', 'vpc-1/zone-a', raw={'ZoneId': 'apse1-az2'})
    nodes, children, edges = build([early, late])
    positions = layout(nodes, children, edges, binding)
    assert positions[early.key].rank < positions[late.key].rank


# ══════════════════════════════════════════════════════════════════════
# entry point resolution (§5 applied to the top of the diagram)
# ══════════════════════════════════════════════════════════════════════

def test_entry_point_prefers_the_edge_and_falls_through_when_absent(binding):
    with_cdn = [Node('cloudfront.distribution', 'd-1'),
                Node('elbv2.load_balancer', 'lb-1', raw={'Scheme': 'internet-facing'})]
    nodes, children, edges = build(with_cdn)
    positions = layout(nodes, children, edges, binding)
    assert positions['cloudfront.distribution:d-1'].entry is True
    # The balancer is still drawn - it is present, just not the front door.
    assert positions['elbv2.load_balancer:lb-1'].entry is False

    nodes, children, edges = build(with_cdn[1:])
    positions = layout(nodes, children, edges, binding)
    assert positions['elbv2.load_balancer:lb-1'].entry is True


def test_internal_balancer_is_never_the_entry_point(binding):
    node = Node('elbv2.load_balancer', 'lb-1', raw={'Scheme': 'internal'})
    nodes, children, edges = build([node])
    positions = layout(nodes, children, edges, binding)
    assert positions[node.key].entry is False


# ══════════════════════════════════════════════════════════════════════
# spanning — a balancer is not a resident of one segment
# ══════════════════════════════════════════════════════════════════════

def test_balancer_spans_only_the_zones_it_occupies(binding):
    """Spans exactly the zones it is enabled in — never one it has no ENI in."""
    lb = Node('elbv2.load_balancer', 'lb-1', raw={
        'Scheme': 'internet-facing',
        'AvailabilityZones': [{'ZoneName': 'az-a'}, {'ZoneName': 'az-b'}],
    })
    nodes, children, edges = build([lb])
    pos = layout(nodes, children, edges, binding)[lb.key]
    assert pos.span == ['az-a', 'az-b']


def test_nat_gateway_is_zonal_and_does_not_span(binding):
    """The asymmetry with a balancer is real: NAT lives in exactly one segment."""
    nat = Node('ec2.nat_gateway', 'nat-1')
    nodes, children, edges = build(hosted(nat))
    pos = layout(nodes, children, edges, binding)[nat.key]
    assert pos.role == 'door.egress'
    assert pos.span == []


@pytest.mark.parametrize('type_, raw, demoted_to', [


    ('ec2.nat_gateway', {}, 'resident.integration'),
])
def test_flow_roles_are_demoted_when_there_is_no_network(
        binding, type_, raw, demoted_to):
    """
    A flow role outside a network is a claim about a traffic path that does not
    exist there.

    These used to demote to a category lane, which was better than pretending
    they were databases but still wrong: a parameter group is not a datastore,
    it is configuration FOR one. They are artifacts now, and the suffix rule
    catches them before the service default ever applies - so the demotion path
    below is exercised by things that really are residents outside a network.
    """
    node = Node(type_, 'x-1', raw=raw)
    nodes, children, edges = build([node])
    assert layout(nodes, children, edges, binding)[node.key].role == demoted_to


# ══════════════════════════════════════════════════════════════════════
# networks: lateral when connected, stacked when not (A2)
# ══════════════════════════════════════════════════════════════════════

def test_peered_networks_share_a_lane_and_unrelated_ones_do_not(binding):
    a, b, c = (Node('vpc', 'vpc-a'), Node('vpc', 'vpc-b'), Node('vpc', 'vpc-c'))
    peering = [{'source_key': a.key, 'target_key': b.key, 'edge_type': 'peers-with'}]

    positions = layout({n.key: n for n in (a, b, c)}, {}, peering, binding)
    assert positions[a.key].lane == positions[b.key].lane
    assert positions[c.key].lane != positions[a.key].lane

    # Drop the peering and all three stack in groups of their own.
    positions = layout({n.key: n for n in (a, b, c)}, {}, [], binding)
    assert len({positions[n.key].lane for n in (a, b, c)}) == 3


# ══════════════════════════════════════════════════════════════════════
# fail loud
# ══════════════════════════════════════════════════════════════════════

def test_unknown_type_is_visible_not_silently_bucketed(binding):
    """
    Silence is how thousands of types accumulated in one undifferentiated blob.
    An unbound type gets a named, visible band instead.
    """
    node = Node('madeupservice.widget', 'w-1')
    nodes, children, edges = build([node])
    pos = layout(nodes, children, edges, binding)[node.key]
    assert pos.band == 'unplaced'
    assert pos.to_dict()['assumed'] is True


def test_binding_covers_the_services_in_the_live_scene(binding):
    """
    Every service in the committed scene fixture resolves to a role.

    Guards the long tail: a collector that starts returning a new service should
    show up here as a failing test, not as a silent blob in the diagram.
    """
    with open('out/scene.json') as fh:
        doc = json.load(fh)

    seen, stack = set(), [doc['tree']]
    while stack:
        node = stack.pop()
        seen.add(node['type'])
        stack.extend(node.get('children', []))

    spine = {t for spec in (binding['spine'] or {}).values()
             for t in (spec or {}).get('types') or []}
    unbound = sorted(t for t in seen
                     if t not in spine and resolve_role(t, {}, binding) is None)
    assert not unbound, f'no binding for: {unbound}'


def test_a_zone_is_only_a_container_when_it_holds_network():
    """
    A resource with a zone but no network must not mint an AZ box.

    A snapshot and an autoscaling group both carry an availability zone, but
    neither is a resident of one - the ASG spans zones, and the snapshot is a
    backup rather than something running. Minting a box for them produced a
    second `ap-south-1b` beside the VPC that already had one: same physical
    zone drawn twice, with 12 database snapshots inside it looking like
    infrastructure.
    """
    from providers.aws.runtime.scene import build_scene

    assets = [
        {'asset_id': 'a-vpc', 'resource_key': 'ec2.vpc', 'id': 'vpc-1'},
        {'asset_id': 'a-sub', 'resource_key': 'ec2.subnet', 'id': 'subnet-a',
         'availability_zone': 'ap-south-1b'},
        # Same zone as the subnet, but in no network at all.
        {'asset_id': 'a-snap', 'resource_key': 'rds.rds_snapshot', 'id': 'snap-1',
         'availability_zone': 'ap-south-1b'},
        {'asset_id': 'a-asg', 'resource_key': 'autoscaling.auto_scaling_group',
         'id': 'asg-1', 'availability_zone': 'ap-south-1b'},
    ]
    edges = [{'source_asset_id': 'a-sub', 'target_asset_id': 'a-vpc',
              'edge_type': 'contained-in'}]

    doc = build_scene(assets, edges, '111', 'ap-south-1').to_dict()
    zones, parent_of = [], {}
    stack = [doc['tree']]
    while stack:
        node = stack.pop()
        for child in node.get('children', []):
            parent_of[child['key']] = node
            stack.append(child)
        if node['type'] == 'az':
            zones.append(node)

    # Exactly one zone box, and it is inside the network.
    assert len(zones) == 1, [z['key'] for z in zones]
    assert parent_of[zones[0]['key']]['type'] in ('vpc', 'ec2.vpc')
    # The zone-carrying strays sit in the region, not in a minted zone.
    for key in ('rds.rds_snapshot:snap-1', 'autoscaling.auto_scaling_group:asg-1'):
        assert parent_of[key]['type'] == 'region'


# ══════════════════════════════════════════════════════════════════════
# doors and bindings — what a thing IS decides how it is placed
# ══════════════════════════════════════════════════════════════════════

def test_every_role_declares_a_kind(model):
    """
    The class decides HOW a thing is placed; the role decides WHERE. A role
    without one falls back to being drawn inline, which for a gateway or a
    policy is exactly the mistake this vocabulary exists to prevent.
    """
    known = set(model['kinds'])
    missing = [r for r, spec in model['roles'].items()
               if (spec or {}).get('kind') not in known]
    assert not missing, f'roles with no kind: {missing}'


@pytest.mark.parametrize('type_, raw', [
    ('ec2.internet_gateway', {}),
    ('ec2.nat_gateway', {}),
    ('ec2.vpc_endpoint', {'VpcEndpointType': 'Gateway'}),
    ('ec2.vpn_gateway', {}),
    ('ec2.vpc_peering_connection', {}),
    ('ec2.transit_gateway', {}),
])
def test_every_door_is_on_the_same_border(binding, type_, raw):
    """
    A door is where this box meets what is outside it, and that is one place.

    They used to be spread over three borders — north for the internet, south
    for private egress, east for lateral — on the reasoning that the SIDE said
    where the door led. It reads well in the abstract and badly on a canvas: an
    internet gateway, a NAT, a transit gateway and Direct Connect all answer the
    same question, and answering it in three places is why none of them read as
    a set.

    Where a door leads has not stopped mattering; it is carried by `edge_rank`
    along the border instead, which is the axis with room for it.
    """
    node = Node(type_, 'x-1', raw=raw)
    nodes, children, edges = build(hosted(node, 'network'))
    pos = layout(nodes, children, edges, binding)[node.key]
    assert pos.anchor == 'edge.n'
    assert pos.kind == 'door'


def test_south_border_ranks_by_how_public_the_destination_is(binding):
    """
    NAT reaches the open internet, an endpoint reaches AWS privately, a VPN
    reaches your own datacentre. Lower rank is more central, so the most public
    way out takes the middle of the border.
    """
    nat = Node('ec2.nat_gateway', 'nat-1')
    endpoint = Node('ec2.vpc_endpoint', 'vpce-1', raw={'VpcEndpointType': 'Gateway'})
    vpn = Node('ec2.vpn_gateway', 'vgw-1')
    nodes, children, edges = build(
        [*hosted(nat, 'network'), endpoint, vpn])
    positions = layout(nodes, children, edges, binding)
    ranks = {n.id: positions[n.key].edge_rank for n in (nat, endpoint, vpn)}
    assert ranks['nat-1'] < ranks['vpce-1'] < ranks['vgw-1'], ranks


def test_a_binding_is_hoisted_to_the_container_it_is_scoped_to(binding):
    """
    The bug this fixes: a VPC-scoped ACL had a containment edge to ONE subnet
    while governing four, so it drew inside that subnet. Scope is a fact about
    the resource; which containment edge got collected is an accident.
    """
    acl = Node('ec2.network_acl', 'acl-1')
    chain = hosted(acl, 'segment')          # containment puts it in the subnet
    nodes, children, edges = build(chain)
    pos = layout(nodes, children, edges, binding)[acl.key]
    assert pos.kind == 'rule'
    assert pos.hoist_to == 'vpc:vpc-1', pos.hoist_to


def test_a_binding_already_in_its_scope_container_is_not_hoisted(binding):
    """Hoisting only moves what is in the wrong place — no churn otherwise."""
    sg = Node('ec2.security_group', 'sg-1')
    nodes, children, edges = build(hosted(sg, 'network'))
    pos = layout(nodes, children, edges, binding)[sg.key]
    assert pos.hoist_to is None


def test_ec2_artefacts_are_not_network_bindings(binding):
    """
    A key pair, an AMI and a launch template carry an `ec2.` prefix and govern
    no network. The blanket service default filed them as things that control
    the VPC, which put provenance on the security rail.
    """
    for type_ in ('ec2.key_pair', 'ec2.ami', 'ec2.launch_template',
                  'ec2.spot_instance_request'):
        assert resolve_role(type_, {}, binding) != 'rule.network', type_


def test_autoscaling_group_is_a_binding_on_the_run_by_rail(binding):
    """
    An autoscaling group owns instances and holds no address of its own, so
    traffic never arrives at one. That makes it a binding, not a door and not a
    resident - and never the border line, which means "this is how traffic
    enters or leaves".

    North rather than south: a scaling group governs no traffic at all. It
    decides how many instances exist, which is the same question an audit trail
    answers about a change - oversight, not path. It also puts the fleet on the
    border nearest the way in, which is where a reader looks for the front of
    one.
    """
    asg = Node('autoscaling.auto_scaling_group', 'asg-1')
    nodes, children, edges = build(hosted(asg, 'segment'))
    pos = layout(nodes, children, edges, binding)[asg.key]
    assert pos.kind == 'rule'
    # West, because west is now "how it is run" and a scaling group is the
    # thing that decides how many there are. The assertion used to read
    # `rail.e`; the claim it was making has not changed, only which side of the
    # box carries it now that the arm comes from the domain.
    assert pos.anchor == 'rail.w'
    assert pos.slot == 'w-middle'
    assert not pos.anchor.startswith('edge.'), 'a fleet is not a way in'
    assert pos.hoist_to == 'vpc:vpc-1'


# ══════════════════════════════════════════════════════════════════════
# what the type NAME says it is, before what its service usually is
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('type_', [
    'rds.rds_snapshot', 'rds.db_parameter_group', 'rds.option_group',
    'memorydb.parameter_group', 'elasticache.cache_parameter_group',
    'neptune.db_subnet_group', 'lambda.version', 'scheduler.schedule_group',
    'docdb.certificate',
])
def test_configuration_and_provenance_are_artifacts_not_residents(binding, type_):
    """
    Sixty-six resources were drawn as residents because they inherited their
    service's default: `rds.rds_snapshot` took `rds -> resident.data` and appeared
    as though it were a database, `lambda.version` as though it were a function.

    None of them holds an address. The type name already said so, and the
    renderer already labelled them "configuration" and "snapshots" - which is
    the tell that the rule belonged in the data rather than the view.
    """
    assert resolve_role(type_, {}, binding) == 'record', type_


def test_an_override_still_beats_a_suffix(binding):
    """
    `acm.certificate` is the certificate service itself, not provenance from
    another one - so it stays a platform binding while `rds.certificate`
    becomes an artifact. Precedence is what keeps one general rule from
    flattening a real distinction.
    """
    assert resolve_role('acm.certificate', {}, binding) == 'rule.platform'
    assert resolve_role('rds.certificate', {}, binding) == 'record'


def test_a_target_group_is_part_of_its_load_balancer(binding):
    """One load balancer owns it, so it nests rather than sitting beside it."""
    assert resolve_role('elbv2.target_group', {}, binding) == 'part'


def test_a_security_group_is_a_binding_whichever_service_names_it(binding):
    assert resolve_role('rds.db_security_group', {}, binding) == 'rule.network'
    assert resolve_role('ec2.security_group', {}, binding) == 'rule.network'


def test_a_definition_is_a_template_not_a_running_thing(binding):
    """
    Seven Greengrass `*_definition`s filled the edge band with seven groups of
    one apiece, each drawn as though it were deployed compute. You deploy FROM
    a definition; what got deployed is the architecture.
    """
    assert resolve_role('greengrass.connector_definition', {}, binding) == 'record'
    assert resolve_role('ecs.task_definition', {}, binding) == 'record'
    assert resolve_role('batch.job_definition', {}, binding) == 'record'


def test_a_configuration_describes_a_thing_rather_than_being_one(binding):
    assert resolve_role('apprunner.auto_scaling_configuration', {}, binding) == 'record'
    assert resolve_role('autoscaling.launch_configuration', {}, binding) == 'record'


def test_the_configuration_suffix_is_anchored(binding):
    """
    `config.configuration_recorder` is a live governance control that happens
    to contain the word. An unanchored rule would have filed AWS Config's
    recorder as configuration, which is the sort of pun that makes a whole
    taxonomy untrustworthy.
    """
    assert resolve_role('config.configuration_recorder', {}, binding) != 'record'


def test_a_listener_belongs_to_one_load_balancer(binding):
    """Same argument as the target group: a port is not separate infrastructure."""
    assert resolve_role('elbv2.listener', {}, binding) == 'part'


def test_a_service_scoped_user_is_not_a_workload(binding):
    """
    An ElastiCache user is a Redis ACL entry scoped to a cache. It was drawn as
    a resident - a box in a band, beside the caches it governs - which reads as
    a running thing with an address.
    """
    assert resolve_role('elasticache.user', {}, binding) == 'rule.identity'


def test_a_region_listing_is_not_a_resource(binding):
    """
    `gamelift.location` returns region names. Drawing a box labelled
    "ap-south-1" inside ap-south-1 costs a reader more trust than it buys.
    """
    assert resolve_role('gamelift.location', {}, binding) == 'record'


def test_the_binding_has_no_duplicate_keys():
    """
    YAML keeps the LAST of two identical keys and says nothing.

    This is not hypothetical: `ecs.cluster` was bound to a control-plane role
    near the top of overrides and to a category lane 120 lines below, and the
    lane won silently. The file read correctly and the loader disagreed, which
    is the worst way for a catalog to be wrong.
    """
    import yaml

    seen = []

    class Strict(yaml.SafeLoader):
        pass

    def no_dupes(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        dupes = {k for k in keys if keys.count(k) > 1}
        seen.extend(sorted(dupes))
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dupes)
    with open(BINDING_PATH) as fh:
        yaml.load(fh, Strict)

    assert not seen, f'duplicate keys silently shadowed: {sorted(set(seen))}'


# ══════════════════════════════════════════════════════════════════════
# exposure — how far from the internet, in hops
# ══════════════════════════════════════════════════════════════════════

def test_exposure_runs_from_the_internet_inward(model):
    """
    L1 is on the open internet by definition, L4 cannot be reached from it.
    The ordering is the claim; the individual numbers are just labels for it.
    """
    roles = model['roles']
    assert roles['resident.edge']['exposure'] == 1        # CDN, global WAF
    assert roles['resident.balancer']['exposure'] == 2    # terminates at the boundary
    assert roles['resident.compute']['exposure'] == 3     # public IP + gateway, or behind an LB
    assert roles['resident.data']['exposure'] == 4        # no path in at all

    path = ['resident.edge', 'resident.balancer', 'resident.compute', 'resident.data']
    levels = [roles[r]['exposure'] for r in path]
    assert levels == sorted(levels), 'exposure must increase away from the internet'


def test_only_the_traffic_path_carries_an_exposure(model):
    """
    A policy is not nearer or further from the internet - it applies. Giving a
    binding, a door or an artifact a level would state a distance that has no
    meaning, and a reader would reasonably believe it.
    """
    for role, spec in model['roles'].items():
        if (spec or {}).get('exposure') is None:
            continue
        assert spec['kind'] == 'resident', \
            f'{role} is {spec["kind"]}, so it is not on the traffic path'


def test_an_api_gateway_is_an_entry_point(model):
    """It terminates inbound traffic at the boundary, exactly as a balancer does."""
    lanes = {lane['role']: lane for lane in model['categories']['lanes']}
    assert lanes['resident.api']['exposure'] == 2


# ══════════════════════════════════════════════════════════════════════
# the four arms — each border answers one question
# ══════════════════════════════════════════════════════════════════════

ARMS = {
    'rail.n': 'who may act, and what protects what they act on',
    'rail.e': 'how it is run — audit, config, deploy, orchestration',
    'rail.w': 'how traffic moves — firewall, routing, dns',
    'rail.s': 'attached to nothing — dangling parts and ways out',
}


def test_every_rail_names_one_of_the_four_arms(model):
    """
    A rule has no position in the traffic path, so it has to go somewhere, and
    picking the side by hand let one arm become a bin: east carried secrets,
    encryption, config, deploy, posture, provisioning and observability at once
    — seven different questions stacked on one border.
    """
    for role, spec in model['roles'].items():
        anchor = (spec or {}).get('anchor', 'in')
        if not anchor.startswith('rail.'):
            continue
        assert anchor in ARMS, f'{role} rides {anchor}, which answers no question'


def test_all_four_arms_are_used(model, binding):
    """
    Every arm answers a question, and every question has a home.

    South is the exception and deliberately so: nothing DECLARES it, because
    what rides there is decided per resource rather than per role — a part
    attached to nothing. It is populated by the placement table, so this
    exercises that path rather than reading the model.
    """
    declared = {(s or {}).get('anchor') for s in model['roles'].values()}
    for arm in ('rail.n', 'rail.e', 'rail.w'):
        assert arm in declared, f'{arm} answers "{ARMS[arm]}" and nothing rides it'

    eni = Node('ec2.network_interface', 'eni-1')
    nodes, children, edges = build(hosted(eni, 'segment'))
    pos = layout(nodes, children, edges, binding)[eni.key]
    assert pos.anchor == 'rail.s' and pos.dangling, \
        'south carries what is attached to nothing'


def test_the_arms_carry_different_questions(binding, model):
    """
    Identity governs WHO, encryption governs WHAT, network governs the PATH and
    audit WATCHES. If two of those shared an arm the side would carry no
    information, which is the state this replaced.
    """
    roles = model['roles']
    # north: who may act, and what protects what they act on
    assert roles['rule.identity']['anchor'] == 'rail.n'
    assert roles['rule.platform']['anchor'] == 'rail.n'
    # west: how traffic moves
    assert roles['rule.network']['anchor'] == 'rail.w'
    # east: how it is run
    for run_by in ('rule.governance', 'rule.orchestration', 'rule.scaling'):
        assert roles[run_by]['anchor'] == 'rail.e', \
            f'{run_by} answers "how is this run", which is east'


# ══════════════════════════════════════════════════════════════════════
# the naming rule — a role cannot lie about what it is
# ══════════════════════════════════════════════════════════════════════

def test_a_role_name_is_its_kind(model):
    """
    A role name is its kind, optionally followed by `.` and a qualifier.

    Before this rule three of eighteen roles contradicted themselves:
    `flow.egress` was a door, `plane.application` was a resident, and
    `plane.artifact` was an artifact. The prefix was pure documentation and no
    code read it, so nothing caught any of them. Now the name IS the claim.
    """
    for role, spec in model['roles'].items():
        kind = (spec or {}).get('kind')
        assert kind, f'{role} declares no kind'
        assert role == kind or role.startswith(f'{kind}.'), \
            f'{role} is a {kind}; its name should say so'


def test_there_are_exactly_six_kinds(model):
    """
    Pinned so a seventh cannot appear without someone deciding it changes
    placement — which is the only thing that makes a kind a kind. Orchestrator
    and enclosure were both proposed and both failed that test.
    """
    assert model['kinds'] == ['boundary', 'resident', 'part', 'door', 'rule', 'record']


def test_every_spine_boundary_declares_its_kind(model):
    """
    All eight spine roles carried no class at all, so the scene emitted null and
    the RENDERER invented the word "container" to fill the hole — a kind that
    existed on screen and not in the model.

    `workload` and `attachment` stay exempt: they are containment layers that no
    node ever takes as its role, verified against the live scene where
    `workload` appears zero times.
    """
    kinds = {c['role']: c.get('kind') for c in model['containers']}
    for role in ('org', 'account', 'region', 'network', 'zone', 'segment'):
        assert kinds[role] == 'boundary', f'{role} is drawn as a box; say so'
    for layer in ('workload', 'attachment'):
        assert kinds[layer] is None, f'{layer} is a layer, not a node role'


def test_attachment_is_a_layer_and_part_is_a_role(model, binding):
    """
    `attachment` was both — a spine layer in the model AND a placement role
    patched into the role table in Python, because the model had no way to say
    it. Renaming the role to `part` let it be declared like everything else.
    """
    assert 'attachment' not in model['roles'], 'a layer is not a placement role'
    assert model['roles']['part']['kind'] == 'part'
    assert {c['role'] for c in model['containers']} >= {'attachment'}
    for type_ in ('ec2.volume', 'ec2.network_interface', 'elbv2.listener'):
        assert resolve_role(type_, {}, binding) == 'part', type_


def test_no_node_is_left_without_a_kind(binding):
    """
    Ten nodes — every account, region, VPC, zone and subnet — carried no kind at
    all, so the scene emitted null and the renderer invented the word
    "container" to fill the hole. A kind that exists on screen and not in the
    model is a kind nothing can test.
    """
    nodes, children, edges = build(_fixture_nodes(), links=_links())
    for key, pos in layout(nodes, children, edges, binding).items():
        assert pos.kind, f'{key} has no kind'


# ══════════════════════════════════════════════════════════════════════
# the two gates the grid did not answer: is it drawn, and in what order
# ══════════════════════════════════════════════════════════════════════

def test_the_engine_decides_what_is_drawn(model, binding):
    """
    `model.yaml` declared `render: detail` on records for months and no code
    read it — the renderer decided for itself and the two agreed by luck. A
    declaration nothing enforces is a comment with a colon in it.
    """
    assert model['roles']['record']['render'] == 'detail'

    nodes, children, edges = build(_fixture_nodes(), links=_links())
    positions = layout(nodes, children, edges, binding)
    ami = Node('ec2.ami', 'ami-1')
    nodes[ami.key] = ami
    positions = layout(nodes, children, edges, binding)
    assert positions[ami.key].drawn is False, 'a record belongs in a panel'
    for key, pos in positions.items():
        if pos.kind != 'record':
            assert pos.drawn, f'{key} is a {pos.kind} and must draw'


def test_subcategories_in_one_slot_have_a_declared_order(model):
    """
    Thirteen subcategories share the region's north rail. They resolve to the
    same role, so they shared a rank, so the tie-break was alphabetical by
    service name — which put `governance.config` second and `analytics.query`
    ahead of `security.posture` for no reason anyone chose.

    Every other axis here has a declared rank. This one now takes its order
    from the sequence the taxonomy is written in, so re-ordering is a moved
    line rather than a new number.
    """
    ranks = taxonomy_ranks(model)
    order = [s for s in model['taxonomy']['governance']]
    ranked = sorted(order, key=lambda s: ranks[f'governance.{s}'])
    assert ranked == order, 'written order must be draw order'

    # across categories too, so a rail holding several stays grouped
    assert ranks['compute.instances'] < ranks['security.identity']
    assert ranks['security.identity'] < ranks['governance.audit']


def test_the_sort_key_uses_the_subcategory_rank(binding):
    """Ordering must consult it, or declaring it changes nothing."""
    a = Node('cloudtrail.trail', 't-1')
    b = Node('config.config_rule', 'r-1')
    nodes, children, edges = build([a, b])
    pos = layout(nodes, children, edges, binding)
    # governance.audit is written before governance.config
    assert sort_key(a, pos[a.key]) < sort_key(b, pos[b.key])


def test_a_rule_wraps_only_what_is_drawn(binding):
    """
    A security group's `protected-by` edges come mostly from its own RULES,
    which are records living in a panel. Counting them measured "all my rules
    are in the region" — true of every group, informative about none, and it
    marked 27 groups as wrappable when the real answer is 2.

    A box on the canvas can only enclose things on the canvas.
    """
    from providers.common.topology.layout import GOVERNED_BY
    assert 'protected-by' in GOVERNED_BY

    sg = Node('ec2.security_group', 'sg-1')
    ami = Node('ec2.ami', 'ami-1')
    nodes, children, edges = build(
        hosted(sg, 'network') + [ami],
        edges=[{'source_key': ami.key, 'target_key': sg.key,
                'edge_type': 'protected-by'}])
    pos = layout(nodes, children, edges, binding)
    assert pos[sg.key].wrap is None, 'a record cannot be inside a drawn box'


def test_a_wrap_must_be_tighter_than_the_rail_it_replaces(binding):
    """
    A KMS key on the region rail whose members all sit in that region is
    contiguous and says nothing — eight of them drew eight boxes round the
    whole region. The box has to enclose something smaller than where the rule
    already rides, or it carries no information.
    """
    src = open('providers/common/topology/layout.py').read()
    assert 'if container == scope:' in src, \
        'the tighter-than-scope guard is what stops a region-wide wrap'


def test_a_governing_resource_with_no_drawn_members_earns_no_code(binding):
    """
    The short-code tags (`sg-2`, `kms-1`) exist so a reader can FIND the thing
    governing a resource. 371 of 494 landed on records — resources that live in
    a detail panel and never draw — so 27 of 80 governing resources had a code
    that appeared nowhere on the canvas.

    Same artefact, third appearance: a security group's `protected-by` edges
    come mostly from its own RULES, which are records. It broke the rule-wrap
    contiguity measure and inflated `integration.messaging` before this.

    The engine's job here is only to say what draws; the renderer filters on it.
    This asserts the fact the filter depends on.
    """
    sg = Node('ec2.security_group', 'sg-1')
    rule = Node('ec2.security_group_rule', 'sgr-1')
    nodes, children, edges = build(hosted(sg, 'network') + [rule])
    positions = layout(nodes, children, edges, binding)
    assert positions[rule.key].drawn is False, \
        'a rule is a record; a tag on one points at nothing a reader can find'
    assert positions[sg.key].drawn is True


# ══════════════════════════════════════════════════════════════════════
# the model may not contain settings nothing reads
# ══════════════════════════════════════════════════════════════════════

def test_the_model_has_no_decorative_settings(model):
    """
    Five declarations read as configuration and no code consulted any of them:
    `attachment_rule.one_attached`, `segment_tiers[].test`,
    `entry_points[].where`, `edge_order.centre_out`, `cluster_placement`'s
    switches. The model is the multi-cloud contract — someone writing an Azure
    binding would reasonably change a declared test and watch nothing happen.

    One of them was not cosmetic: because the tier tests were never read, the
    `isolated` tier was UNREACHABLE. A segment with routes but none to the
    internet fell through to `unknown`, which the model itself says is an
    absence of data rather than a tier.

    Anything genuinely explanatory lives under a `note:` key, which this
    tolerates. Everything else must be reachable from code.
    """
    import os
    import re

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    code = ''
    for rel in ('providers/common/topology/layout.py',
                'providers/aws/runtime/scene.py',
                'providers/aws/runtime/layers.py'):
        with open(os.path.join(root, rel)) as fh:
            code += fh.read()

    def settings(obj):
        """Every key that is not prose, and not a value someone reads by name."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == 'note':
                    continue
                if isinstance(k, str) and re.fullmatch(r'[a-z][a-z_]{3,}', k):
                    yield k
                yield from settings(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from settings(item)

    checked = ('attachment_rule', 'edge_order', 'segment_tiers',
               'entry_points', 'cluster_placement')
    unread = sorted({k for section in checked
                     for k in settings(model.get(section))
                     if f"'{k}'" not in code and f'"{k}"' not in code})
    assert not unread, (
        'these read as settings and nothing consults them — wire them or move '
        f'them under a note: {unread}')


def test_the_isolated_tier_is_reachable(binding):
    """
    The model declares four segment tiers and the code could only ever produce
    three: `isolated` — a segment with routes but none to the internet — fell
    through to `unknown`, which the model itself calls an ABSENCE of routing
    data rather than a tier.

    Those are different facts. "I looked and there is no way out" is a finding;
    "I could not see the routes" is a gap in collection. Reporting both as
    `unknown` told a reader neither.
    """
    vpc = Node('vpc', 'vpc-1')
    zone = Node('az', 'vpc-1/az-a', parent=vpc.key)
    seg = Node('ec2.subnet', 'subnet-a', parent=zone.key)
    inst = Node('ec2.instance', 'i-1', parent=seg.key)
    rtb = Node('ec2.route_table', 'rtb-1', parent=vpc.key)

    links = {vpc.key: [zone.key, rtb.key], zone.key: [seg.key], seg.key: [inst.key]}
    # routed, but nowhere near the internet
    nodes, children, edges = build(
        [vpc, zone, seg, inst, rtb], links=links,
        edges=[{'source_key': seg.key, 'target_key': rtb.key,
                'edge_type': 'routes-through'}])
    assert layout(nodes, children, edges, binding)[seg.key].tier == 'private'

    # no route edges at all — an absence, and flagged as assumed
    nodes, children, edges = build([vpc, zone, seg, inst], links=links)
    pos = layout(nodes, children, edges, binding)[seg.key]
    assert pos.tier == 'unknown'
    assert pos.derived is False, 'an absence must not pass as a derived fact'


def test_a_lane_never_sorts_against_another_band(binding):
    """
    Lane ranks were written straight into `rank`, so they competed with band
    ranks: a lane at 10 sorted above the network band at 20, and a region's
    regional services interleaved with the VPC instead of forming a block
    beneath it. The reading order came out
    queue -> VPC -> events, which is not a sequence anyone chose.

    A lane orders things INSIDE its band. `sort_key` is
    (rank, lane_rank, sub_rank, ...) so the two can never be compared.

    The example used to be an API gateway. It no longer can be: an API gateway
    is `resident.ingress`, an L2 entry point that belongs ABOVE the network, so
    it is the one service for which sorting under the VPC is wrong. A messaging
    queue is a lane resident and makes the point without that confusion.
    """
    queue = Node('sqs.queue', 'q-1')
    vpc = Node('vpc', 'vpc-1')
    nodes, children, edges = build([queue, vpc], links={'vpc:vpc-1': []})
    pos = layout(nodes, children, edges, binding)

    # the network is a band above the services band, whatever the lane says
    assert pos[vpc.key].rank < pos[queue.key].rank
    assert sort_key(vpc, pos[vpc.key]) < sort_key(queue, pos[queue.key])
    # and the lane's own rank survives, for ordering within the band
    assert pos[queue.key].lane_rank == 20


def test_an_api_gateway_is_an_entry_point_not_a_regional_service(binding):
    """
    An API gateway terminates inbound traffic at the boundary exactly as a load
    balancer does — same L2, same job — so it draws with the front door, not in
    the services band under the VPC.

    It kept landing under the VPC because of two things at once. Its binding
    sent it to `resident.api`, a lane resident in the services band; and even
    when it reached `resident.ingress`, the demotion rule's container list was
    [network, zone, segment] while the role's own is [region, segment], so a
    region-anchored gateway was demoted straight back out of it.
    """
    region = Node('region', 'ap-south-1')
    api = Node('apigatewayv2.api', 'api-1', parent=region.key)
    vpc = Node('vpc', 'vpc-1', parent=region.key)
    nodes, children, edges = build(
        [region, api, vpc],
        links={region.key: [api.key, vpc.key], 'vpc:vpc-1': []},
    )
    pos = layout(nodes, children, edges, binding)

    assert pos[api.key].role == 'resident.ingress', 'demoted out of its own role'
    assert pos[api.key].exposure == 2, 'terminates inbound traffic at the boundary'
    # Above the network, because that is what L2 in front of L3 means.
    assert pos[api.key].rank < pos[vpc.key].rank
    assert sort_key(api, pos[api.key]) < sort_key(vpc, pos[vpc.key])


def test_an_api_gateway_and_a_load_balancer_rank_as_peers(binding):
    """
    Both are L2 entry points, so neither is upstream of the other and they read
    side by side (A2) rather than as a sequence. They differ only in WHERE they
    terminate — a balancer in the network, a gateway in the region — which is
    the containers, not the rank.
    """
    region = Node('region', 'ap-south-1')
    api = Node('apigatewayv2.api', 'api-1', parent=region.key)
    vpc = Node('vpc', 'vpc-1', parent=region.key)
    lb = Node('elbv2.load_balancer', 'lb-1', parent=vpc.key)
    nodes, children, edges = build(
        [region, api, vpc, lb],
        links={region.key: [api.key, vpc.key], vpc.key: [lb.key]},
    )
    pos = layout(nodes, children, edges, binding)

    assert pos[api.key].rank == pos[lb.key].rank, 'peers, so neither precedes the other'
    assert pos[api.key].exposure == pos[lb.key].exposure == 2


def test_the_order_of_both_axes_survives_serialisation(binding):
    """
    The engine computes `sub_rank` from the taxonomy and `lane_rank` from the
    model's lane list, and used to emit neither — so the view got `datastore`
    and `object` as bare strings with nothing saying which came first, and fell
    back to sorting by the alphabet of whatever the first member was called.
    That is the whole reason `taxonomy_ranks()` exists.

    Same defect as `render: detail`, as `edge_order.centre_out`, and as
    `categories.wrap`: a fact the engine knows, does not say, and the renderer
    then guesses. A name without its order is half a fact.
    """
    region = Node('region', 'ap-south-1')
    bucket = Node('s3.bucket', 'b-1', parent=region.key)
    table = Node('dynamodb.table', 't-1', parent=region.key)
    nodes, children, edges = build(
        [region, bucket, table],
        links={region.key: [bucket.key, table.key]},
    )
    pos = layout(nodes, children, edges, binding)

    for key in (bucket.key, table.key):
        emitted = pos[key].to_dict()
        assert 'category' in emitted
        assert 'sub_rank' in emitted, 'a subcategory with no order is half a fact'
        assert 'lane_rank' in emitted

    # And the order is real: storage sorts before database in the taxonomy, so
    # an object store precedes a key-value one wherever both appear.
    assert pos[bucket.key].sub_rank != pos[table.key].sub_rank


def test_a_rollup_never_spans_two_arms():
    """
    A rollup is display only: several domains drawn as one tab. If two of them
    sat on different arms that tab would have to draw in two places, so the
    rollup would be making a placement claim it has no business making.
    """
    import collections

    import yaml

    from providers.common.topology.layout import resolve_slot

    with open('providers/common/topology/model.yaml') as fh:
        model = yaml.safe_load(fh)

    arms = collections.defaultdict(set)
    for domain, label in (model.get('rollup') or {}).items():
        category, _, sub = domain.partition('.')
        found = resolve_slot(category, sub, model)
        assert found, f'{domain} rolls up but resolves to no slot'
        arms[label].add(found[0])
    split = {label: slots for label, slots in arms.items() if len(slots) > 1}
    assert not split, f'rollups spanning more than one slot: {split}'


def test_every_rolled_up_domain_is_a_real_domain():
    """A rollup keyed on a domain the taxonomy never declares silently does
    nothing, which is the failure mode this whole model keeps producing."""
    import yaml

    with open('providers/common/topology/model.yaml') as fh:
        model = yaml.safe_load(fh)

    declared = {f'{c}.{s}' for c, subs in (model.get('taxonomy') or {}).items() for s in subs}
    unknown = [d for d in (model.get('rollup') or {}) if d not in declared]
    assert not unknown, f'rollup names domains the taxonomy does not have: {unknown}'


# ══════════════════════════════════════════════════════════════════════
# exposure invariants (§4e)
# ══════════════════════════════════════════════════════════════════════
#
# §4e states "Only residents carry a level ... Enforced by test." It was not.
# Nothing checked it, and the claim survived in the spec unchallenged while
# `door.ingress` was being added — the one change most likely to break it.
#
# The rule matters because a level is a claim about DISTANCE from the internet,
# and distance is only meaningful for something traffic can arrive at. A rule
# does not sit nearer or further from the internet; it applies. Giving one a
# level states a fact that has no referent, and a reader would believe it.

def test_only_residents_carry_an_exposure_level():
    model = load_model()
    offenders = [
        (role, spec.get('kind'), spec.get('exposure'))
        for role, spec in (model.get('roles') or {}).items()
        if (spec or {}).get('exposure') is not None
        and (spec or {}).get('kind') != 'resident'
    ]
    assert not offenders, (
        "a non-resident role declares an exposure level: "
        f"{offenders}. §4e — only residents carry one."
    )


def test_every_resident_role_carries_a_level():
    """
    The other half, and the one that catches a reclassification going the wrong
    way: a resident with no level is off the exposure ladder entirely, so it
    sorts as though it were the safest thing in the estate.
    """
    model = load_model()
    missing = [
        role for role, spec in (model.get('roles') or {}).items()
        if (spec or {}).get('kind') == 'resident'
        and (spec or {}).get('exposure') is None
    ]
    assert not missing, f"resident roles with no exposure level: {missing}"


def test_cloudfront_and_dns_are_doors_on_the_account_border(binding):
    """
    The Sprint 1 change itself. A CDN and public DNS are how traffic from the
    internet finds this account at all, which is the door test in §4b — not
    residents that happen to sit high in the flow.
    """
    nodes, children, edges = build([
        Node('cloudfront.distribution', 'd-1'),
        Node('route53.hosted_zone', 'z-1'),
    ])
    positions = layout(nodes, children, edges, binding)
    for key in ('cloudfront.distribution:d-1', 'route53.hosted_zone:z-1'):
        pos = positions[key]
        assert pos.kind == 'door', f'{key} should be a door, got {pos.kind}'
        assert pos.anchor == 'edge.n', f'{key} should ride the north edge'
        assert pos.edge_align == 'right', f'{key} should align right'
        assert pos.exposure is None, (
            f'{key} is a door and must not carry an exposure level (§4e)'
        )


def test_the_edge_family_that_stayed_resident(binding):
    """
    The blast radius that had to be avoided. Four types shared `resident.edge`
    with CloudFront; a WAF governs a way through without being one, which makes
    it a rule-like resident, not a door. Rebinding the group would have filled
    the account's top line with things that do not belong on a border.
    """
    for type_, id_ in (('globalaccelerator.accelerator', 'a-1'),
                       ('wafv2.web_acl', 'w-1'),
                       ('shield.protection', 's-1')):
        nodes, children, edges = build([Node(type_, id_)])
        pos = layout(nodes, children, edges, binding)[f'{type_}:{id_}']
        assert pos.anchor == 'in', f'{type_} should still draw inline'
        assert pos.kind == 'resident', f'{type_} should still be a resident'


def test_edge_align_defaults_to_centre_for_existing_doors():
    """
    A new field must not move anything that predates it. Every door that existed
    before `edge_align` keeps the behaviour it had, which for a strip that has
    only ever started at one place is `centre`.
    """
    model = load_model()
    for role, spec in (model.get('roles') or {}).items():
        if (spec or {}).get('kind') != 'door' or role == 'door.ingress':
            continue
        assert (spec or {}).get('edge_align') in (None, 'centre'), (
            f'{role} changed alignment without being asked to'
        )
