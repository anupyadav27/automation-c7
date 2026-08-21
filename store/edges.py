"""
store.edges — what points at what.

The catalog holds the RULES (`rule_diagram_relationship`, 2,780 declared paths
from one type to another). This holds the EDGES those rules actually produced
against a real account, so a reader can ask "what is this resource connected
to" without reading a CSV off the pipeline host.

Keyed on (source, target, edge_type). That triple is the identity of a
relationship: one pair related two ways is two edges, and one pair found by
four different paths is one edge with four corroborations.
"""
from . import get_backend, is_postgres

# Columns the table actually has. An edge row arrives from the validator
# carrying verdict fields and ladder checks that belong to the CATALOG, not to
# the estate — writing them here would duplicate the rule's own record and let
# the two disagree.
_COLUMNS = ("tenant_id", "source_asset_id", "target_asset_id", "edge_type",
            "source_key", "target_key", "via", "mechanism", "confidence",
            "corroborations", "resolved", "value", "attributes",
            "last_seen_scan_id", "last_seen_at")


def _row(edge, tenant_id, scan_run_id, scanned_at):
    """One validator edge as one table row, with nothing extra."""
    resolved = edge.get("resolved")
    if isinstance(resolved, str):
        resolved = resolved.strip().lower() == "true"
    attributes = edge.get("attributes")
    return {
        "tenant_id": tenant_id,
        "source_asset_id": edge.get("source_asset_id") or "",
        "target_asset_id": edge.get("target_asset_id") or "",
        "edge_type": edge.get("edge_type") or "references",
        "source_key": edge.get("source_key") or None,
        "target_key": edge.get("target_key") or None,
        "via": edge.get("via") or None,
        "mechanism": edge.get("mechanism") or None,
        "confidence": edge.get("confidence") or None,
        "corroborations": int(edge.get("corroborations") or 1),
        "resolved": True if resolved is None else bool(resolved),
        "value": edge.get("value") or None,
        "attributes": attributes if isinstance(attributes, (dict, list)) else {},
        "last_seen_scan_id": scan_run_id,
        "last_seen_at": scanned_at,
    }


def upsert_edges(edges, scan_run_id, scanned_at, tenant_id="local"):
    """
    Stage-2 writer. Returns the number of rows written.

    Deduped before the upsert for the same reason `upsert_assets` is: Postgres
    cannot touch the same row twice in one `ON CONFLICT` statement, and a batch
    legitimately carries the same edge more than once when two relation rules
    resolve to it. Last wins, which is safe because the validator has already
    collapsed duplicates and kept the strongest.
    """
    backend = get_backend()
    if not is_postgres():
        return 0  # files mode: out/edges.csv already IS the artifact

    deduped = {}
    for edge in edges or []:
        row = _row(edge, tenant_id, scan_run_id, scanned_at)
        if not row["source_asset_id"] or not row["target_asset_id"]:
            continue  # an edge with no end is not an edge
        deduped[(row["tenant_id"], row["source_asset_id"],
                 row["target_asset_id"], row["edge_type"])] = row
    rows = list(deduped.values())
    if not rows:
        return 0

    keys = ["tenant_id", "source_asset_id", "target_asset_id", "edge_type"]
    return backend.upsert("inventory_edges", rows, keys,
                          [c for c in _COLUMNS if c not in keys])


def prune_stale(scan_run_id, tenant_id="local"):
    """
    Drop edges this scan did not see.

    Same rule as the assets: the graph answers "what is connected now". An edge
    whose resource was deleted, or whose rule was refuted and stopped firing,
    has no row — otherwise the table only grows and a panel shows relationships
    that no longer exist.
    """
    backend = get_backend()
    if not is_postgres() or not scan_run_id:
        return 0
    rows = backend.query(
        "DELETE FROM inventory_edges"
        " WHERE tenant_id = %s AND last_seen_scan_id IS DISTINCT FROM %s"
        " RETURNING source_asset_id", [tenant_id, scan_run_id])
    return len(rows or [])


def relations_for(resource_uid, tenant_id="local", limit=500):
    """
    Every edge touching this resource, both directions, in one query.

    Direction is returned rather than normalised away. An edge is directional
    but relatedness is not: a security group's whole answer is the edges
    pointing AT it, and the panel has to phrase those from its end — "protects"
    rather than "protected-by". Only the caller knows which end it is standing
    on, so it is told.
    """
    backend = get_backend()
    if not is_postgres():
        return []
    return backend.query(
        "SELECT *, 'out' AS direction FROM inventory_edges"
        "  WHERE tenant_id = %s AND source_asset_id = %s"
        " UNION ALL "
        "SELECT *, 'in' AS direction FROM inventory_edges"
        "  WHERE tenant_id = %s AND target_asset_id = %s"
        " LIMIT %s",
        [tenant_id, resource_uid, tenant_id, resource_uid, limit]) or []


def count(tenant_id="local"):
    """Row count, for the run report."""
    backend = get_backend()
    if not is_postgres():
        return 0
    row = backend.query_one(
        "SELECT count(*) AS n FROM inventory_edges WHERE tenant_id = %s",
        [tenant_id])
    return (row or {}).get("n", 0)
