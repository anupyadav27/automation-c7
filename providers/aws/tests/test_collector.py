"""Collector and value-match tests — offline, against fixture payloads."""

import pytest

from providers.aws.runtime import collector as col
from providers.aws.runtime import valuematch as vm

ACCOUNT, REGION = '123456789012', 'ap-southeast-1'

CATALOG = {
    'ec2.instance': {
        'key': 'ec2.instance', 'service': 'ec2', 'resource_name': 'Instance',
        'operation': 'describe_instances', 'tier': 'primary',
        'items_for': '{{ response.Reservations[].Instances }}',
        'id_field': 'InstanceId', 'arn_field': '', 'arn_type': 'instance',
        'arn_separator': '/', 'arn_strategy': 'construct',
        'global_resource': 'false', 'cfn_type': 'AWS::EC2::Instance',
        'c7n_name': 'ec2',
    },
    'iam.role': {
        'key': 'iam.role', 'service': 'iam', 'resource_name': 'Role',
        'operation': 'list_roles', 'tier': 'primary',
        'items_for': '{{ response.Roles }}', 'id_field': 'RoleName',
        'arn_field': 'Arn', 'arn_type': 'role', 'arn_separator': '/',
        'arn_strategy': 'field', 'global_resource': 'true', 'c7n_name': 'iam-role',
    },
}
ASSETS_META = {
    'ec2.instance': {'asset_class': 'asset', 'parent_params': '', 'required_args': ''},
    'iam.role': {'asset_class': 'asset', 'parent_params': '', 'required_args': ''},
}


@pytest.fixture
def collector():
    return col.Collector(REGION, ACCOUNT, 'prod', session=object(),
                         catalog=CATALOG, assets_meta=ASSETS_META,
                         locations={}, layers={})


# ── the read-only guard ───────────────────────────────────────────────

@pytest.mark.parametrize('op', ['describe_instances', 'list_roles',
                                'get_bucket_policy', 'batch_get_projects'])
def test_read_operations_are_allowed(op):
    col.Collector.assert_read_only(op)


@pytest.mark.parametrize('op', ['delete_bucket', 'create_role', 'put_object',
                                'terminate_instances', 'update_stack',
                                'modify_instance_attribute'])
def test_write_operations_raise(op):
    """
    A write verb means the catalog is wrong. Raising stops the run so it gets
    fixed; skipping would let the bug persist unnoticed.
    """
    with pytest.raises(col.ReadOnlyViolation):
        col.Collector.assert_read_only(op)


# ── response unpacking ────────────────────────────────────────────────

def test_extract_items_walks_a_nested_container():
    page = {'Reservations': [
        {'Instances': [{'InstanceId': 'i-1'}, {'InstanceId': 'i-2'}]},
        {'Instances': [{'InstanceId': 'i-3'}]}]}
    got = col.extract_items(page, '{{ response.Reservations[].Instances }}')
    assert [i['InstanceId'] for i in got] == ['i-1', 'i-2', 'i-3']


@pytest.mark.parametrize('page', [{}, {'Reservations': []}, {'Other': [1, 2]}])
def test_extract_items_on_an_empty_account(page):
    assert col.extract_items(page, '{{ response.Reservations[].Instances }}') == []


def test_parse_selector_args():
    assert col.parse_args('resourceOwner=SELF,Scope=REGIONAL') == {
        'resourceOwner': 'SELF', 'Scope': 'REGIONAL'}
    assert col.parse_args('') == {}


# ── asset records ─────────────────────────────────────────────────────

def test_asset_gets_a_constructed_arn(collector):
    asset = collector.build_asset('ec2.instance', {
        'InstanceId': 'i-0abc', 'Tags': [{'Key': 'Name', 'Value': 'web-1'}]})
    assert asset['arn'] == f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0abc'
    assert asset['asset_id'] == asset['arn']
    assert asset['arn_source'] == 'construct'
    assert asset['name'] == 'web-1'
    assert asset['tags'] == {'Name': 'web-1'}


def test_global_resource_has_no_region(collector):
    asset = collector.build_asset('iam.role', {
        'RoleName': 'AppRole', 'Arn': f'arn:aws:iam::{ACCOUNT}:role/AppRole'})
    assert asset['region'] == '', 'IAM is global; a region would be wrong'
    assert asset['arn_source'] == 'field'


def test_unidentifiable_item_is_dropped(collector):
    assert collector.build_asset('ec2.instance', {'NoIdHere': 1}) is None


def test_foreign_owner_is_recorded(collector):
    """A resource owned elsewhere is shared to us — the diagram must say so."""
    asset = collector.build_asset('ec2.instance', {
        'InstanceId': 'i-9', 'OwnerId': '999999999999'})
    assert asset['owner_account'] == '999999999999'


def test_own_account_is_not_flagged_as_foreign(collector):
    asset = collector.build_asset('ec2.instance', {
        'InstanceId': 'i-9', 'OwnerId': ACCOUNT})
    assert asset['owner_account'] == ''


# ── planning and memoisation ──────────────────────────────────────────

