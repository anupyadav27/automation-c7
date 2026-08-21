"""store.inventory — assets, the estate's system of record."""
from . import get_backend, is_postgres

_SORTABLE = {"name", "resource_type", "provider", "account_id", "region",
             "last_seen_at", "monthly_cost_usd"}
_FILTERS = {"provider", "account_id", "region", "resource_type", "tenant_id", "scope"}


def list_assets(limit=50, offset=0, sort=None, **filters):
    """Returns (rows, total) in cspm_asset shape + audit fields."""
    backend = get_backend()
    filters = {k: v for k, v in filters.items() if k in _FILTERS and v}
    if is_postgres():
        where, params = ["1=1"], []
        for key, value in filters.items():
            where.append(f"{key} = %s")
            params.append(value)
        order = "last_seen_at DESC NULLS LAST"
        if sort:
            field, _, direction = sort.partition(":")
            if field in _SORTABLE:
                order = f"{field} {'DESC' if direction == 'desc' else 'ASC'}"
        total = backend.query_one(
            f"SELECT count(*) AS n FROM inventory_assets WHERE {' AND '.join(where)}",
            params)["n"]
        rows = backend.query(
            f"SELECT * FROM inventory_assets WHERE {' AND '.join(where)} "
            f"ORDER BY {order} LIMIT %s OFFSET %s", params + [limit, offset])
        return rows, total

    data = backend.read("assets_v1", default={"assets": []})
    assets = data.get("assets", data) if isinstance(data, dict) else data
    rows = [a for a in assets if backend.match(a, **filters)]
    return backend.paginate(rows, limit, offset, sort)


def with_rollups(assets):
    """Attach finding counts and cost to assets — the Assets table's
    `Findings` and `Cost /mo` columns. One aggregate pass, not N queries."""
    if not assets:
        return assets
    backend = get_backend()
    counts, costs = {}, {}

    if is_postgres():
        rows = backend.query(
            """SELECT resource_uid, severity, count(*) AS n
               FROM posture_findings WHERE status = 'open'
               GROUP BY resource_uid, severity""")
        for row in rows:
            counts.setdefault(row["resource_uid"], {})[row["severity"]] = row["n"]
        for row in backend.query(
                """SELECT resource_uid,
                          sum(coalesce(savings_max_usd, 0)) AS savings
                   FROM finops_recommendations WHERE status = 'open'
                   GROUP BY resource_uid"""):
            costs[row["resource_uid"]] = float(row["savings"] or 0)
    else:
        doc = backend.read("findings", default={"findings": []})
        for f in (doc.get("findings", doc) if isinstance(doc, dict) else doc):
            uid = f.get("arn") or f.get("resource_uid")
            if uid:
                counts.setdefault(uid, {})[f.get("severity", "info")] = \
                    counts.setdefault(uid, {}).get(f.get("severity", "info"), 0) + 1
        doc = backend.read("recommendations", default={})
        for r in (doc.get("recommendations", []) if isinstance(doc, dict) else doc):
            uid = r.get("resource_uid")
            savings = (r.get("estimated_monthly_savings_usd") or {}).get("max")
            if uid and savings:
                costs[uid] = costs.get(uid, 0) + float(savings)

    for asset in assets:
        uid = asset.get("resource_uid")
        asset["finding_counts"] = counts.get(uid, {})
        asset["savings_usd"] = costs.get(uid)
    return assets


def get_asset(resource_uid, tenant_id=None):
    backend = get_backend()
    if is_postgres():
        return backend.query_one(
            "SELECT * FROM inventory_assets WHERE resource_uid = %s"
            + (" AND tenant_id = %s" if tenant_id else ""),
            [resource_uid] + ([tenant_id] if tenant_id else []))
    data = backend.read("assets_v1", default={"assets": []})
    assets = data.get("assets", data) if isinstance(data, dict) else data
    return next((a for a in assets if a.get("resource_uid") == resource_uid), None)


def list_drift(limit=50, offset=0, **filters):
    """Drift events between consecutive scans."""
    backend = get_backend()
    if is_postgres():
        total = backend.query_one(
            "SELECT count(*) AS n FROM inventory_drift_events")["n"]
        rows = backend.query(
            "SELECT * FROM inventory_drift_events ORDER BY detected_at DESC "
            "LIMIT %s OFFSET %s", [limit, offset])
        return rows, total
    return [], 0


