"""
Architecture Router — resource taxonomy and architecture diagram endpoints.

Endpoints:
  GET /api/v1/inventory/taxonomy          — resource classification taxonomy
  GET /api/v1/inventory/taxonomy/coverage — how many resource_types have taxonomy entries
  GET /api/v1/inventory/architecture      — pre-nested architecture hierarchy for diagram rendering

Database:
  READS:  architecture_resource_placement, resource_inventory_identifier,
          inventory_scan_data, inventory_relationships, inventory_findings
"""

import logging
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query
from .router_utils import _get_raw_conn
from ..database.connection.database_config import get_database_config
from ..api.architecture_builder import build_architecture_hierarchy

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/inventory/taxonomy")
async def get_taxonomy(
    csp: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    min_priority: int = Query(5, ge=1, le=5),
):
    """Resource classification taxonomy from architecture_resource_placement.

    Used by the UI to group, color, and nest resources in architecture diagrams.
    """
    try:
        conn = _get_raw_conn()
        try:
            with conn.cursor() as cur:
                conditions = []
                params = []
                if csp:
                    conditions.append("csp = %s")
                    params.append(csp)
                if category:
                    conditions.append("category = %s")
                    params.append(category)
                if min_priority < 5:
                    conditions.append("diagram_priority <= %s")
                    params.append(min_priority)

                where = " AND ".join(conditions) if conditions else "TRUE"
                cur.execute(f"""
                    SELECT csp, resource_type,
                           visual_subgroup AS service,
                           resource_type AS resource_name,
                           resource_type AS display_name,
                           placement_scope AS scope,
                           visual_group AS category,
                           visual_subgroup AS subcategory,
                           '' AS service_model, '' AS managed_by,
                           '' AS access_pattern, '' AS encryption_scope,
                           is_container, placement_parent AS container_parent,
                           display_priority AS diagram_priority, '' AS csp_category
                    FROM architecture_resource_placement
                    WHERE {where}
                    ORDER BY csp, display_priority, visual_group, resource_type
                """, params)

                columns = [desc[0] for desc in cur.description]
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]

                categories_summary = {}
                for r in rows:
                    cat = r["category"]
                    if cat not in categories_summary:
                        categories_summary[cat] = {"count": 0, "subcategories": set()}
                    categories_summary[cat]["count"] += 1
                    if r.get("subcategory"):
                        categories_summary[cat]["subcategories"].add(r["subcategory"])

                for cat_info in categories_summary.values():
                    cat_info["subcategories"] = sorted(cat_info["subcategories"])

                return {
                    "total": len(rows),
                    "classifications": rows,
                    "categories_summary": categories_summary,
                    "filters_applied": {"csp": csp, "category": category, "min_priority": min_priority},
                }
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to get taxonomy", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get taxonomy: {e}")


