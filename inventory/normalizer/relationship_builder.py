"""
Relationship Builder

Builds relationship edges from normalized assets using DB-driven rules.

=== DATABASE & TABLE MAP ===
Source of truth: threat_engine_inventory (INVENTORY DB)
Table: resource_security_relationship_rules

Rules are loaded once per scan from the inventory DB — no local JSON files,
no dependency on the pythonsdk DB at runtime.

Tables READ:
  - resource_security_relationship_rules : SELECT from_resource_type, relation_type,
                                          to_resource_type, source_field,
                                          source_field_item, target_uid_pattern
                                   FROM   resource_security_relationship_rules
                                   WHERE  csp = %s AND is_active = TRUE

Tables WRITTEN: None (returns Relationship objects to callers)

Populate rules with:
  engine_inventory/scripts/load_relationship_rules_to_db.py
===
"""

import json
import logging
import os
import re
from typing import List, Dict, Any, Optional, Set

from ..schemas.asset_schema import Asset, Provider
from ..schemas.relationship_schema import Relationship, RelationType

logger = logging.getLogger(__name__)


class RelationshipBuilder:
    """Builds relationships between assets using inventory-DB-driven relationship rules."""

    def __init__(
        self,
        tenant_id: str,
        scan_run_id: str,
        csp_id: str = "aws",
        db_conn=None,
    ):
        """
        Args:
            tenant_id:    Tenant identifier
            scan_run_id:  Current scan run ID
            csp_id:       Cloud provider key (aws | azure | gcp | oci | ibm | alicloud | k8s)
            db_conn:      Open psycopg2 connection to the inventory DB.
                          When None the builder falls back to opening its own connection
                          via INVENTORY_DB_URL env var (or returns an empty rule set if
                          neither is available — relationships are skipped gracefully).
        """
        self.tenant_id = tenant_id
        self.scan_run_id = scan_run_id
        self.csp_id = csp_id
        self._owns_conn = False
        self._conn = db_conn or self._open_inventory_conn()
        self.relationship_index = self._load_rules_from_db()
        self.relation_types: Set[str] = {rt.value for rt in RelationType}

    # ------------------------------------------------------------------
    # DB connection helpers
    # ------------------------------------------------------------------

    def _open_inventory_conn(self):
        """Open a connection to the inventory DB using env vars."""
        db_url = os.getenv("INVENTORY_DB_URL")
        if db_url:
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                self._owns_conn = True
                return conn
            except Exception as exc:
                logger.warning(f"Cannot open inventory DB connection: {exc}")
        return None

    def close(self):
        """Close owned DB connection (if we opened it)."""
        if self._owns_conn and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # Load: read rules from resource_security_relationship_rules (inventory DB)
    # ------------------------------------------------------------------

    def _load_rules_from_db(self) -> Dict[str, Any]:
        """
        Load relationship rules for this CSP from resource_security_relationship_rules.

        Returns index keyed by from_resource_type:
            {"by_resource_type": {type_name: {"relationships": [...]}}}
        """
        if not self._conn:
            logger.warning(
                f"No inventory DB connection — relationship rules unavailable for {self.csp_id}. "
                "Run load_relationship_rules_to_db.py to populate the rules table."
            )
            return {}

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT from_resource_type, relation_type, to_resource_type,
                           source_field, source_field_item, target_uid_pattern
                    FROM   resource_security_relationship_rules
                    WHERE  csp = %s AND is_active = TRUE
                    ORDER BY from_resource_type, relation_type
                    """,
                    (self.csp_id,),
                )
                rows = cur.fetchall()

            by_resource_type: Dict[str, Dict] = {}
            for (from_type, rel_type, to_type,
                 source_field, source_field_item, target_pattern) in rows:
                if from_type not in by_resource_type:
                    by_resource_type[from_type] = {"relationships": []}
                by_resource_type[from_type]["relationships"].append({
                    "relation_type":      rel_type,
                    "target_type":        to_type,
                    "source_field":       source_field,
                    "source_field_item":  source_field_item,
                    "target_uid_pattern": target_pattern,
                })

            logger.info(
                f"Loaded {sum(len(v['relationships']) for v in by_resource_type.values())} "
                f"relationship rules from inventory DB for csp={self.csp_id} "
                f"({len(by_resource_type)} resource types)"
            )
            return {
                "version": "db",
                "source": "inventory_db:resource_security_relationship_rules",
                "classifications": {
                    "by_resource_type": by_resource_type,
                },
            }
        except Exception as exc:
            logger.error(f"Error loading relationship rules from DB for {self.csp_id}: {exc}")
            return {}

    # ------------------------------------------------------------------
    # Build: create Relationship edges from assets
    # ------------------------------------------------------------------

    def build_relationships(self, assets: List[Asset]) -> List[Relationship]:
        """
        Build relationships from assets using the loaded rule index.

        For each asset:
          1. Look up relationship patterns for its resource_type
          2. Extract field values from asset metadata
          3. Resolve target UIDs from patterns
          4. Emit Relationship edges
        """
        relationships: List[Relationship] = []

        assets_by_uid = {asset.resource_uid: asset for asset in assets}
        assets_by_type: Dict[str, List[Asset]] = {}
        for asset in assets:
            assets_by_type.setdefault(asset.resource_type, []).append(asset)

        for asset in assets:
            relationships.extend(
                self._extract_relationships_from_asset(asset, assets_by_uid, assets_by_type)
            )

        # Special case: internet exposure (public IPs / public buckets)
        relationships.extend(self._build_internet_exposure(assets_by_type))

        return relationships

    def _extract_relationships_from_asset(
        self,
        asset: Asset,
        assets_by_uid: Dict[str, Asset],
        assets_by_type: Dict[str, List[Asset]],
    ) -> List[Relationship]:
        """Extract all relationships for a single asset."""
        relationships: List[Relationship] = []

        if not self.relationship_index:
            return relationships

        by_resource = (
            self.relationship_index
            .get("classifications", {})
            .get("by_resource_type", {})
        )
        resource_patterns = by_resource.get(asset.resource_type, {}).get("relationships", [])
        if not resource_patterns:
            return relationships

        for pattern in resource_patterns:
            rel_type_str = pattern.get("relation_type", "")
            if rel_type_str not in self.relation_types:
                continue

            try:
                rel_type = RelationType(rel_type_str)
            except ValueError:
                continue

            target_type        = pattern.get("target_type", "")
            source_field       = pattern.get("source_field", "")
            target_uid_pattern = pattern.get("target_uid_pattern", "")
            source_field_item  = pattern.get("source_field_item")

            if not source_field or not target_uid_pattern:
                continue

            field_values = self._extract_field_values(
                asset.metadata, source_field, source_field_item
            )

            for field_value in field_values:
                if not field_value:
                    continue

                target_uid = self._resolve_target_uid(
                    target_uid_pattern, field_value, asset, target_type
                )
                if not target_uid:
                    continue

                relationships.append(Relationship(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.scan_run_id,
                    provider=asset.provider.value,
                    account_id=asset.account_id,
                    region=asset.region,
                    relation_type=rel_type,
                    from_uid=asset.resource_uid,
                    to_uid=target_uid,
                    from_resource_type=asset.resource_type,
                    to_resource_type=target_type,
                    properties=self._extract_relationship_properties(
                        pattern, field_value, asset
                    ),
                ))

        return relationships

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_field_values(
        self,
        metadata: Dict[str, Any],
        source_field: str,
        source_field_item: Optional[str] = None,
    ) -> List[Any]:
        """
        Extract field value(s) from asset metadata.

        Supports:
        - Simple fields:               "VpcId"
        - Nested dot-paths:            "IamInstanceProfile.Arn"
        - Array fields:                "SecurityGroups"        (returns whole list)
        - Array + item extraction:     source_field="SecurityGroups", source_field_item="GroupId"
        - Nested array dot-paths:      "VpcConfig.SubnetIds"
        - JSON-string auto-parse:      field value is a JSON string → strings extracted
        """
        if not source_field:
            return []

        # metadata may contain "emitted_fields" (explicit extractions take priority)
        # or direct raw-response keys — the normalizer already merges both.
        data_source = metadata.get("emitted_fields", metadata)

        # ── Nested dot-path (e.g. "IamInstanceProfile.Arn") ─────────────────
        if "." in source_field and not source_field.endswith("[]"):
            parts = source_field.split(".")
            value = data_source
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return []
                if value is None:
                    return []

            if isinstance(value, list):
                if source_field_item:
                    extracted: List[Any] = []
                    for item in value:
                        if isinstance(item, dict):
                            iv = item.get(source_field_item)
                            if iv is not None:
                                extracted.append(iv)
                        elif isinstance(item, str):
                            extracted.append(item)
                    return extracted
                return value

            if source_field_item and isinstance(value, dict):
                iv = value.get(source_field_item)
                return [iv] if iv is not None else []

            return [value]

        # ── Simple field ─────────────────────────────────────────────────────
        field_value = data_source.get(source_field)
        if field_value is None:
            return []

        if source_field_item and isinstance(field_value, list):
            extracted = []
            for item in field_value:
                if isinstance(item, dict):
                    item_value = item.get(source_field_item)
                    if item_value:
                        extracted.append(item_value)
                elif isinstance(item, str):
                    extracted.append(item)
            return extracted

        if isinstance(field_value, list):
            return field_value

        # Dict: collect all embedded string values
        if isinstance(field_value, dict):
            results: List[Any] = []
            def _collect(obj: Any) -> None:
                if isinstance(obj, dict):
                    for v in obj.values():
                        _collect(v)
                elif isinstance(obj, list):
                    for it in obj:
                        _collect(it)
                elif isinstance(obj, str):
                    results.append(obj)
            _collect(field_value)
            return list(dict.fromkeys(results))

        # JSON string → auto-parse
        if isinstance(field_value, str):
            s = field_value.strip()
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    parsed = json.loads(s)
                    results = []
                    def _collect_parsed(obj: Any) -> None:
                        if isinstance(obj, dict):
                            for v in obj.values():
                                _collect_parsed(v)
                        elif isinstance(obj, list):
                            for it in obj:
                                _collect_parsed(it)
                        elif isinstance(obj, str):
                            results.append(obj)
                    _collect_parsed(parsed)
                    return list(dict.fromkeys(results))
                except Exception:
                    pass

        return [field_value]

    # ------------------------------------------------------------------
    # UID resolution
    # ------------------------------------------------------------------

    def _extract_account_from_uid(self, resource_uid: str) -> Optional[str]:
        if not resource_uid or not resource_uid.startswith("arn:"):
            return None
        parts = resource_uid.split(":")
        return parts[4] if len(parts) >= 5 else None

    def _extract_region_from_uid(self, resource_uid: str) -> Optional[str]:
        if not resource_uid or not resource_uid.startswith("arn:"):
            return None
        parts = resource_uid.split(":")
        region = parts[3] if len(parts) >= 4 else None
        return region if region else None

    def _resolve_target_uid(
        self,
        pattern: str,
        field_value: Any,
        asset: Asset,
        target_type: str,
    ) -> Optional[str]:
        """
        Resolve target UID from pattern.

        Pattern forms:
          "{Arn}"                                    → use field_value directly
          "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}" → substitute variables
        """
        if not pattern or not field_value:
            return None

        # Direct single-placeholder: e.g. "{Arn}", "{RoleArn}"
        if pattern.startswith("{") and pattern.endswith("}"):
            if isinstance(field_value, str) and field_value.startswith("arn:"):
                return field_value
            if isinstance(field_value, (dict, list)):
                return None
            return str(field_value) if field_value else None

        # Template with variables
        resolved = pattern
        account_id = self._extract_account_from_uid(asset.resource_uid) or asset.account_id
        region     = self._extract_region_from_uid(asset.resource_uid) or asset.region or ""

        resolved = resolved.replace("{region}", region)
        resolved = resolved.replace("{account_id}", account_id)

        # Replace remaining {Field} placeholders with field_value
        for placeholder in re.findall(r'\{([^}]+)\}', resolved):
            if placeholder in ("region", "account_id"):
                continue
            resolved = resolved.replace(f"{{{placeholder}}}", str(field_value))

        # Unresolved placeholders → invalid
        if "{" in resolved or "}" in resolved:
            return None

        return resolved if resolved and resolved != pattern else None

    def _extract_relationship_properties(
        self,
        pattern: Dict[str, Any],
        field_value: Any,
        asset: Asset,
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        if (pattern.get("relation_type") == "attached_to"
                and "security-group" in pattern.get("target_type", "")):
            props["direction"] = "inbound"
        if isinstance(field_value, (str, int)):
            props["source_field_value"] = str(field_value)
        return props

    # ------------------------------------------------------------------
    # Internet exposure (special-case, no DB rule needed)
    # ------------------------------------------------------------------

    def _build_internet_exposure(
        self, assets_by_type: Dict[str, List[Asset]]
    ) -> List[Relationship]:
        relationships: List[Relationship] = []

        for instance in assets_by_type.get("ec2.instance", []):
            public_ip = (
                instance.metadata.get("public_ip")
                or instance.metadata.get("PublicIpAddress")
            )
            if public_ip:
                relationships.append(Relationship(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.scan_run_id,
                    provider=instance.provider.value,
                    account_id=instance.account_id,
                    region=instance.region,
                    relation_type=RelationType.INTERNET_CONNECTED,
                    from_uid=instance.resource_uid,
                    to_uid="internet:0.0.0.0/0",
                    from_resource_type="ec2.instance",
                    to_resource_type=None,
                    properties={"public_ip": public_ip},
                ))

        for bucket in assets_by_type.get("s3.bucket", []):
            if bucket.metadata.get("public_access") or bucket.tags.get("Public"):
                relationships.append(Relationship(
                    tenant_id=self.tenant_id,
                    scan_run_id=self.scan_run_id,
                    provider=bucket.provider.value,
                    account_id=bucket.account_id,
                    region=bucket.region,
                    relation_type=RelationType.INTERNET_CONNECTED,
                    from_uid=bucket.resource_uid,
                    to_uid="internet:0.0.0.0/0",
                    from_resource_type="s3.bucket",
                    to_resource_type=None,
                    properties={"public_access": True},
                ))

        return relationships
