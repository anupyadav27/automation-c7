"""
Inventory UI Data Router — Unified endpoint for frontend.

Provides a single GET endpoint that returns everything the UI dashboard
needs for the inventory page: summary counters, provider/service/region
breakdowns, relationships summary, drift counts, and a paginated asset list.

Endpoint:
  GET /api/v1/inventory/ui-data?tenant_id=X&scan_run_id=latest&limit=200&offset=0

Tables read (threat_engine_inventory):
  - inventory_report        : scan summaries (total_assets, total_relationships, scan_metadata)
  - inventory_findings      : per-asset records (finding_id, resource_uid, resource_type, name, provider, region …)
  - inventory_relationships : resource-to-resource relationships (relation_type, from_uid, to_uid)
  - inventory_drift         : configuration drift records (change_type: added/removed/modified)
"""

import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inventory-ui-data"])


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_inventory_conn():
    """Create a psycopg2 connection to the inventory database."""
    return psycopg2.connect(
        host=os.getenv("INVENTORY_DB_HOST", os.getenv("DB_HOST", "localhost")),
        port=int(os.getenv("INVENTORY_DB_PORT", os.getenv("DB_PORT", "5432"))),
        dbname=os.getenv("INVENTORY_DB_NAME", "threat_engine_inventory"),
        user=os.getenv("INVENTORY_DB_USER", os.getenv("DB_USER", "postgres")),
        password=os.getenv("INVENTORY_DB_PASSWORD", os.getenv("DB_PASSWORD", "")),
    )


def _resolve_scan_run_id(
    cursor: psycopg2.extensions.cursor,
    tenant_id: str,
    scan_run_id: Optional[str],
) -> Optional[str]:
    """Resolve the scan_run_id.

    If *scan_run_id* is ``None`` or ``"latest"`` the most recent
    ``inventory_report`` row for the tenant is used.  Otherwise the
    caller-supplied value is returned as-is.

    Args:
        cursor: Open DB cursor (RealDictCursor).
        tenant_id: Tenant UUID string.
        scan_run_id: Explicit scan_run_id or ``"latest"``.

    Returns:
        The resolved scan_run_id, or ``None`` if nothing was found.
    """
    if scan_run_id and scan_run_id != "latest":
        # Check if the caller passed a scan_run_id — try to find a matching
        # row in inventory_report.
        inv_candidate = f"inventory_{scan_run_id}"
        cursor.execute(
            """
            SELECT scan_run_id
            FROM inventory_report
            WHERE tenant_id = %s AND scan_run_id = %s
            LIMIT 1
            """,
            (tenant_id, inv_candidate),
        )
        row = cursor.fetchone()
        if row:
            return row["scan_run_id"]
        # Fallback: maybe the value IS a scan_run_id already.
        return scan_run_id

    # "latest" — pick the most recent completed report for this tenant.
    # Fall back to any report, then to inventory_findings directly.
    cursor.execute(
        """
        SELECT scan_run_id
        FROM inventory_report
        WHERE tenant_id = %s AND status = 'completed' AND total_assets > 0
        ORDER BY created_at DESC LIMIT 1
        """,
        (tenant_id,),
    )
    row = cursor.fetchone()
    if row:
        return row["scan_run_id"]

    # Fallback: most recent scan_run_id with actual findings data
    cursor.execute(
        """
        SELECT scan_run_id, COUNT(*) AS cnt
        FROM inventory_findings
        WHERE tenant_id = %s
        GROUP BY scan_run_id
        ORDER BY MAX(last_seen_at) DESC NULLS LAST, cnt DESC
        LIMIT 1
        """,
        (tenant_id,),
    )
    row = cursor.fetchone()
    return row["scan_run_id"] if row else None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/api/v1/inventory/ui-data")