def test_plan_separates_roots_from_children():
    meta = dict(ASSETS_META)
    meta['ec2.instance'] = {**meta['ec2.instance'], 'parent_params': 'VpcId'}
    c = col.Collector(REGION, ACCOUNT, catalog=CATALOG, assets_meta=meta,
                      locations={}, layers={}, session=object())
    roots, children = c.plan()
    assert [r.resource_key for r in roots] == ['iam.role']
    assert [r.resource_key for r in children] == ['ec2.instance']


def test_plan_respects_an_explicit_type_list(collector):
    roots, _ = collector.plan(only={'iam.role'})
    assert [r.resource_key for r in roots] == ['iam.role']


def test_a_repeated_call_signature_fires_once(collector):
    calls = []

    class FakeClient:
        def can_paginate(self, _op):
            return False

        def describe_instances(self, **kw):
            calls.append(kw)
            return {'Reservations': []}

    collector._clients['ec2'] = FakeClient()
    collector.call('ec2', 'describe_instances', {'MaxResults': 5})
    collector.call('ec2', 'describe_instances', {'MaxResults': 5})
    assert len(calls) == 1, 'the same call must not fire twice'


def test_failures_are_recorded_not_raised(collector):
    class Boom:
        def can_paginate(self, _op):
            return False

        def describe_instances(self, **kw):
            err = Exception('denied')
            err.response = {'Error': {'Code': 'AccessDenied'}}
            raise err

    collector._clients['ec2'] = Boom()
    assert collector.call('ec2', 'describe_instances') == []
    assert collector.failures[0]['code'] == 'AccessDenied'
    assert collector.failures[0]['benign'] is True, \
        'no role can read every type; a denial is normal'


# ── mechanism C ───────────────────────────────────────────────────────

@pytest.mark.parametrize('name,kind,ident', [
    ('com.amazonaws.ap-southeast-1.s3', 'aws', 's3'),
    ('com.amazonaws.ap-southeast-1.execute-api', 'aws', 'execute-api'),
    ('com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc123', 'customer',
     'vpce-svc-0abc123'),
    ('not-a-service', None, None),
])
def test_endpoint_service_name_is_parsed(name, kind, ident):
    assert vm.match_aws_service_name(name) == (kind, ident)


@pytest.mark.parametrize('left,right,expected', [
    ('my-lb-123.ap-southeast-1.elb.amazonaws.com.',
     'my-lb-123.ap-southeast-1.elb.amazonaws.com', True),
    ('dualstack.my-lb.elb.amazonaws.com',
     'my-lb.elb.amazonaws.com', True),
    ('other.elb.amazonaws.com', 'my-lb.elb.amazonaws.com', False),
])
def test_dns_names_match_despite_route53_formatting(left, right, expected):
    assert vm.match_dns_name(left, right) is expected


def test_s3_origin_domain_yields_the_bucket():
    assert vm.match_s3_origin('prod-data.s3.ap-southeast-1.amazonaws.com',
                              'prod-data') is True
    assert vm.match_s3_origin('prod-data.s3.amazonaws.com', 'other') is False


@pytest.mark.parametrize('rule,target,expected', [
    ('10.0.0.0/8', '10.1.0.0/16', True),
    ('10.1.0.0/16', '10.0.0.0/8', False),
    # An open rule contains every subnet; matching it to each one would draw an
    # edge from the rule to the whole estate.
    ('0.0.0.0/0', '10.0.0.0/16', False),
    ('not-a-cidr', '10.0.0.0/16', False),
])
def test_cidr_containment(rule, target, expected):
    assert vm.match_cidr_contains(rule, target) is expected


@pytest.mark.parametrize('value,expected', [
    ('0.0.0.0/0', True), ('::/0', True), ('10.0.0.0/16', False), ('', False)])
def test_default_route_detection(value, expected):
    assert vm.is_default_route(value) is expected


def test_value_match_finds_a_route53_alias_to_a_load_balancer():
    assets = [
        {'asset_id': 'a1', 'resource_key': 'route53.resource_record_set',
         'raw': {'AliasTarget': {'DNSName': 'my-lb.elb.amazonaws.com.'}}},
        {'asset_id': 'a2', 'resource_key': 'elbv2.load_balancer',
         'raw': {'DNSName': 'my-lb.elb.amazonaws.com'}},
    ]
    rules = [{'source_key': 'route53.resource_record_set',
              'source_path': 'AliasTarget.DNSName', 'match_kind': 'dns_name',
              'target_key': 'elbv2.load_balancer', 'target_path': 'DNSName',
              'edge_type': 'routes-to', 'confidence': 'high'}]
    edges = list(vm.derive_edges(assets, rules))
    assert len(edges) == 1
    assert edges[0]['target_asset_id'] == 'a2'
    assert edges[0]['edge_type'] == 'routes-to'


def test_value_match_flags_a_customer_endpoint_service_as_external():
    """The shared-appliance case: the far end is another account's service."""
    assets = [{'asset_id': 'e1', 'resource_key': 'ec2.vpc_endpoint',
               'raw': {'ServiceName':
                       'com.amazonaws.vpce.ap-southeast-1.vpce-svc-0abc'}}]
    rules = [{'source_key': 'ec2.vpc_endpoint', 'source_path': 'ServiceName',
              'match_kind': 'aws_service_name', 'target_key': '',
              'target_path': '', 'edge_type': 'fronts', 'confidence': 'high'}]
    edges = list(vm.derive_edges(assets, rules))
    assert len(edges) == 1
    assert edges[0]['external'] is True
    assert edges[0]['target_asset_id'] == 'aws-service:vpce-svc-0abc'


