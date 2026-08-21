"""
A targeted `--types` scan must not be mistaken for the whole estate.

`discover` writes one artifact and `build_assets` treats that artifact as the
complete picture, pruning any asset missing from it. So a scan of three types
used to leave `out/assets.json` holding three assets, and the next stage
deleted the other 1,033 rows from the inventory. That is not hypothetical — it
happened, and the estate went from 564 rows to 62.

The fix is that a partial scan merges. These tests pin the merge rule: types
named in the scan are replaced wholesale, types not named are carried through.
"""
import json
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from orchestration.stages import discover


def _asset(rtype, ident):
    return {"resource_key": rtype, "id": ident, "arn": f"arn::{rtype}:{ident}"}


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    """Redirect the stage at a temp artifact and fake the collector."""
    path = tmp_path / "assets.json"
    monkeypatch.setattr(discover, "ASSETS_PATH", str(path))
    monkeypatch.setattr(discover, "POLICY_EDGES_PATH", str(tmp_path / "policy.json"))

    def run_scan(prior, collected, types=None):
        """`types` is what the scan ASKED for — it defaults to what came back,
        but a test can name a type that returned nothing."""
        path.write_text(json.dumps(prior))

        def fake_collect(args):
            path.write_text(json.dumps(collected))
            return 0

        asked = types or ",".join(sorted({a["resource_key"] for a in collected}))
        with mock.patch("providers.aws.cli.cmd_collect", fake_collect):
            return discover.run(region="ap-south-1", types=asked, offline=False)

    return SimpleNamespace(path=path, run=run_scan,
                           read=lambda: json.loads(path.read_text()))


def test_untouched_types_survive_a_targeted_scan(artifact):
    prior = [_asset("ec2.instance", "i-1"), _asset("s3.bucket", "b1")]
    result = artifact.run(prior, [_asset("sns.topic", "t1")])

    kinds = {a["resource_key"] for a in artifact.read()}
    assert kinds == {"ec2.instance", "s3.bucket", "sns.topic"}
    assert result["carried"] == 2
    assert result["collected"] == 1
    assert result["assets"] == 3


def test_a_rescanned_type_is_replaced_not_appended(artifact):
    """Rescanning sns.topic must not leave the old topics behind beside the new."""
    prior = [_asset("sns.topic", "old-1"), _asset("sns.topic", "old-2"),
             _asset("ec2.instance", "i-1")]
    artifact.run(prior, [_asset("sns.topic", "new-1")])

    topics = [a["id"] for a in artifact.read() if a["resource_key"] == "sns.topic"]
    assert topics == ["new-1"]


def test_a_type_whose_resources_are_gone_loses_them(artifact):
    """
    The collector returning nothing for a scanned type is a real answer: those
    resources are gone. It must not be read as 'no information'.
    """
    prior = [_asset("sns.topic", "old-1"), _asset("ec2.instance", "i-1")]
    artifact.run(prior, [_asset("ec2.instance", "i-1")],
                 types="sns.topic,ec2.instance")

    assert {a["resource_key"] for a in artifact.read()} == {"ec2.instance"}


def test_a_full_scope_scan_replaces_everything(artifact, tmp_path, monkeypatch):
    """
    Only `--types` merges. A `--scope all` run IS the whole estate, and merging
    into it would resurrect resources that no longer exist.
    """
    artifact.path.write_text(json.dumps([_asset("sns.topic", "stale")]))
    fresh = [_asset("ec2.instance", "i-1")]

    def fake_collect(args):
        artifact.path.write_text(json.dumps(fresh))
        return 0

    with mock.patch("providers.aws.cli.cmd_collect", fake_collect):
        result = discover.run(region="ap-south-1", scope="all", types=None)

    assert {a["resource_key"] for a in artifact.read()} == {"ec2.instance"}
    assert result["assets"] == 1


def test_a_targeted_scan_with_no_prior_artifact_is_not_an_error(artifact, tmp_path):
    """First run on a clean checkout: nothing to merge, and that is fine."""
    fresh = [_asset("sns.topic", "t1")]

    def fake_collect(args):
        artifact.path.write_text(json.dumps(fresh))
        return 0

    assert not os.path.exists(artifact.path)
    with mock.patch("providers.aws.cli.cmd_collect", fake_collect):
        result = discover.run(region="ap-south-1", types="sns.topic")

    assert result["assets"] == 1
    assert result["carried"] == 0


def test_policy_edges_merge_too(tmp_path, monkeypatch):
    """
    `assets.json` is not the only per-type artifact. `policy_edges.json` holds
    the bucket-policy and topic-policy edges, keyed by the type that HOLDS the
    policy — and a targeted scan of three types once cut it from 33 edges to 1,
    silently deleting every S3 `accessible-by` edge from the graph.
    """
    assets = tmp_path / "assets.json"
    policy = tmp_path / "policy.json"
    monkeypatch.setattr(discover, "ASSETS_PATH", str(assets))
    monkeypatch.setattr(discover, "POLICY_EDGES_PATH", str(policy))

    assets.write_text(json.dumps([_asset("s3.bucket", "b1")]))
    policy.write_text(json.dumps([
        {"target_key": "s3.bucket", "target_id": "b1", "edge_type": "accessible-by"},
        {"target_key": "s3.bucket", "target_id": "b2", "edge_type": "accessible-by"},
        {"target_key": "sns.topic", "target_id": "t-old", "edge_type": "accessible-by"},
    ]))

    def fake_collect(args):
        assets.write_text(json.dumps([_asset("sns.topic", "t1")]))
        policy.write_text(json.dumps([
            {"target_key": "sns.topic", "target_id": "t1", "edge_type": "accessible-by"},
        ]))
        return 0

    with mock.patch("providers.aws.cli.cmd_collect", fake_collect):
        discover.run(region="ap-south-1", types="sns.topic")

    edges = json.loads(policy.read_text())
    # Both S3 edges survive; the stale sns one is replaced by the fresh one.
    assert sorted(e["target_id"] for e in edges) == ["b1", "b2", "t1"]