async def inventory_ui_data(
    tenant_id: str = Query(..., description="Tenant UUID"),
    scan_run_id: str = Query("latest", description="Scan run ID or 'latest'"),
    limit: int = Query(200, ge=1, le=2000, description="Page size for assets"),
    offset: int = Query(0, ge=0, description="Offset for asset pagination"),
) -> Dict[str, Any]:
    """Return a consolidated UI payload for the inventory dashboard.

    The response contains:
    * ``summary`` — aggregate counters and breakdowns.
    * ``assets`` — paginated list of inventory findings.
    * ``total`` — total asset count (before pagination).
    * ``has_more`` — whether more pages exist.
    * ``scan_id`` — resolved scan_run_id.

    Args:
        tenant_id: Tenant UUID.
        scan_run_id: Explicit scan_run_id or ``"latest"`` (default).
        limit: Maximum assets to return per page.
        offset: Pagination offset.

    Returns:
        Dict with summary + paginated asset data.
    """
    conn = None
    try:
        conn = _get_inventory_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Resolve scan_run_id ----------------------------------------
        inv_scan_id = _resolve_scan_run_id(cursor, tenant_id, scan_run_id)
        if not inv_scan_id:
            return {
                "summary": {
                    "total_assets": 0,
                    "total_relationships": 0,
                    "total_drift": 0,
                    "drift_by_type": {},
                    "assets_by_provider": {},
                    "assets_by_service": [],
                    "assets_by_region": [],
                    "relationships_by_type": {},
                },
                "assets": [],
                "total": 0,
                "has_more": False,
                "scan_id": None,
            }

        # 2. Report-level totals -----------------------------------------------
        cursor.execute(
            """
            SELECT total_assets, total_relationships, scan_metadata
            FROM inventory_report
            WHERE scan_run_id = %s AND tenant_id = %s
            LIMIT 1
            """,
            (inv_scan_id, tenant_id),
        )
        report_row = cursor.fetchone()

        total_assets = 0
        total_relationships = 0
        total_drift = 0
        report_summary: Dict[str, Any] = {}

        if report_row:
            total_assets = report_row["total_assets"] or 0
            total_relationships = report_row["total_relationships"] or 0
            raw_summary = report_row["scan_metadata"]
            if isinstance(raw_summary, dict):
                report_summary = raw_summary
                total_drift = report_summary.get("total_drift", 0)

        # 3. Assets by provider -------------------------------------------------
        cursor.execute(
            """
            SELECT provider, COUNT(*) AS cnt
            FROM inventory_findings
            WHERE scan_run_id = %s AND tenant_id = %s
            GROUP BY provider
            ORDER BY cnt DESC
            """,
            (inv_scan_id, tenant_id),
        )
        assets_by_provider: Dict[str, int] = {}
        for row in cursor.fetchall():
            assets_by_provider[row["provider"] or "unknown"] = row["cnt"]

        # 4. Assets by service (resource_type) ----------------------------------
        cursor.execute(
            """
            SELECT resource_type, COUNT(*) AS cnt
            FROM inventory_findings
            WHERE scan_run_id = %s AND tenant_id = %s
            GROUP BY resource_type
            ORDER BY cnt DESC
            LIMIT 50
            """,
            (inv_scan_id, tenant_id),
        )
        assets_by_service: List[Dict[str, Any]] = [
            {"service": row["resource_type"] or "unknown", "count": row["cnt"]}
            for row in cursor.fetchall()
        ]

        # 5. Assets by region ---------------------------------------------------
        cursor.execute(
            """
            SELECT region, COUNT(*) AS cnt
            FROM inventory_findings
            WHERE scan_run_id = %s AND tenant_id = %s
            GROUP BY region
            ORDER BY cnt DESC
            LIMIT 50
            """,
            (inv_scan_id, tenant_id),
        )
        assets_by_region: List[Dict[str, Any]] = [
            {"region": row["region"] or "global", "count": row["cnt"]}
            for row in cursor.fetchall()
        ]

        # 5b. Relationships by type ---------------------------------------------
        cursor.execute(
            """
            SELECT relation_type, COUNT(*) AS cnt
            FROM inventory_relationships
            WHERE scan_run_id = %s AND tenant_id = %s
            GROUP BY relation_type
            ORDER BY cnt DESC
            """,
            (inv_scan_id, tenant_id),
        )
        relationships_by_type: Dict[str, int] = {}
        for row in cursor.fetchall():
            relationships_by_type[row["relation_type"] or "unknown"] = row["cnt"]

        # 5c. Drift by change type ----------------------------------------------
        cursor.execute(
            """
            SELECT change_type, COUNT(*) AS cnt
            FROM inventory_drift
            WHERE inventory_scan_id = %s AND tenant_id = %s
            GROUP BY change_type
            ORDER BY cnt DESC
            """,
            (inv_scan_id, tenant_id),
        )
        drift_by_type: Dict[str, int] = {}
        for row in cursor.fetchall():
            drift_by_type[row["change_type"] or "unknown"] = row["cnt"]
        # Use actual drift count if report didn't have it
        if not total_drift:
            total_drift = sum(drift_by_type.values())

        # 6. Paginated asset list -----------------------------------------------
        cursor.execute(
            """
            SELECT asset_id, scan_run_id, tenant_id, resource_uid,
                   resource_type, name, provider, account_id,
                   region, tags, configuration, first_seen_at,
                   updated_at
            FROM inventory_findings
            WHERE scan_run_id = %s AND tenant_id = %s
            ORDER BY resource_type, name
            LIMIT %s OFFSET %s
            """,
            (inv_scan_id, tenant_id, limit, offset),
        )
        asset_rows = cursor.fetchall()

        assets: List[Dict[str, Any]] = []
        for r in asset_rows:
            tags_val = r["tags"]
            if not isinstance(tags_val, dict):
                tags_val = {}
            config_val = r["configuration"]
            if not isinstance(config_val, dict):
                config_val = {}

            assets.append({
                "id": str(r["asset_id"]),
                "resource_uid": r["resource_uid"],
                "resource_type": r["resource_type"],
                "resource_name": r["name"],
                "provider": r["provider"],
                "account_id": r["account_id"],
                "region": r["region"],
                "tags": tags_val,
                "config": config_val,
                "created_at": r["first_seen_at"].isoformat() if r["first_seen_at"] else None,
                "last_scanned": r["updated_at"].isoformat() if r.get("updated_at") else None,
            })

        # Use report total_assets when available; otherwise fall back to
        # the provider-aggregated count (which is the actual row count).
        effective_total = total_assets if total_assets > 0 else sum(assets_by_provider.values())
        has_more = (offset + limit) < effective_total

        cursor.close()

        return {
            "summary": {
                "total_assets": effective_total,
                "total_relationships": total_relationships,
                "total_drift": total_drift,
                "drift_by_type": drift_by_type,
                "assets_by_provider": assets_by_provider,
                "assets_by_service": assets_by_service,
                "assets_by_region": assets_by_region,
                "relationships_by_type": relationships_by_type,
            },
            "assets": assets,
            "total": effective_total,
            "has_more": has_more,
            "scan_id": inv_scan_id,
        }

    except psycopg2.Error as db_err:
        logger.error("Inventory ui-data DB error: %s", db_err, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as exc:
        logger.error("Inventory ui-data error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if conn and not conn.closed:
            try:
                conn.close()
            except Exception:
                pass