@router.get("/api/v1/inventory/taxonomy/coverage")
async def get_taxonomy_coverage():
    """Coverage stats: how many inventory resource_types have a matching taxonomy entry."""
    try:
        conn = _get_raw_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH inv_types AS (
                        SELECT DISTINCT provider AS csp, resource_type, COUNT(*) AS asset_count
                        FROM inventory_findings
                        GROUP BY provider, resource_type
                    )
                    SELECT i.csp, i.resource_type, i.asset_count,
                           arp.visual_group AS category,
                           arp.display_priority AS diagram_priority,
                           CASE WHEN arp.id IS NOT NULL THEN true ELSE false END AS classified
                    FROM inv_types i
                    LEFT JOIN architecture_resource_placement arp
                        ON arp.csp = i.csp AND arp.resource_type = i.resource_type
                    ORDER BY i.csp, classified, i.asset_count DESC
                """)
                columns = [desc[0] for desc in cur.description]
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]

                by_csp = {}
                for r in rows:
                    c = r["csp"]
                    if c not in by_csp:
                        by_csp[c] = {"total_types": 0, "classified": 0, "unclassified": 0,
                                     "total_assets": 0, "classified_assets": 0}
                    by_csp[c]["total_types"] += 1
                    by_csp[c]["total_assets"] += r["asset_count"]
                    if r["classified"]:
                        by_csp[c]["classified"] += 1
                        by_csp[c]["classified_assets"] += r["asset_count"]
                    else:
                        by_csp[c]["unclassified"] += 1

                for v in by_csp.values():
                    v["coverage_pct"] = round(v["classified"] / v["total_types"] * 100, 1) if v["total_types"] > 0 else 0

                return {"summary": by_csp, "details": rows}
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to get taxonomy coverage", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/inventory/architecture")
async def get_architecture_diagram(
    tenant_id: Optional[str] = Query(None),
    scan_run_id: Optional[str] = Query(None),
    max_priority: int = Query(2, ge=1, le=5),
    include_relationships: bool = Query(True),
    csp: Optional[str] = Query(None),
):
    """
    Pre-nested architecture hierarchy for diagram rendering.

    Combines inventory_scan_data (assets), inventory_relationships (edges),
    and architecture_resource_placement (taxonomy) into a nested account→region→VPC→subnet
    hierarchy ready for the frontend to render without further processing.
    """
    try:
        conn = _get_raw_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # ── Resolve scan_run_id(s) ──
                use_all_scans = False
                scan_run_ids = []
                if not scan_run_id or scan_run_id == "latest":
                    if tenant_id:
                        cur.execute("""
                            SELECT DISTINCT inventory_scan_id, MAX(created_at) AS latest
                            FROM inventory_scan_data WHERE tenant_id = %s
                            GROUP BY inventory_scan_id ORDER BY latest DESC LIMIT 10
                        """, (tenant_id,))
                    else:
                        cur.execute("""
                            SELECT DISTINCT inventory_scan_id, MAX(created_at) AS latest
                            FROM inventory_scan_data
                            GROUP BY inventory_scan_id ORDER BY latest DESC LIMIT 10
                        """)
                    rows = cur.fetchall()
                    if not rows:
                        return {"accounts": [], "relationships": [], "message": "No inventory data found"}
                    scan_run_ids = [r["inventory_scan_id"] for r in rows]
                    scan_run_id = scan_run_ids[0]
                    use_all_scans = True
                else:
                    scan_run_ids = [scan_run_id]

                # ── Load taxonomy ──
                csp_condition = "WHERE csp = %s" if csp else ""
                tax_params = [csp] if csp else []
                cur.execute(f"""
                    SELECT csp, resource_type, diagram_zone, arch_layer,
                           placement_scope AS scope, placement_parent AS container_parent,
                           placement_zone, visual_group AS category, visual_subgroup AS subcategory,
                           is_container, container_depth, display_priority AS diagram_priority,
                           show_as,
                           CASE WHEN arch_layer >= 4 THEN 'supporting' ELSE 'primary' END AS resource_role,
                           '' AS managed_by, '' AS access_pattern,
                           '' AS service_model, '' AS display_name, '' AS resource_name, '' AS service
                    FROM architecture_resource_placement {csp_condition}
                """, tax_params)
                taxonomy = {f"{r['csp']}.{r['resource_type']}": dict(r) for r in cur.fetchall()}

                # ── Load assets ──
                csp_filter = "AND sd.provider = %s" if csp else ""
                tenant_filter = "AND sd.tenant_id = %s" if tenant_id else ""
                params = []
                if tenant_id:
                    params.append(tenant_id)
                if csp:
                    params.append(csp)

                if use_all_scans and len(scan_run_ids) > 1:
                    placeholders = ", ".join(["%s"] * len(scan_run_ids))
                    params.extend(scan_run_ids)
                    scan_filter = f"AND sd.inventory_scan_id IN ({placeholders})"
                else:
                    params.append(scan_run_ids[0])
                    scan_filter = "AND sd.inventory_scan_id = %s"

                params.append(max_priority)
                cur.execute(f"""
                    SELECT sd.asset_id, sd.resource_uid, sd.provider,
                           sd.account_id, sd.region, sd.resource_type,
                           sd.resource_id, sd.name, sd.name AS display_name,
                           sd.tags, NULL::float AS risk_score, 'normal' AS criticality,
                           'unknown' AS compliance_status,
                           sd.inventory_scan_id AS latest_scan_run_id,
                           sd.properties, sd.configuration
                    FROM inventory_scan_data sd
                    INNER JOIN architecture_resource_placement arp
                      ON arp.csp = sd.provider AND arp.resource_type = sd.resource_type
                    LEFT JOIN resource_inventory_identifier rii
                      ON rii.csp = sd.provider
                     AND (rii.service || '.' || rii.canonical_type) = sd.resource_type
                    WHERE 1=1 {tenant_filter} {csp_filter} {scan_filter}
                    AND COALESCE(rii.show_in_architecture, true) = true
                    AND (arp.display_priority <= %s OR arp.is_container = TRUE)
                    ORDER BY sd.account_id, sd.region, sd.resource_type
                """, params)
                assets = [dict(r) for r in cur.fetchall()]

                # ── Load relationships ──
                relationships = []
                if include_relationships:
                    if tenant_id:
                        cur.execute("""
                            SELECT DISTINCT ON (from_uid, to_uid, relation_type)
                                   from_uid, to_uid, relation_type,
                                   from_resource_type, to_resource_type,
                                   relationship_strength, bidirectional
                            FROM inventory_relationships WHERE tenant_id = %s
                            ORDER BY from_uid, to_uid, relation_type
                        """, [tenant_id])
                    else:
                        cur.execute("""
                            SELECT DISTINCT ON (from_uid, to_uid, relation_type)
                                   from_uid, to_uid, relation_type,
                                   from_resource_type, to_resource_type,
                                   relationship_strength, bidirectional
                            FROM inventory_relationships
                            ORDER BY from_uid, to_uid, relation_type
                        """)
                    relationships = [dict(r) for r in cur.fetchall()]

                # ── Build nested hierarchy ──
                hierarchy = build_architecture_hierarchy(assets, taxonomy, relationships)

                return {
                    **hierarchy,
                    "scan_run_id": scan_run_id,
                    "filters": {
                        "max_priority": max_priority,
                        "include_relationships": include_relationships,
                        "csp": csp,
                    },
                    "stats": {
                        "total_assets": len(assets),
                        "total_relationships": len(relationships),
                        "taxonomy_entries": len(taxonomy),
                    },
                }
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to build architecture diagram", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build architecture: {e}")
