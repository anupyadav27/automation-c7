"""
No resource may reference another and show no connection for it.

`scripts/check-panel-coverage.py` was a script you had to remember to run. As a
test it fails the build instead, which is the point of having written it: the
S3 self-edge bug survived for weeks precisely because a silent Connections
section and a correct empty one look identical, and nothing compared them.

Skipped when `out/assets.json` is absent, because a checkout that has never
scanned an account has nothing to be wrong about.
"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
SCRIPT = os.path.join(ROOT, 'scripts', 'check-panel-coverage.py')
ASSETS = os.path.join(ROOT, 'out', 'assets.json')


def _load():
    """Import the script by path — its name is not a module identifier."""
    spec = importlib.util.spec_from_file_location('panel_coverage', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['panel_coverage'] = module
    spec.loader.exec_module(module)
    return module


needs_estate = pytest.mark.skipif(
    not os.path.exists(ASSETS),
    reason='no collected estate; run the discover stage first')


@needs_estate
def test_every_reference_to_a_collected_resource_has_an_edge():
    """
    The one thing that is always a defect.

    Not "every type has every section" — a DynamoDB table encrypted with an
    AWS-owned key genuinely points at no KMS key, and saying so is the honest
    answer. This is narrower and absolute: a payload value that resolves to a
    resource we DID collect, with nothing connecting them, is a relation rule
    that is missing or broken.
    """
    module = _load()
    assert module.main(['--strict']) == 0, (
        'a resource names another collected resource with no edge between them '
        '— run `python3 scripts/check-panel-coverage.py` for the list. Either '
        'add the relation rule, or declare it in COLLISIONS with the reason it '
        'is a name collision rather than a reference.'
    )


@needs_estate
def test_the_collision_list_is_still_earning_its_place():
    """
    A declared collision that no longer occurs is a stale exemption.

    Each entry suppresses a real match on a judgement call. When the underlying
    data changes — a resource renamed, a type no longer collected — the entry
    silently starts hiding nothing, and the next person reads it as a rule that
    still applies.
    """
    module = _load()
    assets, edges = module.load()
    shapes = set()
    for asset in assets:
        for field, _ in module.scalars(asset.get('raw') or {}):
            shapes.add((asset['resource_key'], field))

    stale = [
        (src, field, tgt) for (src, field, tgt) in module.COLLISIONS
        if (src, field) not in shapes
    ]
    assert not stale, f'declared collisions that no longer occur: {stale}'
