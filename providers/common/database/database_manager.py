"""
PostgreSQL Database Manager for Discoveries Engine
Handles discovery storage and drift detection
"""
import os
import json
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2.pool import SimpleConnectionPool
from datetime import datetime
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
import sys
import logging

# Import local database config (Bypassed for local pipeline runner)
# _engine_path = os.path.join(os.path.dirname(__file__), "..", "..")
# sys.path.insert(0, _engine_path)
# from consolidated_services.database.config import get_database_config

logger = logging.getLogger(__name__)


def _parse_database_url(url: str) -> Dict[str, Any]:
    """Parse DATABASE_URL into host, port, database, user, password."""
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"Unsupported scheme: {u.scheme}")
    path = (u.path or "").lstrip("/")
    return {
        "host": u.hostname or "localhost",
        "port": u.port or 5432,
        "database": path or "postgres",
        "user": u.username or "postgres",
        "password": u.password or "",
    }


class DatabaseManager:
    """PostgreSQL database manager for Discoveries Engine"""

    def __init__(self, db_config: Optional[Dict] = None):
        """
        Initialize database connection for discoveries engine.
        
        Args:
            db_config: Optional override (for testing). Normally uses consolidated DB config.
        """
        # Build dummy config via Environment Variables to run locally
        self.db_config = {
            "host": os.getenv("DISCOVERIES_DB_HOST", "localhost"),
            "port": int(os.getenv("DISCOVERIES_DB_PORT", "5433")),
            "database": os.getenv("DISCOVERIES_DB_NAME", "threat_engine_discoveries"),
            "user": os.getenv("DISCOVERIES_DB_USER", "postgres"),
            "password": os.getenv("DISCOVERIES_DB_PASSWORD", "password"),
        }
        logger.info(f"Using local discoveries database config from env: {self.db_config['database']} on {self.db_config['host']}")
        
        # Allow override for testing
        if db_config is not None:
            self.db_config.update(db_config)
            logger.warning("Using provided db_config override (testing mode)")
        
        # Set schema search_path - use public schema for now
        self.search_path = os.getenv("DB_SCHEMA", "public")
        self.use_consolidated_db = True
        
        self.connection_pool = None
        self._init_pool()

    def _init_pool(self):
        """Initialize connection pool.

        Pool sizing rationale:
          - MAX_CONCURRENT_TASKS (400) global semaphore, DB executor capped at 50 threads
          - Each scan calls store_discoveries_batch() via a DB executor thread
          - Plus a few extra for config reads and status updates
          - min=5  : keep a few warm connections to avoid cold-start latency
          - max=60 : headroom above the 50 concurrent threads; psycopg2 pools
                     block if exhausted so we give 20% headroom
        """
        min_conns = int(os.getenv('DB_POOL_MIN', '5'))
        max_conns = int(os.getenv('DB_POOL_MAX', '60'))
        try:
            self.connection_pool = SimpleConnectionPool(
                min_conns, max_conns,
                host=self.db_config["host"],
                port=self.db_config["port"],
                database=self.db_config["database"],
                user=self.db_config["user"],
                password=self.db_config["password"],
                options=f"-c search_path={self.search_path}"
            )
            logger.info(f"Database connection pool initialized (min={min_conns}, max={max_conns}, consolidated DB)")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise

    def _get_connection(self):
        """Get connection from pool"""
        if not self.connection_pool:
            self._init_pool()
        return self.connection_pool.getconn()

    def _return_connection(self, conn):
        """Return connection to pool"""
        if self.connection_pool:
            self.connection_pool.putconn(conn)

    # Customer Management (shared)
    def create_customer(self, customer_id: str, customer_name: str = None,
                       metadata: Dict = None) -> None:
        """Create or update customer"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO customers (customer_id, customer_name, metadata)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (customer_id) 
                    DO UPDATE SET 
                        customer_name = EXCLUDED.customer_name,
                        metadata = EXCLUDED.metadata
                """, (customer_id, customer_name, json.dumps(metadata or {}) if metadata else None))
            conn.commit()
        finally:
            self._return_connection(conn)
    
    # Tenant Management (shared)
    def create_tenant(self, tenant_id: str, customer_id: str, provider: str,
                     tenant_name: str = None, metadata: Dict = None) -> None:
        """Create or update tenant"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tenants (tenant_id, customer_id, provider, tenant_name, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id)
                    DO UPDATE SET
                        customer_id = EXCLUDED.customer_id,
                        provider = EXCLUDED.provider,
                        tenant_name = EXCLUDED.tenant_name,
                        metadata = EXCLUDED.metadata
                """, (
                    tenant_id, customer_id, provider, tenant_name,
                    json.dumps(metadata or {}) if metadata else None
                ))
            conn.commit()
        finally:
            self._return_connection(conn)
    
    # Scan Management (shared)
    def create_scan(self, scan_id: str, customer_id: str, tenant_id: str,
                   provider: str, account_id: str = None,
                   hierarchy_type: str = None, region: str = None,
                   service: str = None, scan_type: str = 'discovery',
                   metadata: Dict = None) -> None:
        """Create scan record in discovery_report"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO discovery_report
                    (scan_run_id, customer_id, tenant_id, provider, account_id, hierarchy_type,
                     region, service, scan_type, status, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (scan_run_id) DO NOTHING
                """, (
                    scan_id, customer_id, tenant_id, provider,
                    account_id, hierarchy_type, region, service,
                    scan_type, 'running',
                    json.dumps(metadata or {}) if metadata else None
                ))
            conn.commit()
        finally:
            self._return_connection(conn)
    
    def update_scan_status(self, scan_id: str, status: str) -> None:
        """Update scan status in discovery_report"""
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE discovery_report SET status = %s WHERE scan_run_id = %s
                """, (status, scan_id))
            conn.commit()
        finally:
            self._return_connection(conn)
    
    # Discovery Storage
    def _calculate_config_hash(self, item: Dict) -> str:
        """Calculate SHA256 hash of configuration"""
        config_dict = {
            k: v for k, v in item.items()
            if k not in ['_raw_response', 'first_seen_at', 'version', 'metadata']
        }
        config_str = json.dumps(config_dict, sort_keys=True, default=str)
        return hashlib.sha256(config_str.encode()).hexdigest()
    
    def store_discoveries_batch(self, scan_id: str, customer_id: str, tenant_id: str,
                                provider: str, discovery_id: str, items: List[Dict],
                                account_id: str = None, hierarchy_type: str = None,
                                region: str = None, service: str = None) -> Dict[str, Any]:
        """
        Store discovery results in batch (optimized for performance)
        
        Returns:
            Dict with drift detection results
        """
        if not items:
            return {
                'new_resources': 0,
                'modified_resources': 0,
                'unchanged_resources': 0,
                'deleted_resources': 0,
                'drifts': []
            }

        # Filter out empty/meaningless items: dicts with no resource identifier
        # and no meaningful content (e.g. {} from failed API calls)
        def _is_meaningful(item: dict) -> bool:
            if not isinstance(item, dict):
                return False
            # Must have a resource identifier OR some non-metadata content
            has_id = bool(item.get('resource_arn') or item.get('resource_uid') or item.get('resource_id'))
            internal_keys = {'_raw_response', '_raw_item', 'resource_arn', 'resource_uid',
                             'resource_id', 'resource_type', 'resource_name'}
            has_content = any(k not in internal_keys and v not in (None, '', [], {})
                              for k, v in item.items())
            return has_id or has_content

        items = [item for item in items if _is_meaningful(item)]
        if not items:
            return {
                'new_resources': 0,
                'modified_resources': 0,
                'unchanged_resources': 0,
                'deleted_resources': 0,
                'drifts': []
            }

        drift_results = {
            'new_resources': 0,
            'modified_resources': 0,
            'unchanged_resources': 0,
            'deleted_resources': 0,
            'drifts': []
        }
        
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Batch: Get all previous versions in one query
                resource_uids = [item.get('resource_uid') or item.get('resource_arn', '') for item in items]
                resource_uids = [uid for uid in resource_uids if uid]  # Filter None values
                
                previous_versions = {}
                if resource_uids:
                    placeholders = ','.join(['%s'] * len(resource_uids))
                    cur.execute(f"""
                        SELECT discovery_id, resource_uid, config_hash, version,
                               scan_run_id, first_seen_at, emitted_fields
                        FROM discovery_findings
                        WHERE discovery_id = %s
                          AND resource_uid IN ({placeholders})
                          AND customer_id = %s
                          AND tenant_id = %s
                          AND account_id = %s
                        ORDER BY first_seen_at DESC
                    """, (discovery_id, *resource_uids, customer_id, tenant_id, account_id))
                    
                    # Build lookup map: resource_uid -> latest version
                    for row in cur.fetchall():
                        uid = row['resource_uid']
                        if uid not in previous_versions:
                            previous_versions[uid] = row
                
                # Prepare batch data with drift detection
                discoveries_to_insert = []
                discoveries_to_update = []
                history_batch = []
                
                def json_serial(obj):
                    """JSON serializer for objects not serializable by default json code"""
                    if isinstance(obj, (datetime,)):
                        return obj.isoformat()
                    raise TypeError(f"Type {type(obj)} not serializable")
                
                for item in items:
                    resource_uid = item.get('resource_uid') or item.get('resource_arn')
                    resource_id = item.get('resource_id')
                    resource_type = item.get('resource_type')

                    config_hash = self._calculate_config_hash(item)
                    
                    # Check previous version from batch lookup
                    previous = previous_versions.get(resource_uid) if resource_uid else None
                    
                    raw_response_json = json.dumps(item.get('_raw_response', {}), default=json_serial)
                    emitted_fields_json = json.dumps(item, default=json_serial)
                    history_resource_uid = resource_uid or f"account:{account_id}:{discovery_id}"
                    
                    if previous:
                        previous_hash = previous['config_hash']
                        if config_hash == previous_hash:
                            # UNCHANGED: UPDATE existing record with new scan_id and timestamp
                            change_type = 'unchanged'
                            version = previous['version']
                            drift_results['unchanged_resources'] += 1
                            diff_summary = None
                            
                            discoveries_to_update.append((
                                scan_id,  # new scan_id
                                resource_uid,
                                discovery_id,
                                customer_id,
                                tenant_id,
                                account_id,
                            ))
                        else:
                            # MODIFIED: INSERT new version
                            change_type = 'modified'
                            version = previous['version'] + 1
                            drift_results['modified_resources'] += 1
                            
                            # Calculate diff — psycopg2 returns JSONB as dict already
                            _ef = previous.get('emitted_fields', '{}')
                            old_item = _ef if isinstance(_ef, dict) else json.loads(_ef)
                            diff_summary = self._calculate_diff_summary(old_item, item)
                            
                            drift_results['drifts'].append({
                                'resource_uid': resource_uid,
                                'discovery_id': discovery_id,
                                'change_type': 'configuration',
                                'severity': self._calculate_severity(diff_summary),
                                'change_summary': diff_summary
                            })
                            
                            discoveries_to_insert.append((
                                scan_id, customer_id, tenant_id, provider,
                                account_id, hierarchy_type,
                                discovery_id, region, service, resource_uid, resource_id,
                                resource_type, raw_response_json, emitted_fields_json, config_hash, version
                            ))
                    else:
                        # NEW: INSERT
                        change_type = 'created'
                        version = 1
                        drift_results['new_resources'] += 1
                        diff_summary = None

                        discoveries_to_insert.append((
                            scan_id, customer_id, tenant_id, provider,
                            account_id, hierarchy_type,
                            discovery_id, region, service, resource_uid, resource_id,
                            resource_type, raw_response_json, emitted_fields_json, config_hash, version
                        ))
                    
                    # Always add to history
                    history_batch.append((
                        customer_id, tenant_id, provider, account_id, hierarchy_type,
                        discovery_id, resource_uid, scan_id, config_hash,
                        raw_response_json, emitted_fields_json, version, change_type,
                        previous['config_hash'] if previous else None,
                        json.dumps(diff_summary, default=json_serial) if diff_summary else None
                    ))
                
                # Execute UPDATE for unchanged resources
                if discoveries_to_update:
                    cur.executemany("""
                        UPDATE discovery_findings
                        SET scan_run_id = %s, first_seen_at = CURRENT_TIMESTAMP
                        WHERE resource_uid = %s
                          AND discovery_id = %s
                          AND customer_id = %s
                          AND tenant_id = %s
                          AND account_id = %s
                    """, discoveries_to_update)

                # Execute INSERT for new/modified resources
                if discoveries_to_insert:
                    cur.executemany("""
                        INSERT INTO discovery_findings
                        (scan_run_id, customer_id, tenant_id, provider, account_id, hierarchy_type,
                         discovery_id, region, service, resource_uid, resource_id,
                         resource_type, raw_response, emitted_fields, config_hash, version)
                        VALUES (%s, COALESCE(%s, 'default'), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, discoveries_to_insert)
                
                # Batch insert history
                # Commit findings first (critical)
                conn.commit()

                # History is non-critical — don't let it block findings
                if history_batch:
                    try:
                        cur.executemany("""
                            INSERT INTO discovery_history
                            (customer_id, tenant_id, provider, account_id, hierarchy_type,
                             discovery_id, resource_uid, scan_run_id, config_hash,
                             raw_response, emitted_fields, version, change_type,
                             previous_hash, diff_summary)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, history_batch)
                        conn.commit()
                    except Exception as hist_err:
                        conn.rollback()
                        logger.warning(f"History insert failed (non-critical): {hist_err}")
        except Exception:
            # Roll back so the connection isn't returned to the pool in a
            # dirty/aborted-transaction state.
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._return_connection(conn)
        
        return drift_results
    
    def _calculate_diff_summary(self, old_item: Dict, new_item: Dict) -> Dict:
        """Calculate summary of changes"""
        changes = {
            'fields_added': [],
            'fields_removed': [],
            'fields_modified': []
        }
        
        old_keys = set(old_item.keys())
        new_keys = set(new_item.keys())
        
        changes['fields_added'] = list(new_keys - old_keys)
        changes['fields_removed'] = list(old_keys - new_keys)
        
        common_keys = old_keys & new_keys
        for key in common_keys:
            if old_item[key] != new_item[key]:
                changes['fields_modified'].append({
                    'field': key,
                    'old_value': str(old_item[key])[:100],
                    'new_value': str(new_item[key])[:100]
                })
        
        return changes
    
    def _calculate_severity(self, diff_summary: Dict) -> str:
        """Calculate severity based on changes"""
        critical_fields = ['Policy', 'Encryption', 'PublicAccessBlock', 'Versioning']
        
        modified_fields = [c['field'] for c in diff_summary.get('fields_modified', [])]
        added_fields = diff_summary.get('fields_added', [])
        removed_fields = diff_summary.get('fields_removed', [])
        
        if any(field in modified_fields or field in added_fields or field in removed_fields
               for field in critical_fields):
            return 'high'
        
        total_changes = len(modified_fields) + len(added_fields) + len(removed_fields)
        if total_changes > 5:
            return 'medium'
        
        return 'low'
    
    # Query Methods
    def query_discovery(self, discovery_id: str = None, tenant_id: str = None,
                       account_id: str = None, scan_id: str = None,
                       customer_id: str = None, service: str = None) -> List[Dict]:
        """Query discoveries"""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if scan_id:
                    # Query specific scan
                    query = "SELECT * FROM discovery_findings WHERE scan_run_id = %s"
                    params = [scan_id]
                    
                    if discovery_id:
                        query += " AND discovery_id = %s"
                        params.append(discovery_id)
                    if tenant_id:
                        query += " AND tenant_id = %s"
                        params.append(tenant_id)
                    if account_id:
                        query += " AND account_id = %s"
                        params.append(account_id)
                    if service:
                        query += " AND service = %s"
                        params.append(service)
                    
                    cur.execute(query, params)
                else:
                    # Query latest version
                    query = """
                        SELECT d1.* FROM discovery_findings d1
                        INNER JOIN (
                            SELECT discovery_id, COALESCE(resource_uid, '') as resource_uid,
                                   customer_id, tenant_id, account_id,
                                   MAX(first_seen_at) as max_ts
                            FROM discovery_findings
                            WHERE 1=1
                    """
                    params = []

                    if discovery_id:
                        query += " AND discovery_id = %s"
                        params.append(discovery_id)

                    query += """
                            GROUP BY discovery_id, COALESCE(resource_uid, ''), customer_id, tenant_id, account_id
                        ) d2 ON d1.discovery_id = d2.discovery_id
                            AND COALESCE(d1.resource_uid, '') = d2.resource_uid
                            AND d1.customer_id = d2.customer_id
                            AND d1.tenant_id = d2.tenant_id
                            AND d1.account_id = d2.account_id
                            AND d1.first_seen_at = d2.max_ts
                        WHERE 1=1
                    """
                    
                    if tenant_id:
                        query += " AND d1.tenant_id = %s"
                        params.append(tenant_id)
                    if account_id:
                        query += " AND d1.account_id = %s"
                        params.append(account_id)
                    if customer_id:
                        query += " AND d1.customer_id = %s"
                        params.append(customer_id)
                    if service:
                        query += " AND d1.service = %s"
                        params.append(service)
                    
                    cur.execute(query, params)
                
                return [dict(row) for row in cur.fetchall()]
        finally:
            self._return_connection(conn)
    
    def store_service_scan_result(self, scan_id: str, result: Dict[str, Any]) -> None:
        """
        Store service scan attempt metadata

        Tracks ALL service scans including:
        - Successful scans (scanned)
        - Unavailable services (OptInRequired)
        - Permission denied (AccessDenied)
        - Failed scans (unexpected errors)

        Args:
            scan_id: Discovery scan ID
            result: Scan result dict with keys:
                - service: Service name (e.g., 'ec2', 'gamelift')
                - region: Region name
                - status: 'scanned', 'unavailable', 'access_denied', 'failed'
                - discoveries: Number of resources found
                - error: Error code (OptInRequired, AccessDenied, etc.)
                - duration_ms: Scan duration in milliseconds
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO service_scan_attempts (
                        scan_run_id, service, region, status,
                        discoveries_count, error_code, error_message, scan_duration_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (scan_run_id, service, region)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        discoveries_count = EXCLUDED.discoveries_count,
                        error_code = EXCLUDED.error_code,
                        error_message = EXCLUDED.error_message,
                        scan_duration_ms = EXCLUDED.scan_duration_ms,
                        created_at = CURRENT_TIMESTAMP
                """, (
                    scan_id,
                    result['service'],
                    result['region'],
                    result['status'],
                    result.get('discoveries', 0),
                    result.get('error'),
                    result.get('error_message'),
                    result.get('duration_ms')
                ))
            conn.commit()
        finally:
            self._return_connection(conn)

    def close(self):
        """Close connection pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
