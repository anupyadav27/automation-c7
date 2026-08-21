"""Cross-account discovery tests — offline, against realistic payloads."""

import pytest

from providers.aws.runtime import accounts

OURS = '111111111111'
NETWORK_ACCOUNT = '222222222222'
PROVIDER = '333333333333'
PARTNER = '444444444444'


@pytest.fixture
def graph():
    return accounts.AccountGraph(OURS)


# ── the general detector: ARNs ────────────────────────────────────────

def test_arn_in_any_field_reveals_an_account(graph):
    asset = {'resource_key': 'lambda.function', 'raw': {
        'FunctionName': 'f',
        'Role': f'arn:aws:iam::{PARTNER}:role/CrossAccountRole',
    }}
    accounts.scan_asset(graph, asset)
    assert PARTNER in graph
    row = next(r for r in graph.rows() if r['account_id'] == PARTNER)
    assert row['discovered_via'] == 'arn_account'


def test_our_own_account_is_never_recorded(graph):
    asset = {'resource_key': 'ec2.instance', 'raw': {
        'OwnerId': OURS, 'Arn': f'arn:aws:ec2:r:{OURS}:instance/i-1'}}
    accounts.scan_asset(graph, asset)
    assert len(graph) == 0


@pytest.mark.parametrize('value', ['not-an-account', '12345', '', None,
                                   '1234567890123'])
def test_non_account_values_are_ignored(graph, value):
    graph.add(value, 'referenced', 'test')
    assert len(graph) == 0


# ── shared subnets: the central-network model ─────────────────────────

def test_subnet_owned_elsewhere_is_an_owner_relationship(graph):
    """RAM-shared subnet — we run inside another account's network."""
    subnet = {'resource_key': 'ec2.subnet', 'raw': {
        'SubnetId': 'subnet-a', 'OwnerId': NETWORK_ACCOUNT, 'VpcId': 'vpc-1'}}
    accounts.scan_asset(graph, subnet)
    row = next(r for r in graph.rows() if r['account_id'] == NETWORK_ACCOUNT)
    assert row['relationship'] == 'owner'


def test_external_owner_identifies_a_shared_resource():
    shared = {'raw': {'SubnetId': 'subnet-a', 'OwnerId': NETWORK_ACCOUNT}}
    ours = {'raw': {'SubnetId': 'subnet-b', 'OwnerId': OURS}}
    assert accounts.external_owner(shared, OURS) == NETWORK_ACCOUNT
    assert accounts.external_owner(ours, OURS) is None


# ── peering and transit ───────────────────────────────────────────────

def test_peering_accepter_is_a_peer(graph):
    peering = {'resource_key': 'ec2.vpc_peering_connection', 'raw': {
        'VpcPeeringConnectionId': 'pcx-1',
        'AccepterVpcInfo': {'OwnerId': PARTNER, 'VpcId': 'vpc-9'},
        'RequesterVpcInfo': {'OwnerId': OURS, 'VpcId': 'vpc-1'},
    }}
    accounts.scan_asset(graph, peering)
    row = next(r for r in graph.rows() if r['account_id'] == PARTNER)
    assert row['relationship'] == 'peer'


def test_transit_gateway_attachment_owner_is_a_peer(graph):
    attachment = {'resource_key': 'ec2.transit_gateway_attachment', 'raw': {
        'TransitGatewayAttachmentId': 'tgw-attach-1',
        'ResourceOwnerId': PARTNER, 'ResourceType': 'vpc'}}
    accounts.scan_asset(graph, attachment)
    assert next(r for r in graph.rows()
                if r['account_id'] == PARTNER)['relationship'] == 'peer'


# ── the shared-appliance (F5) shape ───────────────────────────────────

def test_customer_endpoint_service_reveals_a_provider(graph):
    """
    A `com.amazonaws.vpce.` service is published by another account — this is
    the shared-appliance case, and the provider is named in the payload.
    """
    # The provider id lives on the endpoint SERVICE; DescribeVpcEndpoints'
    # own `Owner` field is our account.
    service = {'resource_key': 'ec2.vpc_endpoint_service', 'raw': {
        'ServiceName': 'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc',
        'Owner': PROVIDER, 'ServiceType': [{'ServiceType': 'Interface'}]}}
    accounts.scan_asset(graph, service)
    row = next(r for r in graph.rows() if r['account_id'] == PROVIDER)
    assert row['relationship'] == 'provider'
    assert 'endpoint_service' in row['discovered_via']


def test_endpoint_with_no_provider_id_is_recorded_as_unresolved(graph):
    """The external dependency is real even when the owner id is absent."""
    endpoint = {'resource_key': 'ec2.vpc_endpoint', 'raw': {
        'VpcEndpointId': 'vpce-1', 'Owner': OURS,
        'ServiceName': 'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc'}}
    accounts.scan_asset(graph, endpoint)
    assert len(graph) == 0
    assert graph.unresolved_services == [
        'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc']


