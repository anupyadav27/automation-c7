"""
Every hand-written catalog key must name a type that actually exists.

This is the test that would have caught the worst bug in the project. Scoping
args for `ec2.image` and `ec2.snapshot` were written, reviewed and committed --
but the catalog calls those types `ec2.ami` and `ec2.ebs_snapshot`, so the args
matched nothing and both operations ran unscoped. A sweep that should have
returned a few hundred owned images returned 103,870 public ones, which in turn
made the child pass unrunnable. Nothing failed; the numbers were just wrong.

A key that does not resolve is always a silent no-op, so it must be a hard error.
"""
import csv
import os

import pytest

CATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'catalog')


def _keys(filename, column):
    path = os.path.join(CATALOG, filename)
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [(r[column], filename) for r in csv.DictReader(fh) if r.get(column)]


def _catalog_keys():
    with open(os.path.join(CATALOG, 'resource_catalog.csv')) as fh:
        return {r['key'] for r in csv.DictReader(fh)}


REFERENCES = (_keys('collection_args.csv', 'resource_key')
              + _keys('collection_filters.csv', 'resource_key')
              + _keys('non_asset_types.csv', 'resource_key'))


def test_there_are_references_to_check():
    assert REFERENCES, 'no hand-written keys found; the guard would pass vacuously'


@pytest.mark.parametrize('key,source', REFERENCES, ids=[f'{s}:{k}' for k, s in REFERENCES])
def test_key_exists_in_catalog(key, source):
    assert key in _catalog_keys(), (
        f'{source} references "{key}", which is not a resource_catalog key. '
        f'The rule silently does nothing.')


def test_snake_case_agrees_with_boto3():
    """The catalog's operation names must be the ones boto3 actually exposes.

    A hand-rolled PascalCase->snake_case regex turned ListWebACLs into
    list_web_ac_ls. boto3 has no such method, so botocore raised KeyError and
    every WAF web ACL in the account was silently uncollectable.
    """
    from providers.aws.runtime.collector import _snake
    assert _snake('ListWebACLs') == 'list_web_acls'
    assert _snake('DescribeACLs') == 'describe_acls'
    assert _snake('DescribeInstances') == 'describe_instances'


def test_no_primary_type_is_unreachable_with_this_sdk():
    """Every primary type must be callable, or it is a guaranteed failure."""
    boto3 = pytest.importorskip('boto3')
    session = boto3.Session()
    services = set(session.get_available_services())
    with open(os.path.join(CATALOG, 'resource_catalog.csv')) as fh:
        primary = [r for r in csv.DictReader(fh) if r['tier'] == 'primary']
    unreachable = [r['key'] for r in primary if r['service'] not in services]
    assert not unreachable, (
        f'{len(unreachable)} primary types name a service boto3 does not have, '
        f'e.g. {unreachable[:5]}')


# ══════════════════════════════════════════════════════════════════════
# catalog hygiene — the classes of defect that hid real resources
# ══════════════════════════════════════════════════════════════════════

def _catalog():
    import csv
    with open('providers/aws/catalog/resource_catalog.csv') as fh:
        return list(csv.DictReader(fh))


def test_no_two_collectable_types_share_a_call_and_a_response_path():
    """
    Two keys, one AWS call, one response path is a duplicate: only one can win
    and the other reports zero, indistinguishably from a service that owns
    nothing. 18 such pairs existed - `eks.nodegroup` / `eks.eks_nodegroup` and
    friends.

    Sharing a CALL is fine and must stay fine: `describe_alarms` returns
    MetricAlarms and CompositeAlarms, which is two resources from one request.
    It is sharing the PATH as well that makes them the same thing twice.
    """
    import csv
    from collections import defaultdict

    with open('providers/aws/catalog/asset_types.csv') as fh:
        meta = {r['key']: r for r in csv.DictReader(fh)}

    seen = defaultdict(list)
    for row in _catalog():
        if meta.get(row['key'], {}).get('collect') != 'yes' or not row['operation']:
            continue
        seen[(row['service'], row['operation'], row['items_for'])].append(row['key'])

    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, f'same call AND same path: {dupes}'


