"""
Index Writer

Writes searchable indexes to Postgres/DynamoDB for UI queries.

=== DATABASE & TABLE MAP ===
Database: threat_engine_inventory (INVENTORY DB)
Env: INVENTORY_DB_HOST / INVENTORY_DB_PORT / INVENTORY_DB_NAME / INVENTORY_DB_USER / INVENTORY_DB_PASSWORD
     (connection URL passed from orchestrator via get_database_config)

Tables WRITTEN:
  - inventory_report        : write_scan_summary(ScanSummary)
                              — INSERT ... ON CONFLICT (scan_run_id) DO UPDATE
  - inventory_findings      : write_asset_index(assets)
                              — INSERT ... ON CONFLICT (asset_id) DO UPDATE (latest state only)
  - inventory_scan_data     : write_scan_snapshot(assets)
                              — INSERT per asset per scan (historical snapshots, 5 retained)
  - inventory_relationships : write_relationship_index(relationships)
                              — INSERT per relationship edge

Tables READ: None (write-only module)
===
"""

import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from ..schemas.asset_schema import Asset, generate_finding_id
from ..schemas.relationship_schema import Relationship
from ..schemas.summary_schema import ScanSummary

logger = logging.getLogger(__name__)


class IndexWriter:
    """Writes indexes to database"""
    
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url
    
    def write_scan_summary(self, summary: ScanSummary):
        """Write scan summary to inventory_scans"""
        # TODO: Implement Postgres write
        pass
    
    def write_asset_index(self, assets: List[Asset]):
        """Write latest asset state to inventory_findings"""
        # TODO: Implement Postgres/DynamoDB write
        pass
    
    def write_relationship_index(self, relationships: List[Relationship]):
        """Write relationship index (optional)"""
        # TODO: Implement if needed
        pass


def _db_url_with_search_path(url: str) -> str:
    """Append options=search_path to URL when DB_SCHEMA is set (consolidated DB)."""
    import os
    schema = (os.getenv("DB_SCHEMA") or "").strip()
    if not schema:
        return url
    sep = "&" if "?" in url else "?"
    opts = f"options=-c%20search_path%3D{schema.replace(',', '%2C')}"
    return f"{url}{sep}{opts}"


