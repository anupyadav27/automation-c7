"""
Check Database Reader for Discovery Engine
Reads discovery definitions from the check engine's rule_discoveries table (cross-engine integration).
This eliminates the dependency on local YAML files for discovery configurations.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)


class CheckDBReader:
    """Reads rule/discovery definitions from the check database (cross-engine)"""

    def __init__(self, db_config: Optional[Dict] = None):
        """
        Initialize with check engine database connection config.
        Uses CHECK_DB_* environment variables (available via threat-engine-db-config configmap).
        """
        self.db_config = db_config or {
            "host": os.getenv("CHECK_DB_HOST", os.getenv("DB_HOST", "localhost")),
            "port": int(os.getenv("CHECK_DB_PORT", os.getenv("DB_PORT", "5432"))),
            "database": os.getenv("CHECK_DB_NAME", "threat_engine_check"),
            "user": os.getenv("CHECK_DB_USER", os.getenv("SHARED_DB_USER", "postgres")),
            "password": os.getenv("CHECK_DB_PASSWORD", os.getenv("SHARED_DB_PASSWORD", "")),
        }
        logger.info(
            f"CheckDBReader: Using check database: {self.db_config['database']} "
            f"on {self.db_config['host']}"
        )

    def _get_connection(self):
        """Get database connection to check engine DB"""
        return psycopg2.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
            connect_timeout=10,
        )

    def read_discoveries_config(self, service: str, provider: str = "aws") -> Optional[Dict]:
        """
        Read discovery definitions from rule_discoveries table for a specific service.

        The discoveries_data JSONB column has the same structure as the local YAML files:
        {
            "service": "rds",
            "provider": "aws",
            "services": {"client": "rds", "module": "boto3.client"},
            "discovery": [
                {"discovery_id": "aws.rds.describe_db_instances", "calls": [...], "emit": {...}},
                ...
            ]
        }

        Returns:
            Dict with discovery config, or None if not found
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT discoveries_data
                    FROM rule_discoveries
                    WHERE service = %s AND provider = %s AND is_active = TRUE
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (service, provider),
                )
                row = cur.fetchone()
                if row and row["discoveries_data"]:
                    data = row["discoveries_data"]
                    if isinstance(data, str):
                        data = json.loads(data)
                    logger.info(
                        f"Loaded discovery config for {provider}.{service} from database "
                        f"({len(data.get('discovery', []))} discoveries)"
                    )
                    return data
                return None
        except Exception as e:
            logger.warning(f"Failed to read discovery config from check DB for {service}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def read_all_discoveries_configs(self, provider: str = "aws") -> Dict[str, Dict]:
        """
        Read all discovery configs for a provider, grouped by service.

        Returns:
            Dict mapping service name to discovery config
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT service, discoveries_data, max_discovery_workers
                    FROM rule_discoveries
                    WHERE provider = %s AND is_active = TRUE
                    ORDER BY service
                    """,
                    (provider,),
                )
                result = {}
                for row in cur.fetchall():
                    data = row["discoveries_data"]
                    if isinstance(data, str):
                        data = json.loads(data)
                    if data and data.get("discovery"):
                        # Inject per-service worker limit from DB column
                        max_workers = row.get("max_discovery_workers")
                        if max_workers and max_workers > 0:
                            data["max_discovery_workers"] = max_workers
                        result[row["service"]] = data
                logger.info(
                    f"Loaded discovery configs for {len(result)} services from database"
                )
                return result
        except Exception as e:
            logger.warning(f"Failed to read all discovery configs from check DB: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    def get_check_services(self, provider: str = "aws") -> set:
        """Return set of services that have check rules in rule_metadata.

        These services need full discovery (independent + dependent).
        Services NOT in this set only need independent discoveries.
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT service FROM rule_metadata WHERE provider = %s",
                    (provider,),
                )
                services = {row[0] for row in cur.fetchall() if row[0]}
                logger.info(f"Loaded {len(services)} services with check rules from database")
                return services
        except Exception as e:
            logger.warning(f"Failed to read check services: {e}")
            return set()
        finally:
            if conn:
                conn.close()

    def check_connection(self) -> bool:
        """Test if check database connection is working"""
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.close()
            return True
        except Exception as e:
            logger.warning(f"Check DB connection test failed: {e}")
            return False
