"""
Shared utilities for inventory API routers.

Provides:
- _get_db_url()  — builds inventory DB URL with schema search_path
- _get_loader()  — returns a connected InventoryDBLoader
- _get_raw_conn() — returns a raw psycopg2 connection (for endpoints that need direct SQL)
- PROVIDER_COLORS / RELATION_FAMILY_MAP / classify_link_type — graph rendering constants
"""

import os
import psycopg2
from typing import Optional

from ..database.connection.database_config import get_database_config
from ..api.inventory_db_loader import InventoryDBLoader


def _get_db_url() -> str:
    """Build inventory DB URL with optional schema search_path."""
    db_config = get_database_config("inventory")
    db_url = db_config.connection_string
    schema = os.getenv("DB_SCHEMA", "public")
    sep = "&" if "?" in db_url else "?"
    return f"{db_url}{sep}options=-c%20search_path%3D{schema.replace(',', '%2C')}"


def _get_loader() -> InventoryDBLoader:
    """Return a connected InventoryDBLoader."""
    return InventoryDBLoader(_get_db_url())


def _get_raw_conn():
    """Return a raw psycopg2 connection to the inventory DB."""
    db_config = get_database_config("inventory")
    return psycopg2.connect(
        host=db_config.host,
        port=db_config.port,
        dbname=db_config.database,
        user=db_config.username,
        password=db_config.password,
        connect_timeout=5,
    )


# ── Graph rendering constants ────────────────────────────────────────────────

PROVIDER_COLORS = {
    "aws": "#FF9900", "azure": "#0078D4", "gcp": "#4285F4",
    "oci": "#F80000", "alicloud": "#FF6A00", "ibm": "#1F70C1",
}

RELATION_FAMILY_MAP = {
    "contained_by": "structural", "contains": "structural", "member_of": "structural",
    "attached_to": "structural", "associated_with": "structural", "references": "structural",
    "peers_with": "network", "connected_to": "network", "routes_to": "network",
    "forwards_to": "network", "serves_traffic_for": "network", "resolves_to": "network",
    "allows_traffic_from": "security", "allows_traffic_to": "security",
    "restricted_to": "security", "exposed_through": "security",
    "internet_connected": "security", "protected_by": "security",
    "uses": "identity", "assumes": "identity", "has_policy": "identity",
    "grants_access_to": "identity", "controlled_by": "identity", "authenticated_by": "identity",
    "encrypted_by": "data", "stores_data_in": "data", "backs_up_to": "data", "replicates_to": "data",
    "runs_on": "execution", "invokes": "execution", "triggers": "execution",
    "triggered_by": "execution", "publishes_to": "execution", "subscribes_to": "execution",
    "scales_with": "execution", "cached_by": "execution", "depends_on": "execution",
    "manages": "governance", "deployed_by": "governance", "applies_to": "governance",
    "complies_with": "governance", "logging_enabled_to": "governance",
    "monitored_by": "governance", "scanned_by": "governance",
}

ATTACK_PATH_CATEGORIES = {
    "initial_access", "privilege_escalation", "lateral_movement",
    "data_exfiltration", "persistence", "impact",
}


def classify_link_type(relation_type: str) -> str:
    """Classify a relation_type into a taxonomy family for graph rendering."""
    return RELATION_FAMILY_MAP.get(relation_type, "default")
