"""
Stage 2 — build assets.

Turns the raw collector output into canonical `cspm_asset.v2` records — the
contract every engine reads. Also writes the narrowed v1 view, which is what
the FinOps engine's Pydantic model accepts (topology dropped, so cost rules
never silently match on positional keys).

Artifacts:
    out/cspm/assets.v2.json   canonical records (validated)
    out/cspm/assets.v1.json   v1 view for the FinOps engine

In the cluster deployment this stage is the Inventory Engine
(`inventory.api.orchestrator.ScanOrchestrator`), which additionally persists
assets, relationships and drift to Postgres. The file path here and the DB
path there emit the same schema — that identity is what
`cspm/tests/test_convergence.py` checks.
"""
import json
import logging
import os

from cspm import paths, schema

from .discover import ASSETS_PATH

logger = logging.getLogger("pipeline.assets")

CSPM_DIR = os.path.join(paths.OUT, "cspm")
V2_PATH = os.path.join(CSPM_DIR, "assets.v2.json")
V1_PATH = os.path.join(CSPM_DIR, "assets.v1.json")


EDGES_PATH = os.path.join(paths.OUT, "edges.csv")


def _build_edges(raw_assets, tenant_id, scan_run_id):
    """
    Derive the edge graph and write it where stage 3 reads it.

    Returns the edge rows so the caller can persist them. Failure is logged and
    swallowed for the same reason the DB block swallows: an estate with no
    edges is a worse diagram, not a broken pipeline.
    """
    try:
        from providers.aws.cli import _write_csv
        from providers.aws.validate.live import validate

        policy_path = os.path.join(paths.OUT, "policy_edges.json")
        policy_edges = []
        if os.path.exists(policy_path):
            with open(policy_path) as fh:
                policy_edges = json.load(fh)

        edges, report = validate(raw_assets, write_back=True,
                                 policy_edges=policy_edges)
        _write_csv(EDGES_PATH, edges)
        logger.info("build_assets: %d edges (%d duplicates collapsed)",
                    len(edges), report.get("edges_collapsed", 0))
        return edges
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("edge build skipped: %s", exc)
        return []


def run(tenant_id: str = "local", scan_run_id: str = "", keep_raw: bool = False) -> dict:
    """Normalise out/assets.json into canonical cspm asset records."""
    if not os.path.exists(ASSETS_PATH):
        raise FileNotFoundError(f"{ASSETS_PATH} not found — run the discover stage first")

    from providers.aws.runtime.emit import emit

    with open(ASSETS_PATH) as fh:
        raw_assets = json.load(fh)

    records, problems = emit(raw_assets, tenant_id=tenant_id, scan_run_id=scan_run_id,
                             keep_raw=keep_raw, validate=True)
    v1_records = [schema.to_v1(r) for r in records]

    os.makedirs(CSPM_DIR, exist_ok=True)
    with open(V2_PATH, "w") as fh:
        json.dump(records, fh, default=str)
    with open(V1_PATH, "w") as fh:
        json.dump({"assets": v1_records}, fh, default=str)

    for problem in problems[:10]:
        logger.warning("invalid record %s: %s",
                       problem["resource_uid"], problem["problem"])
    if len(problems) > 10:
        logger.warning("… and %d more validation problems", len(problems) - 10)

    # ── edges ─────────────────────────────────────────────────────────
    #
    # Derived here because they are derived FROM assets: a relation rule reads
    # one asset's payload and names another. They used to be produced only by
    # `providers.aws.cli validate`, run by hand, while stage 3 read the CSV it
    # left behind — so `pipeline all` re-scanned the account, rebuilt every
    # asset, and drew the diagram over whatever edges happened to be on disk.
    edges = _build_edges(raw_assets, tenant_id, scan_run_id)

    # DB twin of the artifacts (postgres backend only; no-op in files mode)
    upserted = 0
    try:
        from datetime import datetime, timezone

        from store import inventory as store_inventory

        db_rows = []
        for record in records:
            row = {k: v for k, v in record.items()
                   if k not in ("schema_version", "scan_run_id")}
            row["tenant_id"] = row.get("tenant_id") or tenant_id or "local"
            db_rows.append(row)
        if db_rows:
            # drift first: the upsert overwrites the state it compares against
            drift = store_inventory.detect_drift(
                db_rows, scan_run_id or "adhoc",
                tenant_id=tenant_id or "local")
            if drift:
                logger.info("build_assets: drift %s", drift)
            upserted = store_inventory.upsert_assets(
                db_rows, scan_run_id or "adhoc", datetime.now(timezone.utc))
            if upserted:
                logger.info("build_assets: %d assets upserted to DB", upserted)
            pruned = store_inventory.prune_stale(
                scan_run_id or "", tenant_id=tenant_id or "local")
            if pruned:
                logger.info("build_assets: %d stale assets pruned", pruned)

        # Edges after assets, and pruned on the same rule: the graph answers
        # "what is connected now", so an edge whose rule stopped firing has no
        # row. Without the prune the table only ever grows.
        if edges:
            from store import edges as store_edges

            written = store_edges.upsert_edges(
                edges, scan_run_id or "adhoc", datetime.now(timezone.utc),
                tenant_id=tenant_id or "local")
            if written:
                logger.info("build_assets: %d edges upserted to DB", written)
            dropped = store_edges.prune_stale(
                scan_run_id or "", tenant_id=tenant_id or "local")
            if dropped:
                logger.info("build_assets: %d stale edges pruned", dropped)
    except Exception as exc:
        logger.warning("asset DB upsert skipped: %s", exc)

    logger.info("build_assets: %d raw → %d canonical records (%d problems)",
                len(raw_assets), len(records), len(problems))
    return {
        "raw": len(raw_assets),
        "canonical": len(records),
        "edges": len(edges),
        "validation_problems": len(problems),
        "v2_path": V2_PATH,
        "v1_path": V1_PATH,
        "edges_path": EDGES_PATH,
    }
