"""
Discovery Reader Factory

Factory to return appropriate discovery reader based on environment.
Uses consolidated database system when USE_DATABASE=true.

=== DATABASE & TABLE MAP ===
This factory constructs the DB connection URL for DiscoveryDBReader.

Database: threat_engine_discoveries (DISCOVERIES DB)
Env: DISCOVERIES_DB_HOST / DISCOVERIES_DB_PORT / DISCOVERIES_DB_NAME / DISCOVERIES_DB_USER / DISCOVERIES_DB_PASSWORD
     DISCOVERIES_DB_SCHEMA (optional, defaults to DB_SCHEMA or "public")
     USE_DATABASE ("true" to enable DB mode; "false" uses NDJSON files)

When USE_DATABASE=false:
  Uses DiscoveryReader (file-based) reading from DISCOVERY_BASE_PATH

When USE_DATABASE=true:
  Builds postgresql:// URL and returns DiscoveryDBReader(db_url, tenant_id)
  See discovery_db_reader.py for tables accessed.

Tables READ:  None directly (delegates to DiscoveryDBReader)
Tables WRITTEN: None
===
"""

import os
import sys
from typing import Union, Optional
from .discovery_reader import DiscoveryReader
from .discovery_db_reader import DiscoveryDBReader

# Add consolidated_services to path
# Import local database config
from ..database.connection.database_config import get_database_config


def get_discovery_reader(tenant_id: Optional[str] = None) -> Union[DiscoveryReader, DiscoveryDBReader]:
    """
    Factory to return appropriate discovery reader based on environment.
    
    Args:
        tenant_id: Tenant identifier (required for database mode)
    
    Returns:
        DiscoveryReader (file-based) for local development
        DiscoveryDBReader (database-based) for production
    
    Environment Variables:
        USE_DATABASE: Set to "true" for database mode (default: "false")
        DB_SCHEMA: Schema search_path (default: "engine_inventory,engine_shared")
    """
    use_db = os.getenv("USE_DATABASE", "false").lower() == "true"
    
    if use_db:
        if not tenant_id:
            raise ValueError("tenant_id required when USE_DATABASE=true")
        
        # In split-engine architecture, inventory reads from the Discoveries DB
        # (not from the inventory DB).
        try:
            host = os.getenv("DISCOVERIES_DB_HOST", "localhost")
            port = os.getenv("DISCOVERIES_DB_PORT", "5432")
            db = os.getenv("DISCOVERIES_DB_NAME", "threat_engine_discoveries")
            user = os.getenv("DISCOVERIES_DB_USER", "discoveries_user")
            pwd = os.getenv("DISCOVERIES_DB_PASSWORD", "discoveries_password")
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
            # Optional schema search_path (defaults to public in split DBs)
            schema = os.getenv("DISCOVERIES_DB_SCHEMA", os.getenv("DB_SCHEMA", "public"))
            if schema:
                sep = "&" if "?" in db_url else "?"
                db_url = f"{db_url}{sep}options=-c%20search_path%3D{schema.replace(',', '%2C')}"
        except ImportError as e:
            raise RuntimeError(
                f"Failed to import consolidated database config: {e}. "
                "Consolidated database system is required when USE_DATABASE=true."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Failed to get consolidated DB config: {e}") from e
        
        return DiscoveryDBReader(db_url, tenant_id)
    else:
        # Local development mode - use NDJSON files
        discovery_base_path = os.getenv("DISCOVERY_BASE_PATH")
        return DiscoveryReader(discovery_base_path)