def test_no_key_was_singularised_by_chopping_a_letter():
    """
    `event_bus` became `event_bu` and `..._status` became `..._statu` — 77 keys
    mangled by a de-pluraliser that stripped a trailing `s` from words that
    were never plural. Four of them were phantom duplicates of the correctly
    spelled key sitting right beside them.
    """
    import re

    bad = re.compile(r'[_.](bu|statu|addres|acces|proces|clas|analysi|'
                     r'busines|succes|alia)$')
    hits = sorted(r['key'] for r in _catalog() if bad.search(r['key']))
    assert not hits, f'over-singularised keys: {hits}'


def test_a_constructed_arn_is_not_read_from_a_field():
    """
    `ec2.security_group_rule` declared `arn_field: SecurityGroupRuleArn`, and
    AWS returns no such field — it returns `SecurityGroupRuleId`. 228 real
    rules extracted, built no asset, and disappeared without a failure.
    """
    row = next(r for r in _catalog() if r['key'] == 'ec2.security_group_rule')
    assert row['id_field'] == 'SecurityGroupRuleId'
    assert row['arn_strategy'] == 'construct'
    assert not row['arn_field'], 'nothing to read it from — it has to be built'


def test_every_identity_recipe_names_a_field_the_api_returns():
    """
    Eighteen types extracted real items and built no asset, because each named
    a field AWS does not return: `athena.data_catalog` read `Name` from a
    payload with `CatalogName`, `xray.sampling_rule` read `RuleName` from a
    payload that wraps it in `SamplingRule`. Each failed silently.

    These are the eighteen, pinned by the field the API actually returns. A
    change that reverts one of them fails here rather than in six weeks when
    somebody asks where their IAM access keys went.
    """
    known = {
        'athena.data_catalog': 'CatalogName',
        'config.delivery_channel': 'name',
        'dax.parameter_group': 'ParameterGroupName',
        'directconnect.direct_connect_gateway': 'directConnectGatewayId',
        'ec2.traffic_mirror_filter': 'TrafficMirrorFilterId',
        'ec2.security_group_rule': 'SecurityGroupRuleId',
        'iam.access_key': 'AccessKeyId',
        'iot.certificate': 'certificateId',
        'ivs.channel': 'arn',
        'ivschat.room': 'id',
        'memorydb.user': 'Name',
        'networkmanager.global_network': 'GlobalNetworkId',
        'securityhub.standard': 'StandardsArn',
        'ssm.patch_baseline': 'BaselineId',
        # Nested: the API wraps the resource, so a flat lookup finds nothing.
        'xray.sampling_rule': 'SamplingRule.RuleName',
    }
    rows = {r['key']: r for r in _catalog()}
    for key, field in known.items():
        assert rows[key]['id_field'] == field, \
            f'{key} reads {rows[key]["id_field"]!r}; AWS returns {field!r}'


