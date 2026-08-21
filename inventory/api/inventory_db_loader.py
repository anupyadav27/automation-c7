"""
Inventory DB Loader

Loads assets, relationships, and drift records from PostgreSQL inventory DB.
Replaces file-based DataLoader for DB-first architecture.

=== DATABASE & TABLE MAP ===
Database: threat_engine_inventory (INVENTORY DB)
Env: INVENTORY_DB_HOST / INVENTORY_DB_PORT / INVENTORY_DB_NAME / INVENTORY_DB_USER / INVENTORY_DB_PASSWORD
     (connection URL passed from api_server.py via get_database_config)

Tables READ:
  - inventory_findings      : load_assets()       — SELECT with filters (tenant_id, scan_run_id,
                                                     provider, region, resource_type, account_id)
                               load_asset_by_uid() — SELECT WHERE tenant_id + resource_uid
  - inventory_relationships : load_relationships() — SELECT with filters (tenant_id, scan_run_id,
                                                     from_uid, to_uid, relation_type)
  - inventory_report        : (accessed via api_server, not directly here)

Tables WRITTEN: None (read-only loader for API queries)
===
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


# ── Resource categorisation for blast radius ──────────────────────────
# Maps resource_type prefix to a security-meaningful category.
_CATEGORY_MAP = {
    # COMPUTE — can execute code
    "ec2.instance": "compute", "lambda.function": "compute",
    "ecs.task": "compute", "ecs.service": "compute",
    "ecs.definition": "compute", "eks.cluster": "compute",
    "batch.compute-environment": "compute", "lightsail.instance": "compute",
    "ec2.image": "compute",
    # DATA STORAGE — holds unstructured data
    "s3.bucket": "storage", "efs.file-system": "storage",
    "ec2.volume": "storage", "ebs.volume": "storage",
    "ec2.snapshot": "storage", "glacier.vault": "storage",
    "backup.backup-vault": "storage",
    # DATABASE — structured data stores
    "rds.db-instance": "database", "rds.db-cluster": "database",
    "dynamodb.table": "database", "elasticache.cluster": "database",
    "elasticache.replication-group": "database", "es.domain": "database",
    "redshift.cluster": "database", "docdb.cluster": "database",
    # IDENTITY — permissions & access
    "iam.role": "identity", "iam.user": "identity",
    "iam.group": "identity", "iam.policy": "identity",
    "iam.instance-profile": "identity",
    # NETWORK — connectivity & boundaries
    "ec2.vpc": "network", "ec2.subnet": "network",
    "ec2.security-group": "network", "ec2.network-acl": "network",
    "ec2.route-table": "network", "ec2.internet-gateway": "network",
    "ec2.nat-gateway": "network", "ec2.transit-gateway": "network",
    "ec2.vpc-peering-connection": "network",
    "ec2.network-interface": "network",
    # LOAD BALANCING
    "elbv2.balancer": "load_balancer", "elbv2.target-group": "load_balancer",
    "elbv2.listener": "load_balancer",
    "elasticloadbalancing.load-balancer": "load_balancer",
    # ENCRYPTION & SECRETS
    "kms.key": "encryption", "kms.alias": "encryption",
    "acm.certificate": "encryption", "secretsmanager.secret": "encryption",
    # SERVERLESS / EVENT
    "events.rule": "serverless", "events.event-bus": "serverless",
    "states.state-machine": "serverless", "sqs.queue": "serverless",
    "sns.topic": "serverless", "kinesis.stream": "serverless",
    # LOGGING / MONITORING
    "logs.log-group": "logging", "cloudtrail.trail": "logging",
    "cloudwatch.alarm": "logging",
    # EXTERNAL SURFACE
    "cloudfront.distribution": "external", "apigateway.rest-api": "external",
    "waf.web-acl": "external",
}


def _categorize_resource(resource_type: str) -> str:
    """Map a resource_type like 'ec2.instance' to a security category."""
    if not resource_type:
        return "other"
    rt = resource_type.lower().strip()
    # Exact match first
    if rt in _CATEGORY_MAP:
        return _CATEGORY_MAP[rt]
    # Try prefix match (e.g. "ec2.instance" matches "ec2.instance-xxx")
    for key, cat in _CATEGORY_MAP.items():
        if rt.startswith(key):
            return cat
    return "other"


class InventoryDBLoader:
    """Loads inventory data from PostgreSQL database"""
    
    def __init__(self, db_url: str):
        """
        Initialize DB loader.
        
        Args:
            db_url: PostgreSQL connection URL
        """
        self.db_url = db_url
        self.conn = psycopg2.connect(db_url)
    
    def load_assets(
        self,
        tenant_id: str,
        scan_run_id: Optional[str] = None,
        provider: Optional[str] = None,
        region: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_type_prefix: Optional[str] = None,
        account_id: Optional[str] = None,
        account_ids: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Load assets from DB with filtering and pagination.
        
        Returns:
            Tuple of (assets list, total_count)
        """
        # Build WHERE clause
        where_parts = ["tenant_id = %s"]
        params = [tenant_id]
        
        if scan_run_id:
            where_parts.append("scan_run_id = %s")
            params.append(scan_run_id)

        if provider:
            where_parts.append("provider = %s")
            params.append(provider)
        
        if region:
            where_parts.append("region = %s")
            params.append(region)
        
        if resource_type:
            where_parts.append("resource_type = %s")
            params.append(resource_type)

        if resource_type_prefix:
            where_parts.append("resource_type LIKE %s")
            params.append(f"{resource_type_prefix}%")

        # Multi-account filter: merge account_ids list + single account_id
        effective_account_ids: Optional[List[str]] = None
        if account_ids:
            effective_account_ids = list(set(account_ids + ([account_id] if account_id else [])))
        elif account_id:
            effective_account_ids = [account_id]

        if effective_account_ids and len(effective_account_ids) == 1:
            where_parts.append("account_id = %s")
            params.append(effective_account_ids[0])
        elif effective_account_ids:
            where_parts.append("account_id = ANY(%s::text[])")
            params.append(effective_account_ids)

        where_clause = " AND ".join(where_parts)
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM inventory_findings WHERE {where_clause}"
        with self.conn.cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()[0]
        
        # Get paginated results
        query = f"""
            SELECT
                asset_id, tenant_id, resource_uid, provider, account_id,
                region, resource_type, resource_id, name, tags,
                scan_run_id, latest_scan_run_id, updated_at,
                properties
            FROM inventory_findings
            WHERE {where_clause}
            ORDER BY resource_type, resource_uid
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        # Convert to asset schema format
        assets = []
        for row in rows:
            rt = row["resource_type"] or ""
            assets.append(self._row_to_asset(row, rt))

        # Back-fill last_scanned from scan_orchestration for assets missing it
        self._backfill_last_scanned(assets)

        return assets, total

    @staticmethod
    def _extract_service(resource_type: str) -> str:
        """Extract service name from resource_type (e.g., 's3.bucket' -> 's3')."""
        if "." in resource_type:
            return resource_type.split(".")[0]
        return resource_type

    @staticmethod
    def _row_to_asset(row: Dict[str, Any], resource_type: str) -> Dict[str, Any]:
        """Convert a DB row to the UI-ready asset schema."""
        updated = row.get("updated_at")
        tags = row.get("tags") or {}
        return {
            "schema_version": "cspm_asset.v1",
            "tenant_id": row["tenant_id"],
            "scan_run_id": row.get("scan_run_id") or row.get("latest_scan_run_id"),
            "provider": row["provider"],
            "account_id": row["account_id"],
            "region": row["region"] or "global",
            "scope": row["region"] or "global",
            "resource_type": resource_type,
            "resource_id": row["resource_id"],
            "resource_uid": row["resource_uid"],
            "name": row.get("name"),
            "resource_name": row.get("name") or row["resource_uid"].rsplit("/", 1)[-1],
            "service": InventoryDBLoader._extract_service(resource_type),
            "status": "active",
            "last_scanned": updated.isoformat() if updated else None,
            "tags": tags,
            "metadata": row.get("properties") or {},
        }
    
    @staticmethod
    def _backfill_last_scanned(assets: List[Dict[str, Any]]) -> None:
        """Resolve last_scanned for assets where updated_at was NULL.

        Looks up scan_orchestration.completed_at (or started_at) in the
        onboarding DB using each asset's scan_run_id.  A single
        batch query covers all distinct scan IDs in the page.
        """
        need = {
            a["scan_run_id"]
            for a in assets
            if not a.get("last_scanned") and a.get("scan_run_id")
        }
        if not need:
            return

        try:
            from providers.common.orchestration import _get_orchestration_conn
            conn = _get_orchestration_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT inventory_scan_id,
                               COALESCE(completed_at, started_at) AS ts
                        FROM scan_orchestration
                        WHERE inventory_scan_id = ANY(%s::text[])
                        """,
                        (list(need),),
                    )
                    ts_map = {r[0]: r[1] for r in cur.fetchall() if r[1]}
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Could not resolve last_scanned from scan_orchestration: %s", exc)
            return

        for a in assets:
            if not a.get("last_scanned") and a.get("scan_run_id"):
                ts = ts_map.get(a["scan_run_id"])
                if ts:
                    a["last_scanned"] = ts.isoformat()

    def load_asset_by_uid(
        self,
        tenant_id: str,
        resource_uid: str,
        scan_run_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load a specific asset by resource_uid.
        
        Returns:
            Asset dictionary or None if not found
        """
        where_parts = ["tenant_id = %s", "resource_uid = %s"]
        params = [tenant_id, resource_uid]
        
        if scan_run_id:
            where_parts.append("scan_run_id = %s")
            params.append(scan_run_id)

        where_clause = " AND ".join(where_parts)

        query = f"""
            SELECT
                asset_id, tenant_id, resource_uid, provider, account_id,
                region, resource_type, resource_id, name, tags,
                scan_run_id, latest_scan_run_id, updated_at,
                configuration, properties
            FROM inventory_findings
            WHERE {where_clause}
            LIMIT 1
        """

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()

        if not row:
            return None

        rt = row["resource_type"] or ""
        asset = self._row_to_asset(row, rt)
        # Asset detail gets extra fields not in list view
        asset["config"] = row.get("configuration") or row.get("properties") or {}
        return asset
    
    def load_relationships(
        self,
        tenant_id: str,
        scan_run_id: Optional[str] = None,
        from_uid: Optional[str] = None,
        to_uid: Optional[str] = None,
        relation_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Load relationships from DB with filtering and pagination.
        
        Returns:
            Tuple of (relationships list, total_count)
        """
        where_parts = ["tenant_id = %s"]
        params = [tenant_id]

        # Resolve scan_run_id: if given but has 0 relationships, fall back to
        # the latest scan that actually produced relationships for this tenant.
        effective_scan = scan_run_id
        if effective_scan:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM inventory_relationships WHERE tenant_id = %s AND scan_run_id = %s",
                    (tenant_id, effective_scan),
                )
                if cur.fetchone()[0] == 0:
                    cur.execute(
                        "SELECT scan_run_id FROM inventory_relationships WHERE tenant_id = %s "
                        "ORDER BY created_at DESC LIMIT 1",
                        (tenant_id,),
                    )
                    row = cur.fetchone()
                    effective_scan = row[0] if row else None

        if effective_scan:
            where_parts.append("scan_run_id = %s")
            params.append(effective_scan)

        if from_uid:
            where_parts.append("from_uid = %s")
            params.append(from_uid)

        if to_uid:
            where_parts.append("to_uid = %s")
            params.append(to_uid)

        if relation_type:
            where_parts.append("relation_type = %s")
            params.append(relation_type)

        where_clause = " AND ".join(where_parts)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM inventory_relationships WHERE {where_clause}"
        with self.conn.cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()[0]
        
        # Get paginated results
        query = f"""
            SELECT
                relationship_id, tenant_id, scan_run_id, provider,
                account_id, region, relation_type, from_uid, to_uid,
                properties, created_at
            FROM inventory_relationships
            WHERE {where_clause}
            ORDER BY relation_type, from_uid
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        
        # Convert to relationship schema format
        relationships = []
        for row in rows:
            relationships.append({
                "schema_version": "cspm_relationship.v1",
                "tenant_id": row["tenant_id"],
                "scan_run_id": row["scan_run_id"],
                "provider": row["provider"],
                "account_id": row["account_id"],
                "region": row["region"] or "global",
                "relation_type": row["relation_type"],
                "from_uid": row["from_uid"],
                "to_uid": row["to_uid"],
                "properties": row["properties"] or {}
            })
        
        return relationships, total
    
    def get_scan_summary(
        self,
        tenant_id: str,
        scan_run_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get scan summary from inventory_report.

        Returns:
            Summary dict or None if not found
        """
        query = """
            SELECT
                scan_run_id, tenant_id, started_at, completed_at, status,
                total_assets, total_relationships,
                assets_by_provider, assets_by_resource_type, assets_by_region,
                providers_scanned, accounts_scanned, regions_scanned,
                errors_count
            FROM inventory_report
            WHERE tenant_id = %s AND scan_run_id = %s
        """

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (tenant_id, scan_run_id))
            row = cur.fetchone()

        if not row:
            return None

        result = dict(row)

        # Enrich with drift KPIs from inventory_drift
        try:
            drift_query = """
                SELECT change_type, COUNT(*) AS cnt
                FROM inventory_drift
                WHERE tenant_id = %s AND scan_run_id = %s
                GROUP BY change_type
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(drift_query, (tenant_id, scan_run_id))
                drift_rows = cur.fetchall()
            added = 0
            removed = 0
            changed = 0
            for dr in drift_rows:
                ct = (dr.get("change_type") or "").lower()
                c = dr.get("cnt", 0)
                if "added" in ct or "new" in ct:
                    added += c
                elif "removed" in ct or "deleted" in ct:
                    removed += c
                else:
                    changed += c
            result["drift_summary"] = {
                "total_drift": added + removed + changed,
                "assets_added": added,
                "assets_removed": removed,
                "assets_changed": changed,
            }
        except Exception:
            result["drift_summary"] = {
                "total_drift": 0,
                "assets_added": 0,
                "assets_removed": 0,
                "assets_changed": 0,
            }

        return result

    def get_latest_scan_id(self, tenant_id: str) -> Optional[str]:
        """Get latest scan_run_id with actual findings for tenant."""
        # Try completed report first
        query = """
            SELECT scan_run_id FROM inventory_report
            WHERE tenant_id = %s AND status = 'completed' AND total_assets > 0
            ORDER BY completed_at DESC LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(query, (tenant_id,))
            row = cur.fetchone()
            if row:
                return row[0]
            # Fallback: latest scan_run_id with actual findings
            cur.execute("""
                SELECT scan_run_id, COUNT(*) AS cnt
                FROM inventory_findings
                WHERE tenant_id = %s
                GROUP BY scan_run_id
                ORDER BY MAX(last_seen_at) DESC NULLS LAST, cnt DESC
                LIMIT 1
            """, (tenant_id,))
            row = cur.fetchone()
        return row[0] if row else None
    
    # ── Drift enrichment helpers ────────────────────────────────────────

    def _load_asset_snapshot(
        self, tenant_id: str, resource_uid: str,
    ) -> Dict[str, Any]:
        """Load current asset snapshot from inventory_findings for drift enrichment."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT name, resource_type, region, account_id,
                           tags, configuration, properties
                    FROM inventory_findings
                    WHERE tenant_id = %s AND resource_uid = %s
                    LIMIT 1
                """, (tenant_id, resource_uid))
                row = cur.fetchone()
                if not row:
                    return {}
                snap: Dict[str, Any] = {}
                for key in ("name", "resource_type", "region", "account_id"):
                    if row.get(key):
                        snap[key] = row[key]
                tags = row.get("tags")
                if isinstance(tags, str):
                    import json as _json
                    tags = _json.loads(tags)
                if tags and isinstance(tags, dict):
                    snap["tags"] = tags
                config = row.get("configuration")
                if isinstance(config, str):
                    import json as _json
                    config = _json.loads(config)
                if config and isinstance(config, dict):
                    for k, v in config.items():
                        snap[f"config.{k}"] = v
                props = row.get("properties")
                if isinstance(props, str):
                    import json as _json
                    props = _json.loads(props)
                if props and isinstance(props, dict):
                    _skip = {"raw_refs", "emitted_fields", "enriched_from",
                             "discovery_id", "scan_timestamp", "created_at",
                             "last_scanned", "first_seen_at"}
                    for k, v in props.items():
                        if k not in _skip:
                            snap[k] = v
                return snap
        except Exception as e:
            logger.debug(f"Asset snapshot lookup failed: {e}")
            return {}

    def _load_scan_snapshots(
        self, resource_uid: str, scan_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Load asset snapshots from inventory_scan_data for specific scan IDs.

        Returns {scan_run_id: {flattened config/tags/props dict}}.
        """
        if not scan_ids:
            return {}
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                placeholders = ",".join(["%s"] * len(scan_ids))
                cur.execute(f"""
                    SELECT inventory_scan_id AS scan_run_id,
                           name, tags, properties, configuration
                    FROM inventory_scan_data
                    WHERE resource_uid = %s
                      AND inventory_scan_id IN ({placeholders})
                """, [resource_uid] + scan_ids)
                rows = cur.fetchall()

            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                snap: Dict[str, Any] = {}
                if row.get("name"):
                    snap["name"] = row["name"]

                for col in ("tags", "configuration", "properties"):
                    val = row.get(col)
                    if isinstance(val, str):
                        import json as _json
                        val = _json.loads(val)
                    if not val or not isinstance(val, dict):
                        continue
                    prefix = "config." if col == "configuration" else (
                        "tags." if col == "tags" else ""
                    )
                    for k, v in val.items():
                        if k in ("raw_refs", "emitted_fields", "enriched_from"):
                            continue
                        snap[f"{prefix}{k}"] = v

                result[row["scan_run_id"]] = snap
            return result
        except Exception as e:
            logger.debug(f"Scan snapshot lookup failed: {e}")
            return {}

    @staticmethod
    def _diff_snapshots(
        prev: Dict[str, Any], curr: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Compute field-level changes between two flattened snapshots."""
        changes: List[Dict[str, Any]] = []
        all_keys = set(prev.keys()) | set(curr.keys())
        # Skip noisy keys that change every scan
        ignore = {"first_seen_at", "created_at", "discovery_id", "last_scanned",
                  "emitted_fields", "enriched_from", "raw_refs"}
        for key in sorted(all_keys):
            if key in ignore:
                continue
            pv = prev.get(key)
            cv = curr.get(key)
            if pv != cv:
                changes.append({"path": key, "before": pv, "after": cv})
        return changes

    def _enrich_empty_drift(
        self, changes: List[Dict[str, Any]], tenant_id: str, resource_uid: str,
    ) -> None:
        """Fill in empty changes_summary records using scan snapshots.

        Modifies the change dicts in-place. For asset_added/removed, builds a
        snapshot from inventory_findings. For asset_changed, diffs the two scan
        snapshots from inventory_scan_data.
        """
        # Identify which records need enrichment
        needs_snapshot_diff: List[Dict[str, Any]] = []  # asset_changed needing scan pair
        needs_identity: List[Dict[str, Any]] = []       # asset_added/removed needing resource info

        for c in changes:
            summary = c.get("changes_summary")
            if summary and summary != {}:
                continue  # already has data
            ct = (c.get("change_type") or "").lower()
            if "change" in ct or "modif" in ct:
                needs_snapshot_diff.append(c)
            else:
                needs_identity.append(c)

        if not needs_snapshot_diff and not needs_identity:
            return

        # ── Enrich asset_added / asset_removed ──────────────────────────
        if needs_identity:
            snap = self._load_asset_snapshot(tenant_id, resource_uid)
            if snap:
                for c in needs_identity:
                    ct = (c.get("change_type") or "").lower()
                    c["changes_summary"] = {"snapshot": snap}
                    if "add" in ct:
                        c["current_state"] = snap
                    elif "remov" in ct:
                        c["previous_state"] = snap

        # ── Enrich asset_changed via scan snapshot diffs ────────────────
        if needs_snapshot_diff:
            # Collect unique scan IDs we need
            scan_ids_needed: set = set()
            for c in needs_snapshot_diff:
                if c.get("scan_run_id"):
                    scan_ids_needed.add(c["scan_run_id"])
                if c.get("previous_scan_id"):
                    scan_ids_needed.add(c["previous_scan_id"])

            if scan_ids_needed:
                snapshots = self._load_scan_snapshots(
                    resource_uid, list(scan_ids_needed)
                )
                for c in needs_snapshot_diff:
                    prev_snap = snapshots.get(c.get("previous_scan_id", ""), {})
                    curr_snap = snapshots.get(c.get("scan_run_id", ""), {})
                    if prev_snap or curr_snap:
                        field_changes = self._diff_snapshots(prev_snap, curr_snap)
                        if field_changes:
                            c["changes_summary"] = {"changes": field_changes}
                            c["previous_state"] = {
                                ch["path"]: ch["before"] for ch in field_changes
                            }
                            c["current_state"] = {
                                ch["path"]: ch["after"] for ch in field_changes
                            }

    # ── Main drift loader ───────────────────────────────────────────────

    def load_asset_drift(
        self,
        tenant_id: str,
        resource_uid: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Load drift history for a specific asset from inventory_drift table.

        Enriches empty changes_summary records by reconstructing diffs from
        inventory_scan_data snapshots (for asset_changed) or building identity
        snapshots from inventory_findings (for asset_added/removed).
        """
        query = """
            SELECT drift_id, inventory_scan_id AS scan_run_id, previous_scan_id,
                   change_type, previous_state, current_state,
                   changes_summary, severity, detected_at
            FROM inventory_drift
            WHERE tenant_id = %s AND resource_uid = %s
            ORDER BY detected_at DESC
            LIMIT %s
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (tenant_id, resource_uid, limit))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Asset drift query failed: {e}")
            return {"last_check": None, "has_drift": False, "changes": [], "total": 0}

        changes = []
        for r in rows:
            detected = r.get("detected_at")
            summary = r.get("changes_summary")
            if isinstance(summary, str):
                try:
                    import json
                    summary = json.loads(summary)
                except Exception:
                    summary = {}
            changes.append({
                "drift_id": str(r.get("drift_id", "")),
                "scan_run_id": r.get("scan_run_id", ""),
                "previous_scan_id": r.get("previous_scan_id", ""),
                "change_type": r.get("change_type", "modified"),
                "severity": r.get("severity", "medium"),
                "previous_state": r.get("previous_state") or {},
                "current_state": r.get("current_state") or {},
                "changes_summary": summary or {},
                "detected_at": detected.isoformat() if detected else None,
            })

        # Enrich records that have empty changes_summary (historical data)
        if changes:
            try:
                self._enrich_empty_drift(changes, tenant_id, resource_uid)
            except Exception as e:
                logger.debug(f"Drift enrichment failed for {resource_uid}: {e}")

        last_check = changes[0]["detected_at"] if changes else None
        return {
            "last_check": last_check,
            "has_drift": len(changes) > 0,
            "changes": changes,
            "total": len(changes),
        }

    def load_drift_records(
        self,
        tenant_id: str,
        scan_run_id: Optional[str] = None,
        provider: Optional[str] = None,
        change_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Load drift records with resource_name join and flattened values for the UI."""
        where_parts = ["d.tenant_id = %s"]
        params: list = [tenant_id]

        if scan_run_id:
            where_parts.append("d.scan_run_id = %s")
            params.append(scan_run_id)
        if provider:
            where_parts.append("d.provider = %s")
            params.append(provider)
        if change_type:
            where_parts.append("d.change_type = %s")
            params.append(change_type)

        where_clause = " AND ".join(where_parts)

        query = f"""
            SELECT
                d.drift_id, d.resource_uid, d.resource_type, d.change_type,
                d.changes_summary, d.severity, d.detected_at,
                d.provider,
                f.account_id, f.region,
                f.name AS resource_name
            FROM inventory_drift d
            LEFT JOIN inventory_findings f
                ON f.resource_uid = d.resource_uid AND f.tenant_id = d.tenant_id
            WHERE {where_clause}
            ORDER BY d.detected_at DESC
            LIMIT %s
        """
        params.append(limit)

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Drift records query failed: {e}")
            return []

        records = []
        for r in rows:
            detected = r.get("detected_at")
            summary = r.get("changes_summary")
            if isinstance(summary, str):
                try:
                    import json
                    summary = json.loads(summary)
                except Exception:
                    summary = {}
            # Flatten changes_summary into previous_value / new_value
            prev_val, new_val = "", ""
            if isinstance(summary, dict):
                # Could be {"field": {"before": X, "after": Y}} or list
                for field, change in summary.items():
                    if isinstance(change, dict):
                        prev_val = str(change.get("before", ""))
                        new_val = str(change.get("after", ""))
                        break
            elif isinstance(summary, list) and summary:
                entry = summary[0]
                if isinstance(entry, dict):
                    prev_val = str(entry.get("before", ""))
                    new_val = str(entry.get("after", ""))

            uid = r.get("resource_uid", "")
            records.append({
                "drift_id": str(r.get("drift_id", "")),
                "resource_uid": uid,
                "resource_name": r.get("resource_name") or uid.rsplit("/", 1)[-1],
                "resource_type": r.get("resource_type", ""),
                "drift_type": (r.get("change_type") or "modified").replace("_", " "),
                "previous_value": prev_val,
                "new_value": new_val,
                "severity": r.get("severity", "medium"),
                "timestamp": detected.isoformat() if detected else None,
                "provider": r.get("provider", ""),
                "account_id": r.get("account_id", ""),
                "region": r.get("region", ""),
            })
        return records

    # ------------------------------------------------------------------
    # Graph BFS traversal (multi-cloud)
    # ------------------------------------------------------------------

    # Root container types across all supported cloud providers
    _ROOT_TYPES = [
        'ec2.vpc',                       # AWS
        'network.virtual-network',       # Azure
        'vpc.vpc', 'compute.network',    # GCP
        'core.vcn', 'vcn.vcn',          # OCI
        'is.vpc',                        # IBM
    ]

    # All relation types for BFS graph walking — traverse EVERY known edge
    # so the BFS discovers IAM roles (assumes), KMS keys (encrypted_by),
    # Lambda functions (triggers/invokes), ALBs (serves_traffic_for), etc.
    # The UI layer decides which edges render as lines vs. reference badges.
    _STRUCTURAL_TYPES = [
        # containment / membership
        'contained_by', 'contains', 'member_of',
        # connectivity / routing
        'attached_to', 'routes_to', 'connected_to', 'allows_traffic_from',
        # compute / execution
        'uses', 'assumes', 'runs_on', 'deployed_by', 'depends_on',
        'triggers', 'invokes', 'scales_with',
        # traffic / exposure
        'serves_traffic_for', 'exposed_through', 'resolves_to',
        # security / access
        'controlled_by', 'has_policy', 'grants_access_to',
        'authenticated_by', 'protected_by',
        # data / storage
        'stores_data_in', 'backs_up_to', 'replicates_to',
        'encrypted_by', 'cached_by',
        # observability / governance
        'logging_enabled_to', 'monitored_by', 'scanned_by',
        'manages', 'complies_with',
        # messaging
        'publishes_to', 'subscribes_to',
        # network layers (on-prem / hybrid)
        '1st_layer', '2nd_layer', '3rd_layer', '4th_layer',
        'on_prem_datacenter',
        # internet exposure (also loaded separately in Step 6)
        'internet_connected',
    ]

    # Global service type prefixes (multi-cloud)
    _GLOBAL_SERVICE_PREFIXES = [
        'iam.%', 's3.%', 'kms.%', 'cloudwatch.%', 'route53.%',
        'cloudfront.%', 'cloudtrail.%', 'config.%', 'acm.%',
        'waf.%', 'guardduty.%', 'sns.%', 'sqs.%', 'dynamodb.%',
        # Azure
        'keyvault.%', 'monitor.%', 'authorization.%',
        # GCP
        'cloudkms.%', 'logging.%', 'pubsub.%',
        # OCI
        'identity.%', 'objectstorage.%',
    ]

    def load_graph_bfs(
        self,
        tenant_id: str,
        scan_run_id: Optional[str] = None,
        max_depth: int = 5,
        max_nodes: int = 2000,
    ) -> Dict[str, Any]:
        """
        Load graph data using recursive CTE BFS traversal.

        Algorithm:
        1. Seed with VPC/VNet/VCN root containers
        2. Walk structural edges up to max_depth hops
        3. Batch load all discovered assets
        4. Load ALL relationships between discovered nodes
        5. Separately load global-service assets referenced by relationships
        6. Include exposure relationships (internet_connected, exposed_through)

        Returns:
            Dict with keys: nodes (list), relationships (list), exposure (list)
        """
        # Resolve effective scan
        effective_scan = self._resolve_scan_id(tenant_id, scan_run_id)
        if not effective_scan:
            return {"nodes": [], "relationships": [], "exposure": []}

        # Step 1-2: Recursive CTE to discover all graph node UIDs
        cte_query = """
            WITH RECURSIVE graph_walk AS (
                -- Seed: VPC/VNet/VCN root nodes
                SELECT resource_uid AS node_uid, 0 AS depth,
                       ARRAY[resource_uid] AS path
                FROM inventory_findings
                WHERE tenant_id = %(tenant_id)s
                  AND scan_run_id = %(scan_id)s
                  AND resource_type = ANY(%(root_types)s)

                UNION ALL

                -- Walk structural edges (bidirectional)
                SELECT
                    CASE WHEN ir.from_uid = gw.node_uid
                         THEN ir.to_uid ELSE ir.from_uid END AS node_uid,
                    gw.depth + 1,
                    gw.path || CASE WHEN ir.from_uid = gw.node_uid
                                    THEN ir.to_uid ELSE ir.from_uid END
                FROM graph_walk gw
                JOIN inventory_relationships ir
                  ON ir.tenant_id = %(tenant_id)s
                 AND ir.scan_run_id = %(scan_id)s
                 AND (ir.from_uid = gw.node_uid OR ir.to_uid = gw.node_uid)
                 AND ir.relation_type = ANY(%(structural_types)s)
                WHERE gw.depth < %(max_depth)s
                  AND NOT (
                    CASE WHEN ir.from_uid = gw.node_uid
                         THEN ir.to_uid ELSE ir.from_uid END
                    = ANY(gw.path)
                  )
            )
            SELECT DISTINCT node_uid FROM graph_walk
            LIMIT %(max_nodes)s
        """

        params = {
            "tenant_id": tenant_id,
            "scan_id": effective_scan,
            "root_types": self._ROOT_TYPES,
            "structural_types": self._STRUCTURAL_TYPES,
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        }

        try:
            with self.conn.cursor() as cur:
                cur.execute(cte_query, params)
                discovered_uids = [row[0] for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Graph BFS CTE failed: {e}")
            self.conn.rollback()
            return {"nodes": [], "relationships": [], "exposure": []}

        if not discovered_uids:
            return {"nodes": [], "relationships": [], "exposure": []}

        # Step 3: Batch load assets for discovered UIDs
        nodes = []
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT DISTINCT ON (resource_uid)
                       resource_uid, name, resource_type, provider,
                       account_id, region, tags, labels, properties, configuration
                    FROM inventory_findings
                    WHERE tenant_id = %s AND resource_uid = ANY(%s)
                    ORDER BY resource_uid, updated_at DESC""",
                    (tenant_id, discovered_uids),
                )
                nodes = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Graph BFS asset load failed: {e}")
            self.conn.rollback()

        # Step 4: Load ALL relationships where both endpoints are discovered
        relationships = []
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT from_uid, to_uid, relation_type,
                           from_resource_type, to_resource_type,
                           provider, account_id, region, properties
                    FROM inventory_relationships
                    WHERE tenant_id = %s AND scan_run_id = %s
                      AND from_uid = ANY(%s) AND to_uid = ANY(%s)""",
                    (tenant_id, effective_scan, discovered_uids, discovered_uids),
                )
                relationships = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Graph BFS relationship load failed: {e}")
            self.conn.rollback()

        # Step 5: Load global-service assets referenced by discovered relationships
        global_nodes = []
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT DISTINCT ON (f.resource_uid)
                       f.resource_uid, f.name, f.resource_type, f.provider,
                       f.account_id, f.region, f.tags, f.properties, f.configuration
                    FROM inventory_findings f
                    WHERE f.tenant_id = %s
                      AND f.resource_uid IN (
                          SELECT DISTINCT to_uid FROM inventory_relationships
                          WHERE tenant_id = %s AND scan_run_id = %s
                            AND from_uid = ANY(%s)
                            AND to_resource_type LIKE ANY(%s)
                      )
                      AND f.resource_uid != ALL(%s)
                    ORDER BY f.resource_uid, f.updated_at DESC""",
                    (
                        tenant_id, tenant_id, effective_scan,
                        discovered_uids, self._GLOBAL_SERVICE_PREFIXES,
                        discovered_uids,
                    ),
                )
                global_nodes = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Graph BFS global services load failed: {e}")
            self.conn.rollback()

        # Also load relationships TO global nodes
        global_uids = [n["resource_uid"] for n in global_nodes]
        global_rels = []
        if global_uids:
            try:
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT from_uid, to_uid, relation_type,
                               from_resource_type, to_resource_type,
                               provider, account_id, region, properties
                        FROM inventory_relationships
                        WHERE tenant_id = %s AND scan_run_id = %s
                          AND from_uid = ANY(%s) AND to_uid = ANY(%s)""",
                        (tenant_id, effective_scan, discovered_uids, global_uids),
                    )
                    global_rels = [dict(r) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Graph BFS global-rel load failed: {e}")

        # Step 6: Load exposure relationships
        exposure = []
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT from_uid, to_uid, relation_type, properties
                    FROM inventory_relationships
                    WHERE tenant_id = %s AND scan_run_id = %s
                      AND from_uid = ANY(%s)
                      AND relation_type IN ('internet_connected', 'internet_accessible',
                                            'exposed_through')""",
                    (tenant_id, effective_scan, discovered_uids),
                )
                exposure = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Graph BFS exposure load failed: {e}")

        # Step 7: Supplement with orphan resources not reached by BFS
        # Ensures IAM, Lambda, S3, etc. show up even without relationships.
        # Excludes known junk types and orders by resource_type to get
        # a diverse mix (not all from the same type).
        all_discovered = set(discovered_uids + global_uids)
        remaining_capacity = max_nodes - len(all_discovered)
        orphan_nodes = []
        orphan_rels = []

        # Junk types to exclude from orphan supplement
        _JUNK_TYPES = [
            'ec2.vpc_block_public_access_exclusion_resource',
            'ec2.vpc_block_public_access_exclusion',
            'ec2.local_gateway_route_table_vpc_association_local_gateway_route_table',
            'ec2.local_gateway_route_table_vpc_association',
        ]

        if remaining_capacity > 0:
            try:
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT DISTINCT ON (resource_uid)
                               resource_uid, name, resource_type, provider,
                               account_id, region, tags, properties, configuration
                        FROM inventory_findings
                        WHERE tenant_id = %s
                          AND resource_uid != ALL(%s)
                          AND resource_type != ALL(%s)
                        ORDER BY resource_uid, updated_at DESC
                        LIMIT %s""",
                        (tenant_id, list(all_discovered), _JUNK_TYPES,
                         remaining_capacity),
                    )
                    orphan_nodes = [dict(r) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Graph BFS orphan supplement failed: {e}")

            # Also load any relationships between orphan nodes and discovered nodes
            orphan_uids = [n["resource_uid"] for n in orphan_nodes]
            if orphan_uids:
                all_uids = list(all_discovered) + orphan_uids
                try:
                    with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute(
                            """SELECT from_uid, to_uid, relation_type,
                                   from_resource_type, to_resource_type,
                                   provider, account_id, region, properties
                            FROM inventory_relationships
                            WHERE tenant_id = %s AND scan_run_id = %s
                              AND from_uid = ANY(%s) AND to_uid = ANY(%s)
                              AND NOT (from_uid = ANY(%s) AND to_uid = ANY(%s))""",
                            (
                                tenant_id, effective_scan,
                                all_uids, all_uids,
                                list(all_discovered), list(all_discovered),
                            ),
                        )
                        orphan_rels = [dict(r) for r in cur.fetchall()]
                except Exception as e:
                    logger.warning(f"Graph BFS orphan-rel load failed: {e}")

        # Merge all nodes + relationships
        all_nodes = nodes + global_nodes + orphan_nodes
        all_rels = relationships + global_rels + orphan_rels

        return {
            "nodes": all_nodes,
            "relationships": all_rels,
            "exposure": exposure,
        }

    def _resolve_scan_id(
        self, tenant_id: str, scan_run_id: Optional[str]
    ) -> Optional[str]:
        """Resolve effective scan_run_id with fallback to latest."""
        effective_scan = scan_run_id
        if effective_scan and effective_scan != "latest":
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM inventory_relationships "
                    "WHERE tenant_id = %s AND scan_run_id = %s",
                    (tenant_id, effective_scan),
                )
                if cur.fetchone()[0] == 0:
                    effective_scan = None

        if not effective_scan or effective_scan == "latest":
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT scan_run_id FROM inventory_relationships "
                    "WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                    (tenant_id,),
                )
                row = cur.fetchone()
                effective_scan = row[0] if row else None

        return effective_scan

    def close(self):
        """Close database connection"""
        try:
            self.conn.close()
        except Exception:
            pass
