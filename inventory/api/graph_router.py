"""
Graph Router — graph traversal and relationships.

Endpoints:
  GET /api/v1/inventory/graph                                  — raw BFS graph
  GET /api/v1/inventory/runs/latest/graph                      — UI-friendly graph (nodes/links)
  GET /api/v1/inventory/relationships                          — list relationships (paginated)
  GET /api/v1/inventory/assets/{resource_uid}/relationships    — per-asset relationships

Blast radius and attack paths are served exclusively from the threat engine (Neo4j):
  GET /api/v1/graph/blast-radius/{resource_uid}   (threat engine)
  GET /api/v1/graph/attack-paths                  (threat engine)
  GET /api/v1/graph/toxic-combinations            (threat engine)

Database:
  READS:  inventory_relationships, inventory_findings
"""

import logging
import time
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from providers.common.logger import LogContext, log_duration
from .router_utils import _get_loader, PROVIDER_COLORS, classify_link_type

logger = logging.getLogger(__name__)

router = APIRouter()

# VPC endpoint types — used to synthesise service target nodes in UI graph
_VPC_ENDPOINT_TYPES = {
    "ec2.vpc-endpoint", "network.private-endpoint",
    "compute.service-attachment", "core.service-gateway",
    "is.endpoint-gateway",
}


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_ui_graph(raw: Dict[str, Any], service: Optional[str], provider: Optional[str]) -> Dict[str, Any]:
    """Transform raw graph (nodes/edges) to UI-ready nodes/links schema."""
    ui_nodes = []
    for node in raw.get("nodes") or []:
        rt = node.get("resource_type") or ""
        prov = node.get("provider") or ""
        svc = node.get("service") or (rt.split(".")[0] if "." in rt else rt)
        if service and svc.lower() != service.lower():
            continue
        if provider and prov.lower() != provider.lower():
            continue
        ui_nodes.append({
            "id": node.get("resource_uid"),
            "name": node.get("resource_name") or node.get("name") or node.get("resource_uid", "").rsplit("/", 1)[-1],
            "type": rt,
            "service": svc,
            "provider": prov,
            "color": PROVIDER_COLORS.get(prov.lower(), "#6b7280"),
            "region": node.get("region"),
            "account_id": node.get("account_id"),
        })

    visible_ids = {n["id"] for n in ui_nodes}
    ui_links = []
    synthetic_nodes: Dict[str, Any] = {}

    for edge in raw.get("edges") or []:
        src, tgt = edge.get("from_uid"), edge.get("to_uid")
        if not src or not tgt:
            continue
        rel_type = edge.get("relation_type") or ""
        for uid, rtype_key in ((src, "from_resource_type"), (tgt, "to_resource_type")):
            if uid not in visible_ids and uid not in synthetic_nodes:
                rt = edge.get(rtype_key) or ""
                svc = rt.split(".")[0] if "." in rt else rt
                if service and svc.lower() != service.lower():
                    continue
                if provider:
                    continue
                name = uid.rsplit("/", 1)[-1] if "/" in uid else uid.rsplit(":", 1)[-1]
                synthetic_nodes[uid] = {
                    "id": uid, "name": name, "type": rt, "service": svc,
                    "provider": edge.get("provider", "aws"),
                    "color": PROVIDER_COLORS.get(edge.get("provider", "aws").lower(), "#6b7280"),
                    "region": edge.get("region"), "account_id": edge.get("account_id"),
                    "synthetic": True,
                }
        all_ids = visible_ids | set(synthetic_nodes.keys())
        if src in all_ids and tgt in all_ids:
            ui_links.append({"source": src, "target": tgt, "label": rel_type, "type": classify_link_type(rel_type)})

    all_nodes = ui_nodes + list(synthetic_nodes.values())

    # Synthesise service target nodes for VPC endpoints
    vpc_endpoint_links = []
    vpc_endpoint_service_nodes: Dict[str, Any] = {}
    for node in all_nodes:
        if node.get("type") not in _VPC_ENDPOINT_TYPES:
            continue
        node_id = node.get("id", "")
        node_name = node.get("name", "")
        target_svc = None
        parts = node_name.split(".")
        if len(parts) >= 4 and parts[0] == "com" and parts[1] == "amazonaws":
            target_svc = parts[-1]
        elif "vpce-" in node_name.lower():
            segments = node_name.lower().replace("vpce-", "").split("-")
            if segments:
                target_svc = segments[-1]
        if not target_svc and "." in node_id:
            id_parts = node_id.split(".")
            if len(id_parts) >= 4 and id_parts[0] == "com":
                target_svc = id_parts[-1]
        if target_svc:
            svc_key = f"__svc__{target_svc}"
            if svc_key not in vpc_endpoint_service_nodes:
                vpc_endpoint_service_nodes[svc_key] = {
                    "id": svc_key, "name": target_svc.upper(),
                    "type": f"{target_svc}.service", "service": target_svc,
                    "provider": node.get("provider", "aws"),
                    "color": PROVIDER_COLORS.get(node.get("provider", "aws").lower(), "#6b7280"),
                    "region": "global", "account_id": node.get("account_id"), "synthetic": True,
                }
            vpc_endpoint_links.append({"source": node_id, "target": svc_key, "label": "connected_to", "type": "network"})

    if vpc_endpoint_service_nodes:
        all_nodes.extend(vpc_endpoint_service_nodes.values())
        ui_links.extend(vpc_endpoint_links)

    exposure = raw.get("exposure") or []
    ui_exposure = [{"source": e.get("from_uid"), "target": e.get("to_uid"),
                    "type": e.get("relation_type"), "properties": e.get("properties") or {}}
                   for e in exposure]

    return {
        "nodes": all_nodes, "links": ui_links, "exposure": ui_exposure,
        "depth": raw.get("depth", 5),
        "total_nodes": len(all_nodes), "total_links": len(ui_links),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/inventory/graph")
async def get_graph(
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
    resource_uid: Optional[str] = Query(None),
    depth: int = Query(5, ge=1, le=10),
    limit: int = Query(2000, ge=1, le=5000),
):
    """Raw BFS graph — nodes and edges.  resource_uid scopes to single-asset neighborhood."""
    try:
        loader = _get_loader()
        if resource_uid:
            if not scan_run_id or scan_run_id == "latest":
                scan_run_id = loader.get_latest_scan_id(tenant_id)
            if not scan_run_id:
                loader.close()
                return {"nodes": [], "edges": [], "depth": depth, "total_nodes": 0, "total_edges": 0}

            asset = loader.load_asset_by_uid(tenant_id, resource_uid, scan_run_id)
            nodes = [asset] if asset else []
            rels_from, _ = loader.load_relationships(tenant_id=tenant_id, scan_run_id=scan_run_id, from_uid=resource_uid, limit=500)
            rels_to, _ = loader.load_relationships(tenant_id=tenant_id, scan_run_id=scan_run_id, to_uid=resource_uid, limit=500)
            relationships = rels_from + rels_to

            related_uids = set()
            for rel in relationships:
                if rel.get("from_uid") != resource_uid:
                    related_uids.add(rel.get("from_uid"))
                if rel.get("to_uid") != resource_uid:
                    related_uids.add(rel.get("to_uid"))
            for uid in related_uids:
                related_asset = loader.load_asset_by_uid(tenant_id, uid, scan_run_id)
                if related_asset:
                    nodes.append(related_asset)

            loader.close()
            return {"nodes": nodes, "edges": relationships, "exposure": [],
                    "depth": depth, "total_nodes": len(nodes), "total_edges": len(relationships)}
        else:
            result = loader.load_graph_bfs(tenant_id=tenant_id, scan_run_id=scan_run_id, max_depth=depth, max_nodes=limit)
            loader.close()
            return {"nodes": result["nodes"], "edges": result["relationships"], "exposure": result["exposure"],
                    "depth": depth, "total_nodes": len(result["nodes"]), "total_edges": len(result["relationships"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load graph: {e}")


@router.get("/api/v1/inventory/runs/latest/graph")
async def get_graph_ui(
    tenant_id: str = Query(...),
    resource_uid: Optional[str] = Query(None),
    depth: int = Query(5, ge=1, le=10),
    limit: int = Query(2000, ge=1, le=5000),
    service: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
):
    """UI-friendly graph — nodes with id/name/type/color + links with source/target/label."""
    raw = await get_graph(tenant_id=tenant_id, scan_run_id="latest", resource_uid=resource_uid, depth=depth, limit=limit)
    return _build_ui_graph(raw, service, provider)


@router.get("/api/v1/inventory/relationships")
async def list_relationships(
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
    relation_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    from_uid: Optional[str] = Query(None),
    to_uid: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List relationships with filters and pagination."""
    start_time = time.time()
    with LogContext(tenant_id=tenant_id):
        try:
            loader = _get_loader()
            if not scan_run_id or scan_run_id == "latest":
                scan_run_id = loader.get_latest_scan_id(tenant_id)
                if not scan_run_id:
                    loader.close()
                    return {"relationships": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

            relationships, total = loader.load_relationships(
                tenant_id=tenant_id, scan_run_id=scan_run_id,
                from_uid=from_uid, to_uid=to_uid, relation_type=relation_type,
                limit=limit, offset=offset,
            )
            loader.close()
            log_duration(logger, "Relationships listed", (time.time() - start_time) * 1000)
            return {"relationships": relationships, "total": total, "limit": limit, "offset": offset,
                    "has_more": (offset + len(relationships)) < total}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list relationships: {e}")


@router.get("/api/v1/inventory/assets/{resource_uid:path}/relationships")
async def get_asset_relationships(
    resource_uid: str,
    tenant_id: str = Query(...),
    scan_run_id: Optional[str] = Query(None),
    depth: int = Query(1, ge=1, le=3),
    relation_type: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
):
    """Asset relationships with optional depth traversal (inbound/outbound/both)."""
    start_time = time.time()
    with LogContext(tenant_id=tenant_id):
        try:
            loader = _get_loader()
            if not scan_run_id or scan_run_id == "latest":
                scan_run_id = loader.get_latest_scan_id(tenant_id)
                if not scan_run_id:
                    loader.close()
                    return {"resource_uid": resource_uid, "relationships": [], "by_type": {}, "depth": depth, "total": 0}

            if direction == "inbound":
                relationships, _ = loader.load_relationships(
                    tenant_id=tenant_id, scan_run_id=scan_run_id, to_uid=resource_uid,
                    relation_type=relation_type, limit=1000, offset=0)
            elif direction == "outbound":
                relationships, _ = loader.load_relationships(
                    tenant_id=tenant_id, scan_run_id=scan_run_id, from_uid=resource_uid,
                    relation_type=relation_type, limit=1000, offset=0)
            else:
                rels_from, _ = loader.load_relationships(
                    tenant_id=tenant_id, scan_run_id=scan_run_id, from_uid=resource_uid,
                    relation_type=relation_type, limit=500, offset=0)
                rels_to, _ = loader.load_relationships(
                    tenant_id=tenant_id, scan_run_id=scan_run_id, to_uid=resource_uid,
                    relation_type=relation_type, limit=500, offset=0)
                relationships = rels_from + rels_to

            loader.close()
            by_type: Dict[str, list] = {}
            for rel in relationships:
                rt = rel.get("relation_type", "unknown")
                by_type.setdefault(rt, []).append(rel)

            log_duration(logger, "Asset relationships retrieved", (time.time() - start_time) * 1000)
            return {"resource_uid": resource_uid, "relationships": relationships, "by_type": by_type,
                    "depth": depth, "total": len(relationships)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load relationships: {e}")




