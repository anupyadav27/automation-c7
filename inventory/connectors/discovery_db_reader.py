"""
Discovery Database Reader

Reads discovery records from PostgreSQL database (production mode).
Supports consolidated DB: set DB_SCHEMA (e.g. engine_configscan,engine_shared).

=== DATABASE & TABLE MAP ===
Database: threat_engine_discoveries (DISCOVERIES DB)
Env: DISCOVERIES_DB_HOST / DISCOVERIES_DB_PORT / DISCOVERIES_DB_NAME / DISCOVERIES_DB_USER / DISCOVERIES_DB_PASSWORD
     (constructed in discovery_reader_factory.py)

Tables READ:
  - discovery_report   : get_latest_scan_id()  — SELECT scan_run_id WHERE status='completed' ORDER BY first_seen_at DESC
                         list_available_scans() — SELECT + COUNT(*) FROM discovery_findings
  - discovery_findings : read_discovery_records() — SELECT scan_run_id, customer_id, tenant_id, provider,
                           account_id, hierarchy_type, discovery_id, region, service,
                           resource_uid, resource_id, emitted_fields, raw_response, config_hash,
                           first_seen_at, version
                         Filters: scan_run_id, tenant_id, account_id, region, service

Tables WRITTEN: None (read-only connector)
===
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Iterator, Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


def _db_url_with_search_path(url: str) -> str:
    """Append options=search_path to URL when DB_SCHEMA is set."""
    schema = (os.getenv("DB_SCHEMA") or "").strip()
    if not schema:
        return url
    sep = "&" if "?" in url else "?"
    opts = f"options=-c%20search_path%3D{schema.replace(',', '%2C')}"
    return f"{url}{sep}{opts}"


class DiscoveryDBReader:
    """Reads discovery records from PostgreSQL database"""

    def __init__(self, db_url: str, tenant_id: Optional[str] = None):
        """
        Initialize discovery database reader.

        Args:
            db_url: PostgreSQL connection URL
            tenant_id: Tenant identifier (optional, can be set per method call)
        """
        self.db_url = db_url
        self.tenant_id = tenant_id
        self.conn = psycopg2.connect(_db_url_with_search_path(db_url))
    
    def get_latest_scan_id(self, tenant_id: Optional[str] = None) -> Optional[str]:
        """
        Get latest completed scan ID for a tenant.
        
        Args:
            tenant_id: Tenant identifier (uses instance tenant_id if not provided)
        
        Returns:
            Latest scan ID or None if no scans found
        """
        tenant_id = tenant_id or self.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id must be provided either in __init__ or method call")
        
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT scan_run_id FROM discovery_report
                    WHERE tenant_id = %s
                      AND status = 'completed'
                      AND scan_type IN ('discovery', 'full')
                    ORDER BY first_seen_at DESC
                    LIMIT 1
                """, (tenant_id,))
                result = cur.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting latest scan: {e}")
            return None
    
    def read_discovery_records(
        self,
        scan_id: str,
        account_id: Optional[str] = None,
        account_ids: Optional[List[str]] = None,
        region: Optional[str] = None,
        service: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Read discovery records from database with filters.

        Args:
            scan_id: Scan ID or "latest" for auto-detect
            account_id: Optional filter by single account ID (backward compat)
            account_ids: Optional filter by multiple account IDs (multi-account support)
            region: Optional filter by region (use "global" or None for global services)
            service: Optional filter by service name
            tenant_id: Tenant identifier (uses instance tenant_id if not provided)

        Yields:
            Discovery record dictionaries
        """
        tenant_id = tenant_id or self.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id must be provided either in __init__ or method call")

        # Auto-detect latest scan
        if scan_id == "latest":
            scan_id = self.get_latest_scan_id(tenant_id)
            if not scan_id:
                logger.warning(f"No scans found for tenant: {tenant_id}")
                return

        # Build query with filters
        query = """
            SELECT
                scan_run_id, customer_id, tenant_id, provider,
                account_id, hierarchy_type, discovery_id,
                region, service,
                resource_uid, resource_id,
                emitted_fields, raw_response, config_hash,
                first_seen_at, version
            FROM discovery_findings
            WHERE scan_run_id = %s AND tenant_id = %s
        """
        params: list = [scan_id, tenant_id]

        # Multi-account filter: merge account_ids list + single account_id
        effective_account_ids: Optional[List[str]] = None
        if account_ids:
            effective_account_ids = list(set(account_ids + ([account_id] if account_id else [])))
        elif account_id:
            effective_account_ids = [account_id]

        if effective_account_ids and len(effective_account_ids) == 1:
            query += " AND account_id = %s"
            params.append(effective_account_ids[0])
        elif effective_account_ids:
            query += " AND account_id = ANY(%s::text[])"
            params.append(effective_account_ids)

        if region is not None:
            if region == "global":
                query += " AND (region IS NULL OR region = 'global')"
            else:
                query += " AND region = %s"
                params.append(region)
        if service:
            query += " AND service = %s"
            params.append(service)
        
        query += " ORDER BY resource_uid, discovery_id"
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                for row in cur:
                    yield dict(row)
        except Exception as e:
            logger.error(f"Error reading discoveries: {e}")
            return
    
    def list_available_scans(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all available scans for a tenant.
        
        Args:
            tenant_id: Tenant identifier (uses instance tenant_id if not provided)
        
        Returns:
            List of scan metadata dictionaries
        """
        tenant_id = tenant_id or self.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id must be provided either in __init__ or method call")
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        scan_run_id,
                        first_seen_at,
                        status,
                        scan_type,
                        provider,
                        metadata,
                        (SELECT COUNT(*) FROM discovery_findings WHERE discovery_findings.scan_run_id = discovery_report.scan_run_id) as total_records
                    FROM discovery_report
                    WHERE tenant_id = %s
                    ORDER BY first_seen_at DESC
                    LIMIT 50
                """, (tenant_id,))
                
                scans = []
                for row in cur.fetchall():
                    scan_dict = dict(row)
                    scans.append({
                        "scan_id": scan_dict["scan_run_id"],
                        "first_seen_at": scan_dict["first_seen_at"].isoformat() if scan_dict["first_seen_at"] else None,
                        "status": scan_dict["status"],
                        "metadata": scan_dict.get("metadata", {}),
                        "total_records": scan_dict.get("total_records", 0)
                    })
                
                return scans
        except Exception as e:
            logger.error(f"Error listing scans: {e}")
            return []
    
    def get_discovery_path(self, scan_id: str) -> str:
        """Compatibility method - returns database indicator"""
        return f"database://discovery_findings?scan_run_id={scan_id}"
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