def test_value_match_resolves_an_aws_endpoint_service():
    assets = [{'asset_id': 'e2', 'resource_key': 'ec2.vpc_endpoint',
               'raw': {'ServiceName': 'com.amazonaws.ap-southeast-1.s3'}}]
    rules = [{'source_key': 'ec2.vpc_endpoint', 'source_path': 'ServiceName',
              'match_kind': 'aws_service_name', 'target_key': '',
              'target_path': '', 'edge_type': 'fronts', 'confidence': 'high'}]
    edges = list(vm.derive_edges(assets, rules))
    assert edges[0]['target_asset_id'] == 'aws-service:s3'
    assert edges[0]['external'] is False


def test_shipped_value_join_rules_all_have_a_matcher():
    """Every rule in the catalog must be executable, or it is dead weight."""
    for rule in vm.load_rules():
        assert rule['match_kind'] in vm.MATCHERS, \
            f"{rule['source_key']} uses unknown match_kind {rule['match_kind']}"


# ── lifecycle filters ─────────────────────────────────────────────────
#
# A dead resource is not part of the estate. AWS keeps returning terminated
# instances from DescribeInstances for up to an hour and strips their SubnetId,
# so they can never be placed in the network they used to occupy - they drew as
# workloads floating loose in the availability zone. In this account they were
# 17 of 20 instances, which is most of the diagram.

def test_filter_reads_a_nested_field(collector):
    """
    Lifecycle state is nested, and a flat lookup silently matched nothing.

    `item.get('State.Name')` returns None for every instance ever collected, so
    the rule never fired and the filter looked like it was working. That is the
    worst kind of bug in a filter: it fails open and quietly.
    """
    assert collector._field({'State': {'Name': 'terminated'}}, 'State.Name') == 'terminated'
    assert collector._field({'State': 'closed'}, 'State') == 'closed'
    assert collector._field({'State': {'Name': 'running'}}, 'State.Code') is None
    assert collector._field({}, 'State.Name') is None
    # A scalar where a mapping was expected must not raise.
    assert collector._field({'State': 'closed'}, 'State.Name') is None


def test_terminated_instances_are_dropped_and_running_ones_kept(collector):
    collector.collection_filters = {'ec2.instance': [
        {'field': 'State.Name', 'op': 'in',
         'value': 'terminated|shutting-down', 'action': 'drop'}]}

    assert collector._filtered_out('ec2.instance', {'State': {'Name': 'terminated'}})
    assert collector._filtered_out('ec2.instance', {'State': {'Name': 'shutting-down'}})
    assert not collector._filtered_out('ec2.instance', {'State': {'Name': 'running'}})
    assert not collector._filtered_out('ec2.instance', {'State': {'Name': 'stopped'}})
    # A drop is counted, never silent.
    assert sum(collector.filtered.values()) == 2


def test_every_shipped_filter_rule_uses_a_known_operator():
    """A typo in `op` makes the rule a no-op rather than an error."""
    from providers.aws.runtime.collector import FILTER_OPS, load_collection_filters
    for key, rules in load_collection_filters().items():
        for rule in rules:
            assert rule['op'] in FILTER_OPS, f'{key}: unknown op {rule["op"]!r}'
            assert rule['action'] == 'drop', f'{key}: unknown action'


def test_comma_joined_id_lists_resolve_to_their_parts():
    """
    An autoscaling group names its subnets as ONE comma-joined string. Resolved
    whole it matches nothing, so the group never reaches the VPC it launches
    into. Splitting is deliberately narrow - only bare tokens - so a
    description or an ARN keeps its commas.
    """
    from providers.aws.runtime.resolver import resolve_path
    assert resolve_path({'Z': 'subnet-a,subnet-b'}, 'Z') == ['subnet-a', 'subnet-b']
    assert resolve_path({'D': 'web tier, prod'}, 'D') == ['web tier, prod']
    assert resolve_path({'V': 'vpc-1'}, 'V') == ['vpc-1']
    assert resolve_path({'A': 'arn:aws:ec2:r:1:vpc/vpc-1'}, 'A') == ['arn:aws:ec2:r:1:vpc/vpc-1']


# ══════════════════════════════════════════════════════════════════════
# absence must be explicable — the bug that hid an entire EKS cluster
# ══════════════════════════════════════════════════════════════════════

def test_a_list_of_bare_names_is_not_discarded():
    """
    `eks.list_clusters` returns `{"clusters": ["prod"]}` — names, not objects.

    Filtering the extraction to dicts dropped every such type on the floor: it
    collected zero, logged no failure, and looked exactly like an account that
    owns no clusters. This estate HAS an EKS cluster; an autoscaling group in
    it is named `eks-nodegroup-spot-secops-…`.
    """
    from providers.aws.runtime.collector import extract_items

    assert extract_items({'clusters': ['prod', 'dev']},
                         '{{ response.clusters }}') == ['prod', 'dev']
    assert extract_items({'taskArns': ['arn:aws:ecs:eu-west-1:1:task/a']},
                         '{{ response.taskArns }}') == ['arn:aws:ecs:eu-west-1:1:task/a']
    # objects still come through untouched
    assert extract_items({'Functions': [{'FunctionName': 'f'}]},
                         '{{ response.Functions }}') == [{'FunctionName': 'f'}]