def test_aws_own_endpoint_service_is_not_a_provider(graph):
    """`com.amazonaws.<region>.s3` is AWS's own — no third party involved."""
    endpoint = {'resource_key': 'ec2.vpc_endpoint', 'raw': {
        'VpcEndpointId': 'vpce-2',
        'ServiceName': 'com.amazonaws.ap-southeast-1.s3',
        'VpcEndpointType': 'Gateway'}}
    accounts.scan_asset(graph, endpoint)
    assert len(graph) == 0


# ── policies ──────────────────────────────────────────────────────────

def test_policy_principals_become_trusted_accounts(graph):
    edges = [
        {'principal_kind': 'account', 'source_id': PARTNER,
         'edge_type': 'assumes', 'target_id': 'AppRole'},
        {'principal_kind': 'arn', 'source_id': f'arn:aws:iam::{PROVIDER}:role/X',
         'edge_type': 'accessible-by', 'target_id': 'my-bucket'},
        {'principal_kind': 'service', 'source_id': 'ec2.amazonaws.com',
         'edge_type': 'assumes', 'target_id': 'AppRole'},
    ]
    accounts.scan_policy_edges(graph, edges)
    assert {r['account_id'] for r in graph.rows()} == {PARTNER, PROVIDER}
    assert all(r['relationship'] == 'trusted' for r in graph.rows())


# ── strengthening and naming ──────────────────────────────────────────

def test_repeated_sightings_strengthen_the_relationship(graph):
    graph.add(NETWORK_ACCOUNT, 'referenced', 'arn_account')
    graph.add(NETWORK_ACCOUNT, 'owner', 'owner_id')
    row = graph.rows()[0]
    assert row['relationship'] == 'owner', 'a stronger signal must win'
    assert row['sightings'] == 2
    assert row['discovered_via'] == 'arn_account,owner_id'


def test_a_weaker_later_signal_does_not_downgrade(graph):
    graph.add(PROVIDER, 'provider', 'endpoint_service')
    graph.add(PROVIDER, 'referenced', 'arn_account')
    assert graph.rows()[0]['relationship'] == 'provider'


def test_organizations_supplies_names(graph):
    graph.add(NETWORK_ACCOUNT, 'owner', 'owner_id')
    accounts.apply_organization(graph, [
        {'Id': NETWORK_ACCOUNT, 'Name': 'shared-network'},
        {'Id': PARTNER, 'Name': 'data-platform'},
        {'Id': OURS, 'Name': 'ourselves'},
    ])
    rows = {r['account_id']: r for r in graph.rows()}
    assert rows[NETWORK_ACCOUNT]['name'] == 'shared-network'
    assert rows[NETWORK_ACCOUNT]['relationship'] == 'owner', 'naming must not downgrade'
    # An org member we never saw in any resource is still worth recording.
    assert rows[PARTNER]['name'] == 'data-platform'
    assert OURS not in rows


def test_rows_are_ordered_by_significance(graph):
    graph.add(PARTNER, 'referenced', 'arn_account')
    graph.add(NETWORK_ACCOUNT, 'owner', 'owner_id')
    graph.add(PROVIDER, 'provider', 'endpoint_service')
    assert [r['account_id'] for r in graph.rows()] == \
        [NETWORK_ACCOUNT, PROVIDER, PARTNER]


# ── the enterprise shape, end to end ──────────────────────────────────

def test_full_enterprise_estate_from_one_account(graph):
    """
    One workload account: subnets from a network account, an F5 behind an
    endpoint service in a provider account, a peer, and a trusted partner.
    All four are discoverable without leaving our own credentials.
    """
    assets = [
        {'resource_key': 'ec2.subnet', 'raw': {
            'SubnetId': 'subnet-a', 'OwnerId': NETWORK_ACCOUNT}},
        {'resource_key': 'ec2.vpc_endpoint', 'raw': {
            'VpcEndpointId': 'vpce-1', 'Owner': OURS,
            'ServiceName': 'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc'}},
        {'resource_key': 'ec2.vpc_endpoint_service', 'raw': {
            'ServiceName': 'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc',
            'Owner': PROVIDER}},
        {'resource_key': 'ec2.vpc_peering_connection', 'raw': {
            'AccepterVpcInfo': {'OwnerId': PARTNER}}},
    ]
    for asset in assets:
        accounts.scan_asset(graph, asset)
    accounts.scan_policy_edges(graph, [
        {'principal_kind': 'account', 'source_id': PARTNER,
         'edge_type': 'assumes', 'target_id': 'AppRole'}])

    found = {r['account_id']: r['relationship'] for r in graph.rows()}
    assert found == {NETWORK_ACCOUNT: 'owner', PROVIDER: 'provider',
                     PARTNER: 'peer'}
    assert accounts.summarise(graph) == {'owner': 1, 'provider': 1, 'peer': 1}
