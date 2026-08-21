"""
Rules Admin Router — DB-driven relationship rule management.

Provides CRUD endpoints for `resource_security_relationship_rules` table, making the
database the single source of truth for multi-CSP relationship extraction.
No code changes or redeployment needed to add/modify rules for new CSPs.

Endpoints:
  GET    /api/v1/admin/rules              — list rules (filterable)
  POST   /api/v1/admin/rules              — create or upsert a rule
  PUT    /api/v1/admin/rules/{rule_id}    — update a rule by ID
  DELETE /api/v1/admin/rules/{rule_id}    — deactivate (soft delete) a rule
  GET    /api/v1/admin/rules/stats        — counts by CSP and source
  POST   /api/v1/admin/rules/reload       — trigger in-process rule cache refresh
"""

import json
import logging
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database.connection.database_config import get_database_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/rules", tags=["rules-admin"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    csp: str = Field(..., description="Cloud provider: aws | azure | gcp | oci | ibm | alicloud | k8s")
    service: Optional[str] = Field(None, description="Source service (e.g. ec2, lambda). Null for cross-service rules.")
    from_resource_type: str = Field(..., description="Source resource type (e.g. ec2.instance)")
    relation_type: str = Field(..., description="Relationship verb (e.g. attached_to, uses, encrypted_by)")
    to_resource_type: str = Field(..., description="Target resource type (e.g. ec2.security-group)")
    source_field: str = Field(..., description="Dot-path in raw API response to extract value from")
    source_field_item: Optional[str] = Field(None, description="For arrays: sub-field to extract per item")
    target_uid_pattern: str = Field(..., description="Pattern to build target UID, e.g. arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}")
    is_active: bool = Field(True, description="Whether this rule is applied at scan time")
    rule_source: str = Field("curated", description="Rule origin: curated | auto | migrated")
    rule_metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata JSON")


class RuleUpdate(BaseModel):
    is_active: Optional[bool] = None
    target_uid_pattern: Optional[str] = None
    source_field: Optional[str] = None
    source_field_item: Optional[str] = None
    rule_metadata: Optional[Dict[str, Any]] = None


class RuleResponse(BaseModel):
    rule_id: int
    csp: str
    service: Optional[str]
    from_resource_type: str
    relation_type: str
    to_resource_type: str
    source_field: str
    source_field_item: Optional[str]
    target_uid_pattern: str
    is_active: bool
    rule_source: str
    rule_metadata: Dict[str, Any]
    created_at: str
    updated_at: str


# ── DB helper ─────────────────────────────────────────────────────────────────

def _get_conn():
    db_cfg = get_database_config("inventory")
    return psycopg2.connect(
        host=db_cfg.host,
        port=db_cfg.port,
        dbname=db_cfg.database,
        user=db_cfg.username,
        password=db_cfg.password,
        connect_timeout=5,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[RuleResponse], summary="List relationship rules")