def test_a_bare_identifier_becomes_an_item_the_catalog_can_read():
    """
    Which field it lands in is decided by the value, not the operation: an
    `arn:` prefix is unambiguous and nothing else is.
    """
    from providers.aws.runtime.collector import Collector

    col = Collector.__new__(Collector)
    col.catalog = {
        'eks.cluster': {'id_field': 'name', 'arn_field': 'arn'},
        'ecs.task': {'id_field': 'taskArn', 'arn_field': 'taskArn'},
    }
    assert col._as_item('eks.cluster', 'secops-prod') == {'name': 'secops-prod'}

    arn = 'arn:aws:ecs:ap-south-1:1:task/abc'
    assert col._as_item('ecs.task', arn) == {'taskArn': arn, 'name': 'abc'}
    # a dict is already an item and must be left exactly as it came
    assert col._as_item('eks.cluster', {'name': 'x'}) == {'name': 'x'}


def test_the_three_ways_of_producing_nothing_stay_apart():
    """
    Failed, answered-with-nothing-usable, and already-called-by-another-type
    are different facts. Collapsed into "0 assets" they are indistinguishable
    from an empty account — which is how three separate investigations in this
    project each dead-ended.
    """
    from providers.aws.runtime.collector import Collector

    col = Collector.__new__(Collector)
    col.barren, col.skipped_calls = [], []
    col._lock = __import__('threading').Lock()

    col._record_barren('eks.cluster', {'service': 'eks', 'operation': 'list_clusters'},
                       2, 'items extracted but no asset built')
    col._record_skipped_call('organizations.org_account', 'organizations', 'list_accounts')

    assert col.barren[0]['key'] == 'eks.cluster'
    assert col.barren[0]['raw_items'] == 2
    assert col.skipped_calls[0]['key'] == 'organizations.org_account'


def test_a_second_type_reading_the_same_call_gets_the_answer():
    """
    `describe_alarms` returns MetricAlarms AND CompositeAlarms — two genuine
    resource types from one call. Handing the second caller an empty list was
    not a cache, it was data loss, and it hid metric alarms entirely.
    """
    import threading

    from providers.aws.runtime.collector import Collector

    col = Collector.__new__(Collector)
    col._lock = threading.Lock()
    col._seen_calls = set()
    col._call_cache = {}
    col.skipped_calls = []
    col.calls_made = 0
    col.max_retries = 1
    col.max_pages = 10
    col._client_cache = {}

    pages = [{'MetricAlarms': [{'AlarmName': 'a'}], 'CompositeAlarms': []}]
    sig = ('cloudwatch', 'describe_alarms', '{}')
    col._seen_calls.add(sig)
    col._cache(sig, pages)

    got = col.call('cloudwatch', 'describe_alarms', {}, key='cloudwatch.composite_alarm')
    assert got == pages, 'the second type must see what the first one fetched'
    assert col.skipped_calls[0]['key'] == 'cloudwatch.composite_alarm'


def test_recording_a_skipped_call_does_not_deadlock():
    """
    `_record_skipped_call` takes the same non-reentrant lock `call()` holds.
    Recording from inside that lock hung every worker in the pool, which the
    suite caught only because it stopped finishing.
    """
    import threading

    from providers.aws.runtime.collector import Collector

    col = Collector.__new__(Collector)
    col._lock = threading.Lock()
    # A real read verb: assert_read_only refuses anything else, and a thread
    # that raises would look exactly like a thread that hung.
    col._seen_calls = {('cloudwatch', 'describe_alarms', '{}')}
    col._call_cache = {}
    col.skipped_calls = []

    done = threading.Event()

    def go():
        col.call('cloudwatch', 'describe_alarms', {}, key='k')
        done.set()

    threading.Thread(target=go, daemon=True).start()
    assert done.wait(timeout=5), 'call() deadlocked on its own lock'


def test_a_bare_parameter_name_does_not_match_every_asset():
    """
    53 collectable child types ask for a parameter called `id`. Matching that
    loosely against every asset that has one is a cross product, not a lookup —
    it turned a five-minute collection into an unbounded one.

    The convention that DOES carry information is the noun-qualified form:
    `clusterName` means the cluster's name, and nothing else does.
    """
    import csv

    from providers.aws.runtime.collector import GENERIC_PARAMS

    for bare in ('id', 'name', 'arn', 'resourcearn', 'type'):
        assert bare in GENERIC_PARAMS

    with open('providers/aws/catalog/asset_types.csv') as fh:
        meta = list(csv.DictReader(fh))

    wanted = [m['parent_params'] for m in meta
              if m['collect'] == 'yes' and m['parent_params']
              and ',' not in m['parent_params']]
    generic = [w for w in wanted if w.lower() in GENERIC_PARAMS]
    assert len(generic) > 50, 'the hazard this guards against should still exist'