def test_a_type_agrees_with_the_type_its_name_extends():
    """
    `ec2.security_group_rule` is `ec2.security_group` plus a suffix, so it is a
    detail of that thing and belongs in the same domain. It inherited the `ec2`
    service default instead and 228 firewall rules were filed under
    `compute.instances` — 21% of a real estate in the wrong place, with nothing
    to notice because the grid is emergent and nobody reviews it.

    This is that review, as a test. Keyed on the NAME rather than the service:
    "some sibling was named explicitly" flags every RDS type the moment one
    security group is named, and misses this case entirely, because
    `compute.instances` is itself explicitly stated for `ec2.instance`.
    """
    import subprocess
    import sys
    import os

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    out = subprocess.run(
        [sys.executable, os.path.join(root, 'scripts', 'aws-grid.py'), '--json'],
        capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr[:400]

    import json
    conflicts = json.loads(out.stdout)['sibling_conflicts']
    assert not conflicts, (
        'these types disagree with the type their name extends:\n' +
        '\n'.join(f'  {k} got {got}, but {parent[0]} {parent[1]}'
                  for k, got, parent in conflicts[:10]))


def test_every_collectable_type_resolves_to_a_kind_and_a_domain():
    """
    2,241 of 3,073 collectable types had no classification at all — no role, so
    no kind, or a role and no domain. Each would have landed in the `unplaced`
    band the day a customer's account produced it: loud, which is the right
    default, but not an answer.

    Concentrated in services nobody had bound — IoT 69, Connect 63, DataZone 48
    — so this was never going to be found by looking at one estate. It took
    resolving the whole catalog offline.
    """
    import subprocess
    import sys
    import os
    import json

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    out = subprocess.run(
        [sys.executable, os.path.join(root, 'scripts', 'aws-grid.py'), '--json'],
        capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr[:400]

    gaps = json.loads(out.stdout)['gaps']
    assert not gaps, (
        f'{len(gaps)} collectable types resolve to nothing:\n' +
        '\n'.join(f'  {k}: {why}' for k, why, _ in gaps[:12]))


def _catalog_grid():
    import subprocess
    import sys
    import os
    import json

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    out = subprocess.run(
        [sys.executable, os.path.join(root, 'scripts', 'aws-grid.py'), '--json'],
        capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr[:400]
    return json.loads(out.stdout)


def test_no_subcategory_swallows_the_catalog():
    """
    `integration.messaging` held 312 of 3,070 types — a contact centre, an email
    service and a document store filed as messaging infrastructure, because 320
    services were classified in bulk into twelve categories that are all
    infrastructure primitives. A filter on "integration" that returns a contact
    centre has failed at the one job the domain axis has.

    Ten percent is the line. It is arbitrary in the way a speed limit is
    arbitrary: the exact number matters less than there being one, and 312 was
    ten points over it.
    """
    grid = _catalog_grid()['grid']
    total = sum(sum(c.values()) for c in grid.values())
    fat = {d: sum(c.values()) for d, c in grid.items()
           if sum(c.values()) > total * 0.10}
    assert not fat, (
        'these subcategories hold more than 10% of the catalog and are probably '
        f'doing several jobs: { {d: f"{n} ({n * 100 // total}%)" for d, n in fat.items()} }')


def test_edge_compute_is_where_your_code_runs():
    """
    211 of `compute.edge`'s 262 types were the IoT *platform* — a device
    registry, digital twins, industrial data — not code running on a device.

    The line is whether the service executes YOUR code somewhere else.
    Greengrass and Panorama do. IoT Core is a platform you talk to.
    """
    rows = {r['key']: r for r in _catalog_grid()['rows']}
    for key in ('greengrass.core_definition', 'greengrassv2.component'):
        assert rows[key]['domain'] == 'compute.edge', key
    for key in ('iot.thing', 'iotsitewise.asset', 'iottwinmaker.component_type'):
        if key in rows:
            assert rows[key]['domain'] == 'application.devices', key


def test_no_service_is_spelled_two_ways():
    """
    44 services appeared twice, differing only in hyphenation —
    `bedrock-agentcore` and `bedrockagentcore`, `acmpca` and `acm-pca`. Each
    pair split one product into two groups and two sets of types.

    boto3 settles it, not type count: the collector builds a client from this
    name, so a spelling boto3 does not have can never collect whatever it is
    credited with. That criterion disagreed with "keep the heavier side" twice —
    `acmpca` carried five types to `acm-pca`'s one, and boto3 has only the
    latter.
    """
    import csv
    import collections

    with open('providers/aws/catalog/resource_catalog.csv') as fh:
        services = {r['key'].split('.')[0] for r in csv.DictReader(fh) if '.' in r['key']}

    seen = collections.defaultdict(list)
    for s in services:
        seen[s.replace('-', '')].append(s)
    dupes = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    assert not dupes, f'the same service spelled two ways: {dupes}'


def test_detail_fields_declares_each_field_once():
    """
    One raw path, one label.

    `detail_fields.csv` was merged from two lists that had drifted apart — a
    hardcoded RAW_FIELDS in emit.py driving `inventory_assets.metadata`, and
    this CSV driving the detail panel. The merge produced `ec2.volume.Size`
    under two names, `size_gb` and `size_gib`, which would have written the
    same number into two metadata keys and shown it twice in a panel.
    """
    import collections
    import csv
    import os

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    path = os.path.join(root, 'providers', 'aws', 'catalog', 'detail_fields.csv')
    with open(path, newline='') as fh:
        rows = [r for r in csv.DictReader(fh) if r.get('resource_key')]

    by_path = collections.Counter((r['resource_key'], r['field']) for r in rows)
    assert not [k for k, n in by_path.items() if n > 1], \
        f'one raw path under two labels: {[k for k, n in by_path.items() if n > 1]}'

    by_label = collections.Counter((r['resource_key'], r['label']) for r in rows)
    assert not [k for k, n in by_label.items() if n > 1], \
        f'one label from two raw paths: {[k for k, n in by_label.items() if n > 1]}'


def test_every_detail_field_declares_a_known_type():
    """A type the coercer does not know silently falls back to string, so a
    number lands in the database as text and every numeric rule misses it."""
    import csv
    import os

    from providers.aws.runtime.emit import _COERCE

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    path = os.path.join(root, 'providers', 'aws', 'catalog', 'detail_fields.csv')
    with open(path, newline='') as fh:
        rows = [r for r in csv.DictReader(fh) if r.get('resource_key')]

    unknown = sorted({r.get('type', '') for r in rows} - set(_COERCE))
    assert not unknown, f'detail_fields declares types the coercer lacks: {unknown}'


def test_every_field_names_a_source_that_exists():
    """
    A field declares where it comes from, and `enrich:<operation>` must name a
    call that `enrich_specs.csv` actually makes for that same type.

    This is the link that stops the two files drifting. A field claiming an
    enrich call nobody makes is a column that will always be empty; an enrich
    call no field wants is an N+1 sweep for nothing. Both were possible before
    the `source` column existed, and one of them — S3 encryption — is exactly
    the gap that made the detail panel undeliverable.
    """
    import csv
    import os

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    cat = os.path.join(root, 'providers', 'aws', 'catalog')

    with open(os.path.join(cat, 'detail_fields.csv'), newline='') as fh:
        fields = [r for r in csv.DictReader(fh) if r.get('resource_key')]
    with open(os.path.join(cat, 'enrich_specs.csv'), newline='') as fh:
        specs = {(r['resource_key'], r['operation'])
                 for r in csv.DictReader(fh) if r.get('resource_key')}

    # `enrich:metrics` is CloudWatch, not a per-type describe — it has no spec
    # row by design, because one call serves every type that wants a metric.
    missing = []
    for row in fields:
        source = (row.get('source') or 'list').strip()
        if not source.startswith('enrich:') or source == 'enrich:metrics':
            continue
        operation = source.split(':', 1)[1]
        if (row['resource_key'], operation) not in specs:
            missing.append(f"{row['resource_key']}.{row['label']} -> {source}")
    assert not missing, f'fields naming an enrich call nobody makes: {missing}'


def test_every_enrich_call_is_wanted_by_some_field():
    """The other direction: an N+1 sweep nobody reads is pure cost."""
    import csv
    import os

    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    cat = os.path.join(root, 'providers', 'aws', 'catalog')

    with open(os.path.join(cat, 'detail_fields.csv'), newline='') as fh:
        wanted = {(r['resource_key'], (r.get('source') or '').replace('enrich:', ''))
                  for r in csv.DictReader(fh) if r.get('resource_key')}
    with open(os.path.join(cat, 'enrich_specs.csv'), newline='') as fh:
        specs = [r for r in csv.DictReader(fh) if r.get('resource_key')]

    # A spec may exist to produce an EDGE rather than a column — an EKS
    # nodegroup's autoScalingGroups, a state machine's definition — so those
    # are named here rather than silently exempted.
    FOR_EDGES = {('ecs.service', 'describe_services'),
                 ('stepfunctions.state_machine', 'describe_state_machine')}
    orphans = [f"{s['resource_key']}.{s['operation']}" for s in specs
               if (s['resource_key'], s['operation']) not in wanted
               and (s['resource_key'], s['operation']) not in FOR_EDGES]
    assert not orphans, f'enrich calls nothing asks for: {orphans}'
