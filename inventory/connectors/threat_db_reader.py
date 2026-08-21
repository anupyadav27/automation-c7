"""
Threat DB Reader (Inventory)

Reads threat findings from the Threat DB (threat_engine_threat.threat_findings) so Inventory
can enrich assets with MITRE ATT&CK techniques and threat severity.

=== DATABASE & TABLE MAP ===
Database: threat_engine_threat (THREAT DB)
Env: THREAT_DB_HOST / THREAT_DB_PORT / THREAT_DB_NAME / THREAT_DB_USER / THREAT_DB_PASSWORD

Tables READ:
  - threat_findings : get_threat_findings_for_resource(resource_uid, tenant_id)
                      — Detailed threat findings with MITRE tactics/techniques
                      get_threat_severity_counts(resource_uid, tenant_id)
                      — Severity breakdown (critical/high/medium/low) for a single resource

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


class ThreatDBReader:
    """Reads threat findings from PostgreSQL threat_findings table."""

    def __init__(self, db_url: Optional[str] = None):
        if db_url is None:
            host = os.getenv("THREAT_DB_HOST", "localhost")
            port = os.getenv("THREAT_DB_PORT", "5432")
            db = os.getenv("THREAT_DB_NAME", "threat_engine_threat")
            user = os.getenv("THREAT_DB_USER", "threat_user")
            pwd = os.getenv("THREAT_DB_PASSWORD", "threat_password")
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
        self.db_url = db_url
        self.conn = psycopg2.connect(_db_url_with_search_path(db_url))

    def get_threat_findings_for_resource(
        self,
        resource_uid: str,
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Return threat findings for a specific resource (for asset detail Threats section).

        Matches on BOTH resource_uid and resource_arn to handle ARN format mismatch
        between inventory and threat DBs.
        """
        query = """
            SELECT
                tf.finding_id,
                tf.rule_id,
                tf.threat_category,
                tf.severity,
                tf.status,
                tf.resource_type,
                tf.region,
                tf.account_id,
                tf.mitre_tactics,
                tf.mitre_techniques,
                tf.evidence,
                tf.first_seen_at,
                tf.last_seen_at
            FROM threat_findings tf
            WHERE (tf.resource_uid = %s OR tf.resource_arn = %s)
              AND tf.tenant_id = %s
            ORDER BY
                CASE LOWER(COALESCE(tf.severity, 'medium'))
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                tf.last_seen_at DESC
            LIMIT %s
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (resource_uid, resource_uid, tenant_id, limit))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Threat findings query failed: {e}")
            return []

        findings: List[Dict[str, Any]] = []
        for r in rows:
            first_seen = r.get("first_seen_at")
            last_seen = r.get("last_seen_at")
            # mitre_tactics/techniques are JSONB — psycopg2 auto-deserialises
            findings.append({
                "finding_id": r.get("finding_id"),
                "rule_id": r.get("rule_id"),
                "threat_category": r.get("threat_category") or "",
                "severity": (r.get("severity") or "medium").lower(),
                "status": r.get("status") or "open",
                "resource_type": r.get("resource_type") or "",
                "region": r.get("region") or "",
                "account_id": r.get("account_id") or "",
                "mitre_tactics": r.get("mitre_tactics") or [],
                "mitre_techniques": r.get("mitre_techniques") or [],
                "evidence": r.get("evidence") or {},
                "first_seen_at": first_seen.isoformat() if first_seen else None,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
            })
        return findings

    def get_threat_severity_counts(
        self,
        resource_uid: str,
        tenant_id: str,
    ) -> Dict[str, int]:
        """
        Return threat severity breakdown for a single resource.

        Returns:
            {"critical": int, "high": int, "medium": int, "low": int}
        """
        query = """
            SELECT
                LOWER(COALESCE(severity, 'medium')) AS severity,
                COUNT(*) AS cnt
            FROM threat_findings
            WHERE (resource_uid = %s OR resource_arn = %s)
              AND tenant_id = %s
            GROUP BY LOWER(COALESCE(severity, 'medium'))
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, (resource_uid, resource_uid, tenant_id))
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"Threat severity counts query failed: {e}")
            rows = []

        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in rows:
            sev = r.get("severity", "medium")
            if sev in counts:
                counts[sev] = int(r.get("cnt") or 0)
        return counts

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