def test_a_noun_qualified_parameter_still_finds_its_parent():
    """
    The guard must not undo the fix it came from: `eks.list_nodegroups` wants
    `clusterName`, the cluster's own id field is `name`, and only the
    convention connects them. Two real nodegroups depend on this.
    """
    import threading

    from providers.aws.runtime.collector import Collector

    col = Collector.__new__(Collector)
    col._lock = threading.Lock()
    col.catalog = {'eks.cluster': {'id_field': 'name', 'resource_name': 'Cluster'}}
    col.assets = [{
        'resource_key': 'eks.cluster', 'id': 'onam-eks-cluster',
        'name': 'onam-eks-cluster', 'asset_id': 'a-1', 'arn': '',
    }]
    col.assets_meta = {'eks.nodegroup': {'parent_params': 'clusterName'}}
    col.failures, col.barren = [], []
    col.workers = 1
    col.graph = None
    col.type_counts = __import__('collections').defaultdict(int)
    col.progress = False
    col._done = 0

    # Record the parameters the child pass resolves, without making a call.
    seen = {}

    def fake(key, params, pid):
        seen[key] = params
        return []

    col._collect_type = fake
    col._record_barren = lambda *a, **k: None

    from providers.aws.runtime.collector import PlannedCall
    col._collect_children([PlannedCall('eks.nodegroup', 'eks', 'list_nodegroups', {}, 'child')])
    assert seen.get('eks.nodegroup') == {'clusterName': 'onam-eks-cluster'}


def test_a_document_field_yields_the_resources_it_names():
    """
    A Step Functions definition is 20 KB of JSON with the resources it invokes
    buried inside it. A relation path can address the field; it cannot address
    what is written in the field, so a workflow's members were unreachable.

    The distinction that matters is the account number. Step Functions writes
    `arn:aws:states:::aws-sdk:ec2:runInstances` for an API CALL — no account,
    no resource — and a real ARN for a thing you own. The live estate's only
    state machine contains eleven ARNs and every one is an integration, so the
    honest answer there is that it orchestrates nothing collectable.
    """
    from providers.aws.runtime.resolver import arns_in

    definition = (
        '{"States":{"Scan":{"Resource":"arn:aws:states:::aws-sdk:ec2:runInstances"},'
        '"Fix":{"Resource":"arn:aws:lambda:ap-south-1:1:function:remediate"},'
        '"Tell":{"Resource":"arn:aws:sns:ap-south-1:1:topic/alerts"}}}'
    )
    assert arns_in(definition) == [
        'arn:aws:lambda:ap-south-1:1:function:remediate',
        'arn:aws:sns:ap-south-1:1:topic/alerts',
    ]

    # a workflow that only calls APIs names no members, and must not invent any
    only_calls = '{"Resource":"arn:aws:states:::aws-sdk:s3:getObject"}'
    assert arns_in(only_calls) == []
    assert arns_in(None) == []
    assert arns_in('no arns here') == []


def _child_probe(catalog, assets, meta, call):
    """
    Run one child pass without calling AWS, and report what it resolved.

    Returns (params_by_type, failures). A type that resolved nothing simply
    does not appear.
    """
    import collections
    import threading

    from providers.aws.runtime.collector import Collector, PlannedCall

    col = Collector.__new__(Collector)
    col._lock = threading.Lock()
    col.catalog = catalog
    col.assets = assets
    col.assets_meta = meta
    col.failures, col.barren = [], []
    col.workers = 1
    col.graph = None
    col.type_counts = collections.defaultdict(int)
    col.progress = False
    col._done = 0

    seen = collections.defaultdict(list)
    col._collect_type = lambda key, params, pid: seen[key].append(params) or []
    col._record_barren = lambda *a, **k: None
    col._collect_children([PlannedCall(*call)])
    return dict(seen), col.failures


def test_a_child_does_not_take_a_parent_from_another_service():
    """
    `ssm.list_document_versions` wants `Name`. So does half of AWS.

    Before the index carried the owning service, that call was handed the name
    of anything in the account that had one: 136 failures reading
    `Document with name AutoScalingManagedRule does not exist`, for documents
    SSM had never heard of. The same defect fed `fms.list_compliance_status`
    21-character ids where FMS wants 36.
    """
    catalog = {
        'ssm.document': {'id_field': 'Name', 'resource_name': 'Document', 'service': 'ssm'},
        'config.rule': {'id_field': 'Name', 'resource_name': 'Rule', 'service': 'config'},
    }
    assets = [
        {'resource_key': 'ssm.document', 'id': 'my-runbook', 'name': 'my-runbook',
         'asset_id': 'a-1', 'arn': ''},
        {'resource_key': 'config.rule', 'id': 'AutoScalingManagedRule',
         'name': 'AutoScalingManagedRule', 'asset_id': 'a-2', 'arn': ''},
    ]
    seen, _ = _child_probe(
        catalog, assets, {'ssm.document_version': {'parent_params': 'Name'}},
        ('ssm.document_version', 'ssm', 'list_document_versions', {}, 'child'))
    assert seen['ssm.document_version'] == [{'Name': 'my-runbook'}]