class PostgresIndexWriter(IndexWriter):
    """Postgres implementation of index writer"""

    def __init__(self, db_url: str):
        super().__init__(db_url)
        import psycopg2
        self.conn = psycopg2.connect(_db_url_with_search_path(db_url))
    
    def _ensure_tenant(self, tenant_id: str) -> None:
        """Upsert tenant row to satisfy FK constraints on inventory tables."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO tenants (tenant_id, tenant_name)
            VALUES (%s, %s)
            ON CONFLICT (tenant_id) DO NOTHING
        """, (tenant_id, tenant_id))
        self.conn.commit()

    def write_scan_summary(self, summary: ScanSummary):
        """Write to inventory_report table"""
        self._ensure_tenant(summary.tenant_id)
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO inventory_report (
                scan_run_id, tenant_id, started_at, completed_at, status,
                total_assets, total_relationships, assets_by_provider,
                assets_by_resource_type, assets_by_region, providers_scanned,
                accounts_scanned, regions_scanned, errors_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scan_run_id) DO UPDATE SET
                completed_at = EXCLUDED.completed_at,
                status = EXCLUDED.status,
                total_assets = EXCLUDED.total_assets,
                total_relationships = EXCLUDED.total_relationships
        """, (
            summary.scan_run_id, summary.tenant_id,
            summary.started_at, summary.completed_at, summary.status,
            summary.total_assets, summary.total_relationships,
            json.dumps(summary.assets_by_provider),
            json.dumps(summary.assets_by_resource_type),
            json.dumps(summary.assets_by_region),
            json.dumps(summary.providers_scanned),
            json.dumps(summary.accounts_scanned),
            json.dumps(summary.regions_scanned),
            summary.errors_count
        ))
        self.conn.commit()
    
    def write_asset_index(self, assets: List[Asset]):
        """Write to inventory_findings table"""
        import json
        cursor = self.conn.cursor()

        def _serialize_value(obj):
            """Convert datetime and other non-JSON-serializable objects to strings"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: _serialize_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_serialize_value(item) for item in obj]
            return obj

        for asset in assets:
            finding_id = generate_finding_id(asset)

            # Extract enrichment data from metadata
            configuration = asset.metadata.get('configuration', {}) if asset.metadata else {}
            labels = asset.metadata.get('labels', {}) if asset.metadata else {}
            properties = {k: v for k, v in asset.metadata.items() if k not in ['configuration', 'labels', 'raw_refs']} if asset.metadata else {}

            # Serialize datetime objects
            configuration = _serialize_value(configuration)
            labels = _serialize_value(labels)
            properties = _serialize_value(properties)

            # Remove stale row if resource_uid exists under a different asset_id
            # (handles the dual unique constraint: PK on asset_id + UNIQUE on resource_uid,tenant_id)
            cursor.execute(
                "DELETE FROM inventory_findings WHERE resource_uid = %s AND tenant_id = %s AND asset_id != %s",
                (asset.resource_uid, asset.tenant_id, finding_id),
            )

            # Extract new identifier-driven fields from metadata
            source_ids = json.dumps(getattr(asset, 'source_discovery_ids', []) or
                                     (asset.metadata or {}).get('source_discovery_ids', []))
            identifier_key = getattr(asset, 'identifier_key', None) or \
                             (asset.metadata or {}).get('identifier_key', '')
            scope_val = getattr(asset, 'scope', None) or \
                        (asset.metadata or {}).get('scope', '')
            category_val = getattr(asset, 'category', None) or \
                           (asset.metadata or {}).get('category', '')
            managed_by_val = getattr(asset, 'managed_by', None) or \
                             (asset.metadata or {}).get('managed_by', '')
            is_container_val = getattr(asset, 'is_container', False) or \
                               (asset.metadata or {}).get('is_container', False)
            container_parent_val = getattr(asset, 'container_parent', None) or \
                                   (asset.metadata or {}).get('container_parent', '')

            cursor.execute("""
                INSERT INTO inventory_findings (
                    asset_id, tenant_id, resource_uid, provider, account_id,
                    region, resource_type, resource_id, name, tags, labels,
                    properties, configuration,
                    scan_run_id, latest_scan_run_id, updated_at,
                    source_discovery_ids, identifier_key, scope, category,
                    managed_by, is_container, container_parent
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    resource_uid = EXCLUDED.resource_uid,
                    resource_type = EXCLUDED.resource_type,
                    resource_id = EXCLUDED.resource_id,
                    name = EXCLUDED.name,
                    tags = EXCLUDED.tags,
                    labels = EXCLUDED.labels,
                    properties = EXCLUDED.properties,
                    configuration = EXCLUDED.configuration,
                    scan_run_id = EXCLUDED.scan_run_id,
                    latest_scan_run_id = EXCLUDED.latest_scan_run_id,
                    updated_at = EXCLUDED.updated_at,
                    source_discovery_ids = EXCLUDED.source_discovery_ids,
                    identifier_key = EXCLUDED.identifier_key,
                    scope = EXCLUDED.scope,
                    category = EXCLUDED.category,
                    managed_by = EXCLUDED.managed_by,
                    is_container = EXCLUDED.is_container,
                    container_parent = EXCLUDED.container_parent
            """, (
                finding_id, asset.tenant_id, asset.resource_uid,
                asset.provider.value, asset.account_id, asset.region,
                asset.resource_type, asset.resource_id, asset.name,
                json.dumps(asset.tags), json.dumps(labels),
                json.dumps(properties), json.dumps(configuration),
                asset.scan_run_id, asset.scan_run_id,
                datetime.now(timezone.utc),
                source_ids, identifier_key, scope_val, category_val,
                managed_by_val, is_container_val, container_parent_val,
            ))

        self.conn.commit()
    
    def write_relationship_index(self, relationships: List[Relationship]):
        """Write to inventory_relationships table.

        TODO: migrate to new columns only (source_resource_uid, target_resource_uid,
        relationship_type) and drop legacy from_uid/to_uid/relation_type once all
        readers (threat_analyzer, graph_builder, blast-radius queries) are updated.
        """
        if not relationships:
            return

        cursor = self.conn.cursor()

        for rel in relationships:
            provider_val = rel.provider.value if hasattr(rel.provider, 'value') else str(rel.provider)
            cursor.execute("""
                INSERT INTO inventory_relationships (
                    tenant_id, scan_run_id, provider, account_id, region,
                    relation_type, from_uid, to_uid, from_resource_type, to_resource_type, properties,
                    source_resource_uid, target_resource_uid, relationship_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                rel.tenant_id, rel.scan_run_id, provider_val,
                rel.account_id, rel.region, rel.relation_type,
                rel.from_uid, rel.to_uid,
                rel.from_resource_type, rel.to_resource_type,
                json.dumps(rel.properties),
                rel.from_uid, rel.to_uid, rel.relation_type,
            ))

        self.conn.commit()

    def write_scan_snapshot(self, assets: List[Asset]):
        """Write full scan snapshot to inventory_scan_data for historical retention.

        Each scan gets its own set of rows. Old scans beyond the retention limit
        are purged by purge_old_scans().
        """
        if not assets:
            return

        cursor = self.conn.cursor()

        def _serialize_value(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: _serialize_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_serialize_value(item) for item in obj]
            return obj

        for asset in assets:
            finding_id = generate_finding_id(asset)
            configuration = asset.metadata.get('configuration', {}) if asset.metadata else {}
            labels = asset.metadata.get('labels', {}) if asset.metadata else {}
            properties = {k: v for k, v in asset.metadata.items() if k not in ['configuration', 'labels', 'raw_refs']} if asset.metadata else {}
            configuration = _serialize_value(configuration)
            labels = _serialize_value(labels)
            properties = _serialize_value(properties)

            cursor.execute("""
                INSERT INTO inventory_scan_data (
                    inventory_scan_id, tenant_id, asset_id, resource_uid,
                    provider, account_id, region, resource_type, resource_id,
                    name, tags, labels, properties, configuration
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                asset.scan_run_id, asset.tenant_id, finding_id, asset.resource_uid,
                asset.provider.value, asset.account_id, asset.region,
                asset.resource_type, asset.resource_id, asset.name,
                json.dumps(asset.tags), json.dumps(labels),
                json.dumps(properties), json.dumps(configuration),
            ))

        self.conn.commit()
        logger.info(f"Wrote {len(assets)} asset snapshots to inventory_scan_data")

    def purge_old_scans(self, tenant_id: str, keep_count: int = 5):
        """Delete scan snapshots and relationships older than the N most recent.

        Keeps inventory_findings (latest state) intact. Purges:
          - inventory_scan_data rows from old scans
          - inventory_relationships rows from old scans
          - inventory_drift rows from old scans
        """
        cursor = self.conn.cursor()
        # Get the scan IDs to keep (most recent N)
        cursor.execute("""
            SELECT scan_run_id FROM inventory_report
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (tenant_id, keep_count))
        keep_ids = [r[0] for r in cursor.fetchall()]

        if not keep_ids:
            return 0

        total_deleted = 0
        # scan_run_id column varies by table
        table_scan_col = {
            'inventory_scan_data': 'inventory_scan_id',
            'inventory_relationships': 'scan_run_id',
            'inventory_drift': 'inventory_scan_id',
        }
        for table in ['inventory_scan_data', 'inventory_relationships', 'inventory_drift']:
            col = table_scan_col[table]
            try:
                cursor.execute(f"""
                    DELETE FROM {table}
                    WHERE tenant_id = %s
                      AND {col} IS NOT NULL
                      AND {col} != ALL(%s)
                """, (tenant_id, keep_ids))
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"Purged {deleted} old rows from {table}")
                    total_deleted += deleted
            except Exception as e:
                logger.warning(f"Failed to purge {table}: {e}")
                self.conn.rollback()
                cursor = self.conn.cursor()

        self.conn.commit()
        logger.info(f"Scan retention: kept {len(keep_ids)} scans, purged {total_deleted} old rows")
        return total_deleted

    def write_drift_index(self, drift_records, scan_run_id: str, previous_scan_id: str, tenant_id: str):
        """Write drift records to inventory_drift table.

        Args:
            drift_records: List of DriftRecord pydantic objects from DriftDetector
            scan_run_id: Current inventory scan ID
            previous_scan_id: Previous scan ID that was compared against
            tenant_id: Tenant ID
        """
        if not drift_records:
            return

        cursor = self.conn.cursor()
        inserted = 0

        for dr in drift_records:
            try:
                drift_id = str(uuid.uuid4())
                change_type = dr.change_type.value if hasattr(dr.change_type, 'value') else str(dr.change_type)

                # Build previous/current state and changes_summary from diff
                diff_data = dr.diff if (hasattr(dr, 'diff') and dr.diff) else {}
                changes_summary = diff_data if isinstance(diff_data, (dict, list)) else {}

                # Derive previous/current state from snapshot (add/remove) or diff (changed)
                snapshot = diff_data.get("snapshot", {}) if isinstance(diff_data, dict) else {}
                ct_lower = change_type.lower()
                if "add" in ct_lower:
                    previous_state: Dict[str, Any] = {}
                    current_state: Dict[str, Any] = snapshot
                elif "remov" in ct_lower:
                    previous_state = snapshot
                    current_state = {}
                else:
                    # asset_changed: summarise what changed from the changes list
                    changes_list = diff_data.get("changes", []) if isinstance(diff_data, dict) else []
                    previous_state = {c["path"]: c.get("before") for c in changes_list if isinstance(c, dict)}
                    current_state = {c["path"]: c.get("after") for c in changes_list if isinstance(c, dict)}

                # Determine severity from change type
                if "remove" in ct_lower:
                    severity = "high"
                elif "change" in ct_lower or "modified" in ct_lower:
                    severity = "medium"
                else:
                    severity = "low"

                # Extract resource metadata (populated by DriftDetector)
                resource_uid = dr.resource_uid if hasattr(dr, 'resource_uid') else ""
                provider = getattr(dr, 'provider', "") or ""
                resource_type = getattr(dr, 'resource_type', "") or ""

                cursor.execute("""
                    INSERT INTO inventory_drift (
                        drift_id, inventory_scan_id, previous_scan_id, tenant_id,
                        resource_uid, provider, resource_type, change_type,
                        previous_state, current_state, changes_summary,
                        severity, detected_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    drift_id, scan_run_id, previous_scan_id, tenant_id,
                    resource_uid, provider, resource_type, change_type,
                    json.dumps(previous_state), json.dumps(current_state),
                    json.dumps(changes_summary),
                    severity,
                    dr.detected_at if hasattr(dr, 'detected_at') else datetime.now(timezone.utc)
                ))
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to write drift record: {e}")
                self.conn.rollback()
                cursor = self.conn.cursor()
                continue

        self.conn.commit()
        logger.info(f"Wrote {inserted}/{len(drift_records)} drift records to inventory_drift")