async def list_rules(
    csp: Optional[str] = Query(None, description="Filter by CSP (aws, azure, gcp, ...)"),
    service: Optional[str] = Query(None, description="Filter by service (ec2, lambda, ...)"),
    from_resource_type: Optional[str] = Query(None, description="Filter by source resource type"),
    to_resource_type: Optional[str] = Query(None, description="Filter by target resource type"),
    relation_type: Optional[str] = Query(None, description="Filter by relationship type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    rule_source: Optional[str] = Query(None, description="Filter by rule source (curated, auto)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List relationship rules with optional filters. Returns rules ordered by CSP + from_type."""
    conditions: List[str] = []
    params: List[Any] = []

    if csp is not None:
        conditions.append("csp = %s")
        params.append(csp)
    if service is not None:
        conditions.append("service = %s")
        params.append(service)
    if from_resource_type is not None:
        conditions.append("from_resource_type = %s")
        params.append(from_resource_type)
    if to_resource_type is not None:
        conditions.append("to_resource_type = %s")
        params.append(to_resource_type)
    if relation_type is not None:
        conditions.append("relation_type = %s")
        params.append(relation_type)
    if is_active is not None:
        conditions.append("is_active = %s")
        params.append(is_active)
    if rule_source is not None:
        conditions.append("rule_source = %s")
        params.append(rule_source)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, skip])

    sql = f"""
        SELECT rule_id, csp, service, from_resource_type, relation_type, to_resource_type,
               source_field, source_field_item, target_uid_pattern, is_active, rule_source,
               rule_metadata, created_at::text, updated_at::text
        FROM resource_security_relationship_rules
        {where}
        ORDER BY csp, from_resource_type, relation_type
        LIMIT %s OFFSET %s
    """
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"list_rules failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats", summary="Rule counts by CSP and source")
async def rule_stats():
    """Return rule counts grouped by CSP and rule_source."""
    sql = """
        SELECT csp, rule_source, is_active, COUNT(*) AS count
        FROM resource_security_relationship_rules
        GROUP BY csp, rule_source, is_active
        ORDER BY csp, rule_source
    """
    try:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = [dict(r) for r in cur.fetchall()]
                totals: Dict[str, int] = {}
                for r in rows:
                    totals[r["csp"]] = totals.get(r["csp"], 0) + r["count"]
                return {"breakdown": rows, "totals_by_csp": totals, "grand_total": sum(totals.values())}
        finally:
            conn.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("", response_model=Dict[str, Any], status_code=201, summary="Create or upsert a rule")
async def create_rule(rule: RuleCreate):
    """Create a new relationship rule. Upserts on the unique constraint
    (csp, from_resource_type, relation_type, to_resource_type, source_field)."""
    sql = """
        INSERT INTO resource_security_relationship_rules
            (csp, service, from_resource_type, relation_type, to_resource_type,
             source_field, source_field_item, target_uid_pattern,
             is_active, rule_source, rule_metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (csp, from_resource_type, relation_type, to_resource_type, source_field)
        DO UPDATE SET
            service            = EXCLUDED.service,
            source_field_item  = EXCLUDED.source_field_item,
            target_uid_pattern = EXCLUDED.target_uid_pattern,
            is_active          = EXCLUDED.is_active,
            rule_source        = EXCLUDED.rule_source,
            rule_metadata      = EXCLUDED.rule_metadata,
            updated_at         = NOW()
        RETURNING rule_id, created_at::text, updated_at::text
    """
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    rule.csp, rule.service, rule.from_resource_type,
                    rule.relation_type, rule.to_resource_type,
                    rule.source_field, rule.source_field_item,
                    rule.target_uid_pattern, rule.is_active, rule.rule_source,
                    json.dumps(rule.rule_metadata or {}),
                ))
                conn.commit()
                row = cur.fetchone()
                return {
                    "rule_id": row[0],
                    "status": "created",
                    "created_at": row[1],
                    "updated_at": row[2],
                }
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"create_rule failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{rule_id}", response_model=Dict[str, Any], summary="Update a rule by ID")
async def update_rule(rule_id: int, update: RuleUpdate):
    """Partially update a rule by its rule_id. Only provided fields are changed."""
    set_parts: List[str] = ["updated_at = NOW()"]
    params: List[Any] = []

    if update.is_active is not None:
        set_parts.append("is_active = %s")
        params.append(update.is_active)
    if update.target_uid_pattern is not None:
        set_parts.append("target_uid_pattern = %s")
        params.append(update.target_uid_pattern)
    if update.source_field is not None:
        set_parts.append("source_field = %s")
        params.append(update.source_field)
    if update.source_field_item is not None:
        set_parts.append("source_field_item = %s")
        params.append(update.source_field_item)
    if update.rule_metadata is not None:
        set_parts.append("rule_metadata = %s::jsonb")
        params.append(json.dumps(update.rule_metadata))

    if len(set_parts) == 1:  # only updated_at
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(rule_id)
    sql = f"UPDATE resource_security_relationship_rules SET {', '.join(set_parts)} WHERE rule_id = %s RETURNING rule_id, updated_at::text"

    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
                return {"rule_id": row[0], "status": "updated", "updated_at": row[1]}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{rule_id}", response_model=Dict[str, Any], summary="Deactivate a rule")
async def deactivate_rule(rule_id: int):
    """Soft-delete: sets is_active=FALSE. The rule stays in DB for audit purposes.
    Use PUT to re-activate."""
    sql = """
        UPDATE resource_security_relationship_rules
        SET is_active = FALSE, updated_at = NOW()
        WHERE rule_id = %s
        RETURNING rule_id, updated_at::text
    """
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (rule_id,))
                conn.commit()
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
                return {"rule_id": row[0], "status": "deactivated", "updated_at": row[1]}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/reload", summary="Reload rules (cache invalidation)")
async def reload_rules():
    """Signal to reload rules. Currently rules are fetched fresh per scan — this is
    a no-op placeholder for future in-process caching."""
    return {"status": "ok", "message": "Rules are fetched fresh per scan run; no cache to invalidate."}