def test_an_ambiguous_parent_is_recorded_rather_than_guessed():
    """
    When no parent shares the child's service and several services offer the
    name, there is no evidence for choosing between them. Not attempting is the
    honest answer — and it is recorded, so the gap is visible rather than silent.
    """
    catalog = {
        'a.thing': {'id_field': 'WidgetId', 'resource_name': 'Thing', 'service': 'a'},
        'b.thing': {'id_field': 'WidgetId', 'resource_name': 'Thing', 'service': 'b'},
    }
    assets = [
        {'resource_key': 'a.thing', 'id': 'w-1', 'name': 'w-1', 'asset_id': 'a-1', 'arn': ''},
        {'resource_key': 'b.thing', 'id': 'w-2', 'name': 'w-2', 'asset_id': 'a-2', 'arn': ''},
    ]
    seen, failures = _child_probe(
        catalog, assets, {'c.widget': {'parent_params': 'WidgetId'}},
        ('c.widget', 'c', 'describe_widget', {}, 'child'))
    assert 'c.widget' not in seen
    assert [f['code'] for f in failures] == ['AmbiguousParent']


def test_a_cross_service_parent_still_resolves_when_only_one_service_offers_it():
    """
    The narrowing must not cut the legitimate cases: a Glacier vault is keyed on
    an `accountId` that nothing in `glacier` provides. One offering service is
    an unambiguous answer, so it is used.
    """
    catalog = {'organizations.account': {'id_field': 'accountId',
                                         'resource_name': 'Account',
                                         'service': 'organizations'}}
    assets = [{'resource_key': 'organizations.account', 'id': '123456789012',
               'name': 'prod', 'asset_id': 'a-1', 'arn': ''}]
    seen, _ = _child_probe(
        catalog, assets, {'glacier.vault': {'parent_params': 'accountId'}},
        ('glacier.vault', 'glacier', 'list_vaults', {}, 'child'))
    assert seen['glacier.vault'] == [{'accountId': '123456789012'}]


def test_a_bare_id_field_is_not_borrowed_across_services():
    """
    101 services declare an id_field of `Id`. `connect.traffic_distribution`
    asked for one and was handed every asset in the account.

    Scoping is what fixes this, not a ban on the name: `Id` is perfectly usable
    within the service that owns it. What is refused is `Id` taken from
    somewhere else.
    """
    catalog = {'apigateway.rest_api': {'id_field': 'Id', 'resource_name': 'RestApi',
                                       'service': 'apigateway'}}
    assets = [{'resource_key': 'apigateway.rest_api', 'id': 'abc123',
               'name': 'shop', 'asset_id': 'a-1', 'arn': ''}]
    seen, _ = _child_probe(
        catalog, assets, {'connect.traffic_distribution': {'parent_params': 'Id'}},
        ('connect.traffic_distribution', 'connect', 'get_traffic_distribution', {}, 'child'))
    assert 'connect.traffic_distribution' not in seen


@pytest.mark.parametrize('code,expected', [
    # The optional thing is not configured. Thirty spellings, one meaning.
    ('NoSuchBucketPolicy', 'absent'),
    ('RepositoryPolicyNotFoundException', 'absent'),
    ('NoSuchOriginAccessControl', 'absent'),
    ('LifecyclePolicyNotFoundException', 'absent'),
    ('NamespaceNotFound', 'absent'),
    ('InstanceNotRegisteredException', 'absent'),
    ('UnknownResourceFault', 'absent'),
    # The service is not switched on here.
    ('UninitializedAccountException', 'unused'),
    ('UnsupportedRegionException', 'unused'),
    ('TemplatesNotAvailableInRegionException', 'unused'),
    ('InvalidAccessException', 'unused'),
    ('OptInRequired', 'unused'),
    # Would likely succeed on another run.
    ('ThrottlingException', 'transient'),
    ('TooManyRequestsException', 'transient'),
    ('ConnectTimeoutError', 'transient'),
    ('InternalFailure', 'transient'),
    # Our permissions, not the estate.
    ('AccessDenied', 'denied'),
    ('UnauthorizedOperation', 'denied'),
    # The residue — the only bucket worth reading.
    ('ParamValidationError', 'error'),
    ('InvalidDocument', 'error'),
])
def test_a_failure_says_why_not_just_that(code, expected):
    """
    A run report reading "1056 failures" is a number nobody can act on. Split by
    reason, the same run leaves a residue small enough to read — and `error` is
    the only bucket that means something is wrong with US rather than with the
    estate.
    """
    from providers.aws.runtime.collector import classify_failure
    assert classify_failure(code) == expected


def test_denied_is_not_folded_into_unused():
    """
    Being refused a call is a fact about our permissions. A run whose coverage
    is limited by policy must say so rather than reporting the estate as empty.
    """
    from providers.aws.runtime.collector import classify_failure
    assert classify_failure('AccessDeniedException') == 'denied'
    assert classify_failure('SubscriptionRequiredException') == 'unused'


