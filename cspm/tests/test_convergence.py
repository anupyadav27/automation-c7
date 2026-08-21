"""
The two pipelines must agree on identity.

Discovery (AWS, catalog-driven) and the FinOps platform (AWS, hand-written
fetchers) scanned the same account independently. Where they saw the same
resource they must produce the same `resource_uid`, or every join between a
cost recommendation and a compliance finding silently misses.

Skips when either side has not been run, rather than passing vacuously.
"""
import json
import os

import pytest

from providers.aws.runtime import emit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DISCOVERY_ASSETS = os.path.join(REPO, 'out', 'assets.json')

# The FinOps platform's own scan of the same account, kept in-tree as a
# fixture. Nothing here reaches outside the repository.
FINOPS_ASSETS = os.path.join(REPO, 'out', 'samples', 'finops_assets.json')


def _load(path):
    if not os.path.exists(path):
        pytest.skip(f'no scan output at {path}')
    with open(path) as fh:
        data = json.load(fh)
    return data.get('assets', data) if isinstance(data, dict) else data


def test_the_same_resource_gets_the_same_uid_from_both_pipelines():
    ours, _ = emit.emit(_load(DISCOVERY_ASSETS))
    theirs = _load(FINOPS_ASSETS)

    by_name = {}
    for record in ours:
        if record['resource_type'] == 's3.bucket':
            by_name[record['name']] = record['resource_uid']

    compared = 0
    for asset in theirs:
        if asset.get('resource_type') != 's3.bucket':
            continue
        mine = by_name.get(asset.get('name'))
        if mine is None:
            continue                      # different region; nothing to compare
        compared += 1
        assert mine == asset['resource_uid'], (
            f"{asset['name']}: discovery says {mine!r}, "
            f"finops says {asset['resource_uid']!r}")

    assert compared, 'no overlapping resources found; the check proved nothing'


def test_every_emitted_record_is_valid():
    records, problems = emit.emit(_load(DISCOVERY_ASSETS))
    assert records, 'no assets to check'
    assert not problems, f'{len(problems)} invalid records, e.g. {problems[:3]}'
