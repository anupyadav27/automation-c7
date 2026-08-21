"""
Check DB Reader (Inventory)

Reads check results from the Check DB (threat_engine_check.check_findings) so Inventory
can enrich assets with posture summaries without calling cloud APIs.

=== DATABASE & TABLE MAP ===
Database: threat_engine_check (CHECK DB)
Env: CHECK_DB_HOST / CHECK_DB_PORT / CHECK_DB_NAME / CHECK_DB_USER / CHECK_DB_PASSWORD

Tables READ:
  - check_findings : get_posture_by_resource(scan_id, tenant_id)
                     — Aggregate PASS/FAIL/ERROR counts grouped by resource_uid
                     get_findings_for_resource(resource_uid, tenant_id)
                     — Detailed findings list with severity/title from rule_metadata JOIN
                     get_severity_counts_for_resource(resource_uid, tenant_id)
                     — Severity breakdown (critical/high/medium/low) for a single resource
  - rule_metadata  : JOINed in get_findings_for_resource / get_severity_counts_for_resource
                     — Provides severity, title, service per rule_id

Tables WRITTEN: None (read-only connector)
===
"""

from __future__ import annotations

import os
import logging
from typing import Dict, Any, Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _db_url_with_search_path(url: str) -> str:
    """Append options=search_path to URL when DB_SCHEMA is set."""
    schema = (os.getenv("DB_SCHEMA") or "").strip()
    if not schema:
        return url
    sep = "&" if "?" in url else "?"
    opts = f"options=-c%20search_path%3D{schema.replace(',', '%2C')}"
    return f"{url}{sep}{opts}"


class CheckDBReader:
    """Reads check results from PostgreSQL check_findings table."""

    def __init__(self, db_url: Optional[str] = None):
        if db_url is None:
            host = os.getenv("CHECK_DB_HOST", "localhost")
            port = os.getenv("CHECK_DB_PORT", "5432")
            db = os.getenv("CHECK_DB_NAME", "threat_engine_check")
            user = os.getenv("CHECK_DB_USER", "check_user")
            pwd = os.getenv("CHECK_DB_PASSWORD", "check_password")
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
        self.db_url = db_url
        self.conn = psycopg2.connect(_db_url_with_search_path(db_url))

    def get_posture_by_resource(
        self,
        *,
        scan_id: str,
        tenant_id: str,
        account_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Return a posture summary per resource_uid for a given check scan.

        Output format:
        {
          "<resource_uid>": {
            "total": int,
            "passed": int,
            "failed": int,
            "errors": int,
          },
          ...
        }
        """
        query = """
            SELECT
                resource_uid AS resource_uid,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'PASS') AS passed,
                COUNT(*) FILTER (WHERE status = 'FAIL') AS failed,
                COUNT(*) FILTER (WHERE status = 'ERROR') AS errors
            FROM check_findings
            WHERE scan_run_id = %s AND tenant_id = %s
        """
        params = [scan_id, tenant_id]
        if account_id:
            query += " AND account_id = %s"
            params.append(account_id)
        query += " GROUP BY resource_uid"

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        result: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            uid = r.get("resource_uid")
            if not uid:
                continue
            result[uid] = {
                "total": int(r.get("total") or 0),
                "passed": int(r.get("passed") or 0),
                "failed": int(r.get("failed") or 0),
                "errors": int(r.get("errors") or 0),
            }
        return result

    def get_severity_counts_for_resource(
        self,
        resource_uid: str,
        tenant_id: str,
    ) -> Dict[str, int]:
        """
        Return severity breakdown for a single resource across all scans.

        Returns:
            {"critical": int, "high": int, "medium": int, "low": int}
        """
        query = """
            SELECT
                LOWER(COALESCE(rm.severity, 'medium')) AS severity,
                COUNT(*) AS cnt
            FROM check_findings cf
            LEFT JOIN rule_metadata rm ON rm.rule_id = cf.rule_id
            WHERE COALESCE(cf.resource_uid, cf.resource_arn) = %s
              AND cf.tenant_id = %s
              AND cf.status = 'FAIL'
            GROUP BY LOWER(COALESCE(rm.severity, 'medium'))
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (resource_uid, tenant_id))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Severity counts query failed: {e}")
            rows = []

        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in rows:
            sev = r.get("severity", "medium")
            if sev in counts:
                counts[sev] = int(r.get("cnt") or 0)
        return counts

    def get_findings_for_resource(
        self,
        resource_uid: str,
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Return detailed findings list for a specific resource (for asset detail Findings tab).

        JOINs with rule_metadata to get severity and title.
        """
        query = """
            SELECT
                cf.rule_id,
                rm.title,
                LOWER(COALESCE(rm.severity, 'medium')) AS severity,
                COALESCE(rm.service, cf.service) AS service,
                cf.status,
                cf.region,
                cf.resource_type,
                cf.created_at
            FROM check_findings cf
            LEFT JOIN rule_metadata rm ON rm.rule_id = cf.rule_id
            WHERE COALESCE(cf.resource_uid, cf.resource_arn) = %s
              AND cf.tenant_id = %s
            ORDER BY
                CASE LOWER(COALESCE(rm.severity, 'medium'))
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                cf.created_at DESC
            LIMIT %s
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (resource_uid, tenant_id, limit))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Findings detail query failed: {e}")
            return []

        findings = []
        for r in rows:
            created = r.get("created_at")
            findings.append({
                "rule_id": r["rule_id"],
                "title": r.get("title") or r["rule_id"],
                "severity": r.get("severity") or "medium",
                "service": r.get("service") or "",
                "status": r.get("status") or "FAIL",
                "region": r.get("region") or "",
                "resource_type": r.get("resource_type") or "",
                "created_at": created.isoformat() if created else None,
            })
        return findings

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