def test_no_collectable_call_omits_a_required_paging_parameter():
    """
    `cognito-identity.list_identity_pools` requires `MaxResults`. It was never
    declared, so the call failed parameter validation 110 times in one sweep —
    before reaching AWS, every time, for the life of the catalog.

    botocore knows what every operation requires, so the gap is checkable
    offline. Scoped to the paging knobs because those need no parent to
    satisfy: a required `MaxResults` has exactly one right answer and there is
    no reason for it ever to be missing. Parameters that need a real value —
    `resourceType`, `Status`, a filter — are a per-type decision and are
    tracked in docs/engine-improvements.md, not here.
    """
    import csv

    import boto3

    PAGING = {'MaxResults', 'maxResults', 'MaxItems', 'maxItems', 'Limit', 'limit', 'PageSize'}

    with open('providers/aws/catalog/asset_types.csv') as fh:
        meta = {r['key']: r for r in csv.DictReader(fh)}
    with open('providers/aws/catalog/resource_catalog.csv') as fh:
        catalog = {r['key']: r for r in csv.DictReader(fh)}

    session, models = boto3.Session(), {}

    def model(service):
        if service not in models:
            try:
                models[service] = session.client(
                    service, region_name='us-east-1').meta.service_model
            except Exception:                          # noqa: BLE001
                models[service] = None
        return models[service]

    missing = []
    for key, row in meta.items():
        if row.get('collect') != 'yes':
            continue
        entry = catalog.get(key)
        if not entry or not entry.get('operation'):
            continue
        service_model = model(entry['service'])
        if service_model is None:
            continue
        operation = ''.join(w.capitalize() for w in entry['operation'].split('_'))
        try:
            shape = service_model.operation_model(operation).input_shape
        except Exception:                              # noqa: BLE001
            continue
        required = set(getattr(shape, 'required_members', []) or []) & PAGING
        declared = {p.split('=')[0].strip()
                    for p in (row.get('required_args') or '').split(',')}
        if required - declared:
            missing.append((key, sorted(required - declared)))

    assert not missing, f'required paging parameters never declared: {missing}'


def test_one_arn_is_one_asset():
    """
    DocumentDB and Neptune are RDS-backed, so all three services list the same
    instance under the same ARN. Kept apart, the diagram drew three boxes in one
    subnet for one database while the database — keyed on the ARN — collapsed
    them and reported 149 fewer rows than the collector found.
    """
    from providers.aws.runtime.collector import dedupe_by_arn

    arn = 'arn:aws:rds:ap-south-1:1:db:pg-1'
    assets = [
        {'resource_key': 'docdb.db_instance', 'arn': arn, 'raw': dict.fromkeys('abcde')},
        {'resource_key': 'neptune.db_instance', 'arn': arn, 'raw': dict.fromkeys('abcdefgh')},
        {'resource_key': 'rds.db_instance', 'arn': arn, 'raw': dict.fromkeys('abcdefghijkl')},
    ]
    kept, merged = dedupe_by_arn(assets)
    assert len(kept) == 1
    assert kept[0]['resource_key'] == 'rds.db_instance', 'the ARN says rds'
    assert merged[0]['folded'] == ['docdb.db_instance', 'neptune.db_instance']


def test_the_owning_service_wins_over_the_richer_payload():
    """
    Rank order matters: AWS STATES the owner in the ARN, and a stated fact beats
    a heuristic. A fuller payload only breaks ties between types that both
    belong to the ARN's service.
    """
    from providers.aws.runtime.collector import dedupe_by_arn

    arn = 'arn:aws:rds:ap-south-1:1:db:pg-1'
    kept, _ = dedupe_by_arn([
        {'resource_key': 'neptune.db_instance', 'arn': arn, 'raw': dict.fromkeys(range(50))},
        {'resource_key': 'rds.db_instance', 'arn': arn, 'raw': {'a': 1}},
    ])
    assert kept[0]['resource_key'] == 'rds.db_instance'


def test_a_tie_is_broken_by_payload_then_name():
    """Two types from the ARN's own service — `iam.instance_profile` and
    `iam.instance_profiles_for_role` — need an answer that does not depend on
    which thread finished first."""
    from providers.aws.runtime.collector import dedupe_by_arn

    arn = 'arn:aws:iam::1:instance-profile/p'
    rich = {'resource_key': 'iam.instance_profiles_for_role', 'arn': arn,
            'raw': dict.fromkeys(range(9))}
    thin = {'resource_key': 'iam.instance_profile', 'arn': arn, 'raw': {'a': 1}}
    assert dedupe_by_arn([rich, thin])[0][0]['resource_key'] == \
        dedupe_by_arn([thin, rich])[0][0]['resource_key'] == 'iam.instance_profiles_for_role'


def test_an_asset_with_no_arn_is_never_merged():
    """Most of the estate has no ARN — a security group rule, a subnet group
    entry. Nothing to collide on, so nothing may be dropped."""
    from providers.aws.runtime.collector import dedupe_by_arn

    assets = [{'resource_key': 'ec2.security_group_rule', 'id': f'r-{i}', 'raw': {}}
              for i in range(5)]
    kept, merged = dedupe_by_arn(assets)
    assert len(kept) == 5 and not merged