# Fields that describe the resource. Scan bookkeeping is excluded on purpose:
# including it would report every re-scan as a change.
_IDENTITY = ("name", "region", "scope", "resource_type", "tags",
             "metadata", "topology", "hash_sha256")


def detect_drift(new_assets, scan_run_id, tenant_id="local"):
    """Compare this scan's assets with what the DB holds and record the delta.

    Runs before the upsert — afterwards the previous state is gone. Returns
    counts by change type; a first scan produces nothing, which is correct:
    drift needs two points.
    """
    import json
    import uuid

    if not is_postgres():
        return {}
    backend = get_backend()

    previous = {
        row["resource_uid"]: row for row in backend.query(
            "SELECT resource_uid, provider, resource_type, name, region, scope,"
            "       tags, metadata, topology, hash_sha256, last_seen_scan_id"
            "  FROM inventory_assets WHERE tenant_id = %s", [tenant_id])
    }
    if not previous:
        return {}

    prev_scan = next(iter(previous.values())).get("last_seen_scan_id")
    current = {a["resource_uid"]: a for a in new_assets}
    events, counts = [], {}

    def record(uid, asset, change_type, summary=None):
        counts[change_type] = counts.get(change_type, 0) + 1
        events.append({
            "drift_id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                       f"{scan_run_id}:{uid}:{change_type}")),
            "tenant_id": tenant_id,
            "scan_run_id": scan_run_id,
            "previous_scan_id": prev_scan,
            "resource_uid": uid,
            "provider": (asset or {}).get("provider"),
            "resource_type": (asset or {}).get("resource_type"),
            "change_type": change_type,
            "changes_summary": summary or {},
        })

    for uid, asset in current.items():
        was = previous.get(uid)
        if was is None:
            record(uid, asset, "ASSET_ADDED")
            continue
        changed = {}
        for field in _IDENTITY:
            before, after = was.get(field), asset.get(field)
            if isinstance(before, str) and isinstance(after, (dict, list)):
                try:
                    before = json.loads(before)
                except ValueError:
                    pass
            if before != after:
                changed[field] = {"before": before, "after": after}
        if changed:
            record(uid, asset, "ASSET_CHANGED", changed)

    for uid, asset in previous.items():
        if uid not in current:
            record(uid, asset, "ASSET_REMOVED")

    if events:
        backend.upsert("inventory_drift_events", events, ["drift_id"])
    return counts


def upsert_assets(rows, scan_run_id, scanned_at):
    """Stage-2 writer: upsert current state, stamping first/last seen."""
    backend = get_backend()
    if not is_postgres():
        return 0  # file mode: stage 2 already writes the artifacts directly
    # A batch can carry the same resource twice (discovered via two calls);
    # ON CONFLICT can't touch a row twice, so dedupe by key — last wins.
    deduped = {}
    for row in rows:
        row.setdefault("first_seen_scan_id", scan_run_id)
        row.setdefault("first_seen_at", scanned_at)
        row["last_seen_scan_id"] = scan_run_id
        row["last_seen_at"] = scanned_at
        deduped[(row.get("tenant_id"), row.get("resource_uid"))] = row
    rows = list(deduped.values())
    update_cols = [c for c in rows[0].keys()
                   if c not in ("tenant_id", "resource_uid",
                                "first_seen_scan_id", "first_seen_at")]
    return backend.upsert("inventory_assets", rows,
                          ["tenant_id", "resource_uid"], update_cols)


def prune_stale(scan_run_id, tenant_id="local"):
    """
    Drop rows this scan did not see.

    An inventory answers "what exists now", so a resource that has gone has no
    row. Without this the table only ever grew: every write carried the same
    `adhoc` run id, so nothing could tell a current row from one left behind by
    a scan weeks ago — 278 of them by the time anyone looked.

    Safe because it runs AFTER the upsert, so every resource in this scan
    already carries this run's id. Deletion rather than a flag: the removal is
    already recorded as a drift event, which is the durable history, and a
    "deleted" column would have every reader remember to filter on it.
    """
    backend = get_backend()
    if not is_postgres() or not scan_run_id:
        return 0
    rows = backend.query(
        "DELETE FROM inventory_assets"
        " WHERE tenant_id = %s AND last_seen_scan_id IS DISTINCT FROM %s"
        " RETURNING resource_uid", [tenant_id, scan_run_id])
    return len(rows or [])
