"""
Stage 1 — discover.

Collects raw resources from the provider. AWS uses the catalog-driven
collector (`providers/aws`): what to collect comes from the catalog's 1,404
primary types, and only `runtime/collector.py` ever calls AWS, read-only by
construction. Results land in `out/assets.json` (plus assets.csv,
collection.json, failures.json).

Other clouds run through their `DiscoveryScanner` implementations behind the
Discoveries API (`providers/common/api_server.py`) — that path needs the
Postgres/K8s runtime and is not driven from this local stage yet.
"""
import json
import logging
import os
import shutil
from types import SimpleNamespace

from cspm import paths

logger = logging.getLogger("pipeline.discover")

ASSETS_PATH = os.path.join(paths.OUT, "assets.json")
POLICY_EDGES_PATH = os.path.join(paths.OUT, "policy_edges.json")

def per_type_artifacts():
    """
    Artifacts that describe RESOURCES, keyed by the field naming each entry's
    type. A `--types` scan rewrites every one of them with only the types it
    collected, so every one needs the same merge.

    `collection.json` and `failures.json` are deliberately absent: they describe
    the RUN, not the estate, and merging a run report into an older one would
    produce a summary of a scan that never happened.

    Read at call time rather than frozen into a constant, so the paths follow
    the module globals instead of whatever they were at import.
    """
    return ((ASSETS_PATH, "resource_key"),
            (POLICY_EDGES_PATH, "target_key"))


def _merge_by_type(path, type_field, refreshed):
    """
    Carry forward the entries whose type this scan did not look at.

    Returns (carried, total) — or None if there was nothing to merge. The
    refreshed types are dropped from the prior file wholesale, so a type whose
    resources are gone loses them rather than keeping them for ever.
    """
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        fresh = json.load(fh)
    prior_path = f"{path}.prior"
    if not os.path.exists(prior_path):
        return None
    with open(prior_path) as fh:
        prior = json.load(fh)
    os.remove(prior_path)
    if not prior:
        return None

    seen = refreshed | {e.get(type_field) for e in fresh if e.get(type_field)}
    carried = [e for e in prior if e.get(type_field) not in seen]
    with open(path, "w") as fh:
        json.dump(carried + fresh, fh, indent=2, default=str)
    return len(carried), len(carried) + len(fresh)


def run(
    region: str,
    account: str = None,
    scope: str = "scenario",
    types: str = None,
    workers: int = 12,
    policies: str = "core",
    dry_run: bool = False,
    offline: bool = False,
    session=None,
) -> dict:
    """Collect raw AWS resources into out/assets.json.

    offline=True skips the API calls and reuses the last collection — every
    later stage re-runs for free against it.
    """
    if offline:
        if not os.path.exists(ASSETS_PATH):
            raise FileNotFoundError(
                f"{ASSETS_PATH} not found — run without --offline first"
            )
        with open(ASSETS_PATH) as fh:
            assets = json.load(fh)
        logger.info("discover (offline): reusing %d collected assets", len(assets))
        return {"mode": "offline", "assets": len(assets), "path": ASSETS_PATH}

    from providers.aws.cli import cmd_collect

    # A `--types` run collects a handful of types and writes them as the whole
    # artifact. The next stage reads that artifact as the estate and prunes
    # everything absent from it, so an unmerged targeted scan deletes the other
    # 136 types from the inventory. Snapshot every per-type artifact first; the
    # collect overwrites them all, and the merge afterwards puts the rest back.
    if types:
        for path, _ in per_type_artifacts():
            if os.path.exists(path):
                shutil.copyfile(path, f"{path}.prior")

    args = SimpleNamespace(
        region=region,
        account=account,
        account_name=None,
        scope=scope,
        types=types,
        workers=workers,
        policies=policies,
        dry_run=dry_run,
        # Whose account this scan reads. None means the ambient chain, which is
        # the single-tenant path; an onboarded account supplies a session built
        # by `credentials.session_for`.
        session=session,
    )
    rc = cmd_collect(args)
    if rc not in (0, None):
        raise RuntimeError(f"collect failed with exit code {rc}")
    if dry_run:
        return {"mode": "dry-run", "assets": 0, "path": None}

    with open(ASSETS_PATH) as fh:
        collected = len(json.load(fh))

    # Authority comes from what was ASKED, not from what came back. A scanned
    # type that returns nothing has genuinely lost its resources, and reading
    # the answer off the results would carry the stale rows forward for ever.
    refreshed = {t.strip() for t in str(types or "").split(",") if t.strip()}
    merged = 0
    for path, type_field in per_type_artifacts():
        result = _merge_by_type(path, type_field, refreshed)
        if result is None:
            continue
        carried, total = result
        logger.info(
            "discover: %s — carried %d entries of untouched types, %d total",
            os.path.basename(path), carried, total,
        )
        if path == ASSETS_PATH:
            merged = carried

    with open(ASSETS_PATH) as fh:
        assets = json.load(fh)
    logger.info("discover: collected %d assets", collected)
    return {
        "mode": "live", "assets": len(assets), "collected": collected,
        "carried": merged, "path": ASSETS_PATH,
    }