def test_dedupe_reports_what_it_folded():
    """A count that quietly shrinks is the thing this fixes; the run report has
    to be able to say which ARNs merged and into what."""
    from providers.aws.runtime.collector import dedupe_by_arn

    arn = 'arn:aws:rds:ap-south-1:1:db:pg-1'
    _, merged = dedupe_by_arn([
        {'resource_key': 'rds.db_instance', 'arn': arn, 'raw': {}},
        {'resource_key': 'docdb.db_instance', 'arn': arn, 'raw': {}},
    ])
    assert merged == [{'arn': arn, 'kept': 'rds.db_instance',
                       'folded': ['docdb.db_instance']}]


# ── adopting the real ARN after enrichment ────────────────────────────
#
# A type can declare an `arn_field` its LIST call never returns. SQS is the
# case that exposed it: `list_queues` gives only a URL, so the ARN was
# constructed as `arn:aws:sqs:region:account:https://sqs.../my-queue` — not an
# ARN, yet used as the identity key and shown on the panel. The describe call
# returns the real one, and `_readdress` adopts it.

def _queue(arn):
    return {'asset_id': arn, 'arn': arn, 'arn_source': 'construct',
            'raw': {'QueueUrl': 'https://sqs.ap-south-1.amazonaws.com/1/q'}}


def test_a_constructed_arn_is_replaced_by_the_declared_field(collector):
    collector.catalog['sqs.queue'] = {'service': 'sqs', 'arn_field': 'QueueArn'}
    bad = 'arn:aws:sqs:ap-south-1:1:https://sqs.ap-south-1.amazonaws.com/1/q'
    asset = _queue(bad)
    asset['raw']['QueueArn'] = 'arn:aws:sqs:ap-south-1:1:q'

    collector._readdress('sqs.queue', asset)

    assert asset['arn'] == 'arn:aws:sqs:ap-south-1:1:q'
    assert asset['asset_id'] == 'arn:aws:sqs:ap-south-1:1:q'
    assert asset['arn_source'] == 'field'


def test_a_synthetic_asset_id_is_left_alone(collector):
    """
    Only an asset_id that WAS the ARN moves with it. A synthetic key was minted
    to be stable when no ARN existed, and children may already point at it.
    """
    collector.catalog['sqs.queue'] = {'service': 'sqs', 'arn_field': 'QueueArn'}
    asset = _queue(None)
    asset['asset_id'] = 'aws:sqs:ap-south-1:1:sqs.queue/q'
    asset['raw']['QueueArn'] = 'arn:aws:sqs:ap-south-1:1:q'

    collector._readdress('sqs.queue', asset)

    assert asset['arn'] == 'arn:aws:sqs:ap-south-1:1:q'
    assert asset['asset_id'] == 'aws:sqs:ap-south-1:1:sqs.queue/q'


def test_a_field_that_is_not_an_arn_is_ignored(collector):
    """Adopting a non-ARN would replace a wrong ARN with a worse one."""
    collector.catalog['sqs.queue'] = {'service': 'sqs', 'arn_field': 'QueueArn'}
    asset = _queue('arn:aws:sqs:ap-south-1:1:constructed')
    asset['raw']['QueueArn'] = 'just-a-name'

    collector._readdress('sqs.queue', asset)

    assert asset['arn'] == 'arn:aws:sqs:ap-south-1:1:constructed'
    assert asset['arn_source'] == 'construct'


def test_a_type_declaring_no_arn_field_is_untouched(collector):
    asset = _queue('arn:aws:ec2:ap-south-1:1:instance/i-1')
    asset['raw']['Arn'] = 'arn:aws:ec2:ap-south-1:1:something/else'

    collector._readdress('ec2.instance', asset)

    assert asset['arn'] == 'arn:aws:ec2:ap-south-1:1:instance/i-1'


# ── a bare `field[]` path ──────────────────────────────────────────────
#
# `attribute_container("subnets[]")` returns the whole path, so `leaf` is
# empty and the walk fell through `resolve_path(element, leaf) if leaf else []`
# — returning nothing. Every rule whose path ended in a bare `[]` scored zero
# hits and was written back as `absent`: a node group naming three subnets
# looked like it named none, and the catalog recorded the rule as unexercised
# rather than broken.

def test_a_list_of_plain_strings_yields_its_elements():
    from providers.aws.runtime.resolver import resolve_with_attributes

    out = resolve_with_attributes({'subnets': ['subnet-a', 'subnet-b']}, 'subnets[]')

    assert [v for v, _ in out] == ['subnet-a', 'subnet-b']


def test_siblings_still_ride_along_on_a_nested_path():
    """The reason `resolve_with_attributes` exists at all must survive."""
    from providers.aws.runtime.resolver import resolve_with_attributes

    out = resolve_with_attributes(
        {'Routes': [{'GatewayId': 'igw-1', 'DestinationCidrBlock': '0.0.0.0/0'}]},
        'Routes[].GatewayId')

    assert out == [('igw-1', {'DestinationCidrBlock': '0.0.0.0/0'})]


def test_a_list_of_dicts_is_not_read_as_scalars():
    from providers.aws.runtime.resolver import resolve_with_attributes

    assert resolve_with_attributes({'Routes': [{'GatewayId': 'igw-1'}]}, 'Routes[]') == []
