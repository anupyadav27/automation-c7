"""
Resource Classifier

Uses pre-built classification index to determine if a discovery record
should be inventoried, used for enrichment only, or filtered.

Supports two modes:
  1. DB mode (USE_DATABASE=true): Reads from threat_engine_pythonsdk.resource_inventory
     and threat_engine_pythonsdk.enhancement_indexes for multi-CSP classification.
  2. File mode (default): Reads from local JSON config/aws_inventory_classification_index.json

=== DATABASE & TABLE MAP ===
Database (DB mode): threat_engine_pythonsdk (PYTHONSDK DB)
Env: PYTHONSDK_DB_HOST / PYTHONSDK_DB_PORT / PYTHONSDK_DB_NAME / PYTHONSDK_DB_USER / PYTHONSDK_DB_PASSWORD

Tables READ (DB mode):
  - resource_inventory   : _load_db_index()
      SELECT service_id, inventory_data FROM resource_inventory WHERE service_id LIKE '{csp_id}.%'
      Extracts resource_types[].resource_classification to build classification lookups.

  - enhancement_indexes  : _load_db_index()
      SELECT index_data FROM enhancement_indexes WHERE csp_id = %s AND index_type = 'inventory_classification'
      Provides pre-built by_discovery_operation / by_service_resource / by_service lookups.

Tables WRITTEN: None (read-only classifier)

File mode (fallback):
  Source: config/aws_inventory_classification_index.json (AWS only)
===
"""

import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case (e.g. DescribeInstances → describe_instances)."""
    s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class ResourceClassification(Enum):
    """Resource classification types"""
    PRIMARY = "primary"           # Should inventory
    SUB_RESOURCE = "sub_resource" # Don't inventory (enrichment only)
    EPHEMERAL = "ephemeral"       # Don't inventory
    CONFIG = "config"             # Don't inventory (enrichment only)
    UNKNOWN = "unknown"           # Default to inventory if has ARN


class InventoryDecision(Enum):
    """Final decision on whether to inventory"""
    INVENTORY = "inventory"           # Create asset
    ENRICHMENT_ONLY = "enrichment"    # Use for enrichment, don't create asset
    FILTER = "filter"                 # Ignore completely


# Map resource_classification → InventoryDecision
_CLASSIFICATION_TO_DECISION = {
    "PRIMARY_RESOURCE": InventoryDecision.INVENTORY,
    "SUB_RESOURCE": InventoryDecision.ENRICHMENT_ONLY,
    "CONFIGURATION": InventoryDecision.ENRICHMENT_ONLY,
    "EPHEMERAL": InventoryDecision.FILTER,
}


class ResourceClassifier:
    """Classifies discovery records using pre-built classification index.

    Supports multi-CSP classification via pythonsdk DB or local JSON file fallback.
    Also provides root/dependent operation detection for two-pass inventory orchestration.
    """

    def __init__(self, index_path: Optional[Path] = None, csp_id: Optional[str] = None):
        """
        Initialize classifier with classification index.

        Args:
            index_path: Path to classification index JSON file (file mode).
                       Default: inventory_engine/config/aws_inventory_classification_index.json
            csp_id: CSP identifier for DB-based classification (e.g., 'aws', 'azure', 'gcp').
                    If not set, auto-detected from discovery records.
        """
        self.csp_id = csp_id
        self._use_db = os.getenv("USE_DATABASE", "false").lower() == "true"

        # Cache: {csp_id: index_dict}
        self._db_indexes: Dict[str, Dict[str, Any]] = {}

        # Cache: {csp_id: {normalized_op: True/False}} — True = root/independent
        self._root_ops_cache: Dict[str, Dict[str, bool]] = {}

        # File-based index (legacy)
        if index_path is None:
            base_path = Path(__file__).parent.parent
            index_path = base_path / "config" / "aws_inventory_classification_index.json"
        self.index_path = index_path
        self.index = self._load_file_index()

    def _load_file_index(self) -> Dict[str, Any]:
        """Load classification index from local JSON file"""
        empty_index = {
            "classifications": {
                "by_discovery_operation": {},
                "by_service_resource": {},
                "by_service": {},
                "ephemeral_operations": [],
                "config_operations": [],
                "sub_resource_operations": []
            }
        }

        if not self.index_path.exists():
            return empty_index

        try:
            with open(self.index_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load classification index from {self.index_path}: {e}")
            return empty_index

    def _get_db_index(self, csp_id: str) -> Dict[str, Any]:
        """
        Load or return cached DB-based classification index for a CSP.

        Reads from threat_engine_pythonsdk:
          1. enhancement_indexes (pre-built classification lookup)
          2. resource_inventory (per-service resource type classifications)
        """
        if csp_id in self._db_indexes:
            return self._db_indexes[csp_id]

        index = self._load_db_index(csp_id)
        self._db_indexes[csp_id] = index
        return index

    def _load_db_index(self, csp_id: str) -> Dict[str, Any]:
        """Load classification index from pythonsdk DB for a given CSP."""
        empty_index = {
            "classifications": {
                "by_discovery_operation": {},
                "by_service_resource": {},
                "by_service": {},
                "ephemeral_operations": [],
                "config_operations": [],
                "sub_resource_operations": []
            }
        }

        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError:
            logger.warning("psycopg2 not available — falling back to file-based classification")
            return empty_index

        host = os.getenv("PYTHONSDK_DB_HOST", os.getenv("DISCOVERIES_DB_HOST", "localhost"))
        port = os.getenv("PYTHONSDK_DB_PORT", os.getenv("DISCOVERIES_DB_PORT", "5432"))
        db = os.getenv("PYTHONSDK_DB_NAME", "threat_engine_pythonsdk")
        user = os.getenv("PYTHONSDK_DB_USER", os.getenv("DISCOVERIES_DB_USER", "postgres"))
        pwd = os.getenv("PYTHONSDK_DB_PASSWORD", os.getenv("DISCOVERIES_DB_PASSWORD", ""))
        db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

        try:
            conn = psycopg2.connect(db_url)
        except Exception as e:
            logger.warning(f"Cannot connect to pythonsdk DB for CSP={csp_id}: {e}")
            return empty_index

        try:
            # Step 1: Try enhancement_indexes first (pre-built, fast)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT index_data FROM enhancement_indexes
                    WHERE csp_id = %s AND index_type = 'inventory_classification'
                """, (csp_id,))
                row = cur.fetchone()
                if row and row.get("index_data"):
                    index_data = row["index_data"]
                    if isinstance(index_data, str):
                        index_data = json.loads(index_data)
                    # enhancement_indexes stores the full classification structure
                    if "classifications" in index_data:
                        logger.info(f"Loaded classification index from enhancement_indexes for CSP={csp_id}")
                        return index_data

            # Step 2: Build index from resource_inventory rows
            by_discovery_operation = {}
            by_service = {}
            by_service_resource = {}
            ephemeral_ops = []
            config_ops = []
            sub_resource_ops = []

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT service_id, inventory_data FROM resource_inventory
                    WHERE service_id LIKE %s
                """, (f"{csp_id}.%",))
                rows = cur.fetchall()

            for row in rows:
                service_id = row["service_id"]
                inv_data = row["inventory_data"]
                if isinstance(inv_data, str):
                    inv_data = json.loads(inv_data)

                # Extract service name (without CSP prefix)
                service_name = service_id.split(".", 1)[1] if "." in service_id else service_id

                primary_resources = []
                sub_resources = []
                config_resources = []
                ephemeral_resources = []

                for rt in inv_data.get("resources", inv_data.get("resource_types", [])):
                    rt_name = rt.get("resource_type", "")
                    classification = rt.get("classification", rt.get("resource_classification", ""))
                    operations = rt.get("all_operations", rt.get("operations", []))

                    # Map to service.resource_type key
                    sr_key = f"{service_name}.{rt_name}".lower()

                    # Determine should_inventory / use_for_enrichment from classification
                    should_inv = classification == "PRIMARY_RESOURCE"
                    use_enrich = classification in ("SUB_RESOURCE", "CONFIGURATION")
                    cls_label = {
                        "PRIMARY_RESOURCE": "primary",
                        "SUB_RESOURCE": "sub_resource",
                        "CONFIGURATION": "config",
                        "EPHEMERAL": "ephemeral",
                    }.get(classification, "unknown")

                    by_service_resource[sr_key] = {
                        "should_inventory": should_inv,
                        "use_for_enrichment": use_enrich,
                        "classification": cls_label,
                    }

                    # Build by_discovery_operation and per-classification op lists.
                    # An operation may appear in multiple resource types (e.g.
                    # ListRoles → PRIMARY via user_detail_list AND SUB_RESOURCE
                    # via rol_role).  PRIMARY always wins.
                    for op in operations:
                        op_key = f"{service_name}.{_camel_to_snake(op)}"
                        existing = by_discovery_operation.get(op_key)
                        if existing and existing.get("should_inventory"):
                            continue  # Already marked as PRIMARY — don't downgrade
                        by_discovery_operation[op_key] = {
                            "should_inventory": should_inv,
                            "use_for_enrichment": use_enrich,
                            "classification": cls_label,
                        }

                    if classification == "PRIMARY_RESOURCE":
                        primary_resources.append(rt_name.lower())
                    elif classification == "SUB_RESOURCE":
                        sub_resources.append(rt_name.lower())
                        for op in operations:
                            sub_resource_ops.append(f"{service_name}.{_camel_to_snake(op)}")
                    elif classification == "CONFIGURATION":
                        config_resources.append(rt_name.lower())
                        for op in operations:
                            config_ops.append(f"{service_name}.{_camel_to_snake(op)}")
                    elif classification == "EPHEMERAL":
                        ephemeral_resources.append(rt_name.lower())
                        for op in operations:
                            ephemeral_ops.append(f"{service_name}.{_camel_to_snake(op)}")

                by_service[service_name] = {
                    "primary_resources": primary_resources,
                    "sub_resources": sub_resources,
                    "config_resources": config_resources,
                    "ephemeral_resources": ephemeral_resources,
                }

            built_index = {
                "classifications": {
                    "by_discovery_operation": by_discovery_operation,
                    "by_service_resource": by_service_resource,
                    "by_service": by_service,
                    "ephemeral_operations": ephemeral_ops,
                    "config_operations": config_ops,
                    "sub_resource_operations": sub_resource_ops,
                }
            }

            logger.info(f"Built classification index from resource_inventory for CSP={csp_id}: "
                       f"{len(by_service)} services, {len(by_service_resource)} resource types, "
                       f"{len(by_discovery_operation)} operations mapped")
            return built_index

        except Exception as e:
            logger.warning(f"Failed to load classification from pythonsdk DB for CSP={csp_id}: {e}")
            return empty_index
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _get_index_for_csp(self, csp_id: str) -> Dict[str, Any]:
        """Get the appropriate classification index for a CSP."""
        if self._use_db:
            db_index = self._get_db_index(csp_id)
            # If DB index has data, use it
            if db_index.get("classifications", {}).get("by_service", {}):
                return db_index

        # Fallback to file-based index (only meaningful for AWS)
        if csp_id == "aws":
            return self.index

        # For non-AWS CSPs without DB, return empty index (everything defaults to INVENTORY)
        return {
            "classifications": {
                "by_discovery_operation": {},
                "by_service_resource": {},
                "by_service": {},
                "ephemeral_operations": [],
                "config_operations": [],
                "sub_resource_operations": []
            }
        }

    def _load_root_ops(self, csp_id: str) -> Dict[str, bool]:
        """
        Load root/independent operation flags from pythonsdk DB.

        Root operations (operation_type='independent', is_root_operation=True)
        discover PRIMARY resources. Dependent operations enrich them.

        Returns:
            Dict mapping normalized operation key (e.g. 's3.list_buckets') to True (root) / False (dependent).
        """
        if csp_id in self._root_ops_cache:
            return self._root_ops_cache[csp_id]

        root_ops: Dict[str, bool] = {}
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            host = os.getenv("PYTHONSDK_DB_HOST", os.getenv("DISCOVERIES_DB_HOST", "localhost"))
            port = os.getenv("PYTHONSDK_DB_PORT", os.getenv("DISCOVERIES_DB_PORT", "5432"))
            db = os.getenv("PYTHONSDK_DB_NAME", "threat_engine_pythonsdk")
            user = os.getenv("PYTHONSDK_DB_USER", os.getenv("DISCOVERIES_DB_USER", "postgres"))
            pwd = os.getenv("PYTHONSDK_DB_PASSWORD", os.getenv("DISCOVERIES_DB_PASSWORD", ""))
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

            conn = psycopg2.connect(db_url)
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT o.operation_name, o.operation_type, o.is_root_operation,
                               s.service_id
                        FROM operations o
                        JOIN services s ON o.service_id = s.service_id
                        WHERE s.csp_id = %s AND o.is_discovery = true
                    """, (csp_id,))
                    for row in cur:
                        service_id = row["service_id"]
                        # service_id format: "aws.s3" → extract "s3"
                        svc_name = service_id.split(".", 1)[1] if "." in service_id else service_id
                        op_name = row["operation_name"]
                        op_key = f"{svc_name}.{_camel_to_snake(op_name)}"
                        is_root = (
                            row.get("is_root_operation", False) or
                            row.get("operation_type") == "independent"
                        )
                        root_ops[op_key] = is_root
                logger.info(f"Loaded {len(root_ops)} discovery ops for CSP={csp_id} "
                           f"({sum(1 for v in root_ops.values() if v)} root, "
                           f"{sum(1 for v in root_ops.values() if not v)} dependent)")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to load root ops from pythonsdk DB for CSP={csp_id}: {e}")

        self._root_ops_cache[csp_id] = root_ops
        return root_ops

    def is_root_operation(self, discovery_record: Dict[str, Any]) -> bool:
        """
        Check if a discovery record is from a root/independent operation.

        Root operations discover PRIMARY resources (list_buckets, list_roles).
        Dependent operations enrich existing resources (get_bucket_versioning, get_role).

        Used by the orchestrator for two-pass processing:
          Pass 1: root operations → create assets
          Pass 2: dependent operations → enrich existing assets

        Args:
            discovery_record: Discovery record dict

        Returns:
            True if root/independent, False if dependent
        """
        discovery_id = discovery_record.get("discovery_id", "")
        csp_id = self.csp_id or self._detect_csp(discovery_record)
        normalized_id = self.normalize_discovery_id(discovery_id)

        # Check pythonsdk root ops index
        root_ops = self._load_root_ops(csp_id)
        if normalized_id in root_ops:
            return root_ops[normalized_id]

        # Heuristic: operations starting with list_ are typically root
        op_part = normalized_id.split(".")[-1] if "." in normalized_id else normalized_id
        if op_part.startswith("list_"):
            return True

        # Records with _dependent_data are root (they carried enrichment data)
        emitted = discovery_record.get("emitted_fields", {})
        if isinstance(emitted, dict) and "_dependent_data" in emitted:
            return True

        # Records with nested operation keys (get_, describe_) are dependent
        if op_part.startswith("get_") or op_part.startswith("describe_"):
            return False

        # Default: treat as root if it has a resource_arn/resource_uid
        return bool(discovery_record.get("resource_arn") or discovery_record.get("resource_uid"))

    def _detect_csp(self, discovery_record: Dict[str, Any]) -> str:
        """Detect CSP from discovery record."""
        provider = discovery_record.get("provider", "aws").lower()
        return provider

    def normalize_discovery_id(self, discovery_id: str) -> str:
        """Normalize discovery ID to match index format"""
        # Remove csp. prefix if present (e.g., aws.s3.list_buckets → s3.list_buckets)
        for prefix in ["aws.", "azure.", "gcp.", "k8s.", "oci.", "ibm.", "alicloud."]:
            if discovery_id.lower().startswith(prefix):
                return discovery_id[len(prefix):].lower()
        return discovery_id.lower()

    def classify_discovery_record(self, discovery_record: Dict[str, Any]) -> InventoryDecision:
        """
        Classify a discovery record and return inventory decision.

        Supports all 7 CSPs (aws, azure, gcp, k8s, oci, ibm, alicloud).
        Uses DB-based classification when USE_DATABASE=true, file-based fallback for AWS.

        Args:
            discovery_record: Discovery record from discoveries engine

        Returns:
            InventoryDecision enum value
        """
        discovery_id = discovery_record.get("discovery_id", "")
        service = discovery_record.get("service", "")
        resource_arn = discovery_record.get("resource_arn", "")
        resource_uid = discovery_record.get("resource_uid", "")
        resource_id = discovery_record.get("resource_id", "")
        emitted_fields = discovery_record.get("emitted_fields", {})

        # Use resource_uid as fallback for resource_arn (non-AWS CSPs don't use ARNs)
        resource_identifier = resource_arn or resource_uid or resource_id

        # Step 1: Check if record has resource identifier
        if not resource_identifier:
            return InventoryDecision.FILTER  # No resource to inventory

        # Detect CSP and get appropriate index
        csp_id = self.csp_id or self._detect_csp(discovery_record)
        index = self._get_index_for_csp(csp_id)

        # Step 2: Check discovery operation in index
        normalized_id = self.normalize_discovery_id(discovery_id)

        # Check by_discovery_operation mapping FIRST — this has the most accurate
        # per-operation classification.  An operation that appears in multiple
        # resource types (e.g. ListRoles → PRIMARY via user_detail_list AND
        # SUB_RESOURCE via rol_role) will have the last-written classification,
        # which may be wrong.  So if the map says "should_inventory", trust it;
        # if not, fall through to the flat lists for confirmation.
        op_classification = index["classifications"]["by_discovery_operation"].get(normalized_id)
        if op_classification:
            if op_classification.get("should_inventory", False):
                return InventoryDecision.INVENTORY
            # The map says don't inventory — use its classification
            if op_classification.get("use_for_enrichment", False):
                return InventoryDecision.ENRICHMENT_ONLY
            return InventoryDecision.FILTER

        # Flat operation lists (for operations not in by_discovery_operation)
        ephemeral_ops = index["classifications"].get("ephemeral_operations", [])
        if normalized_id in ephemeral_ops:
            return InventoryDecision.FILTER

        config_ops = index["classifications"].get("config_operations", [])
        if normalized_id in config_ops:
            return InventoryDecision.ENRICHMENT_ONLY

        sub_resource_ops = index["classifications"].get("sub_resource_operations", [])
        if normalized_id in sub_resource_ops:
            return InventoryDecision.ENRICHMENT_ONLY

        # Step 3: Try to classify by service + resource type
        if service:
            resource_type = self._extract_resource_type(emitted_fields, resource_arn, service)
            if resource_type:
                service_resource_key = f"{service}.{resource_type}"
                resource_classification = index["classifications"]["by_service_resource"].get(service_resource_key)
                if resource_classification:
                    if not resource_classification.get("should_inventory", False):
                        if resource_classification.get("use_for_enrichment", False):
                            return InventoryDecision.ENRICHMENT_ONLY
                        return InventoryDecision.FILTER
                    return InventoryDecision.INVENTORY

        # Step 4: Default decision - if has ARN/UID, likely a primary resource
        if resource_arn:
            if self._is_ephemeral_arn(resource_arn):
                return InventoryDecision.FILTER
            return InventoryDecision.INVENTORY

        # For non-AWS CSPs, resource_uid without ARN is also a valid identifier
        if resource_uid:
            return InventoryDecision.INVENTORY

        # Step 5: If no ARN/UID but has ID, check if it's a list/describe operation
        if resource_id:
            if any(op in discovery_id.lower() for op in ["list_", "describe_", "get_"]):
                return InventoryDecision.INVENTORY

        # Default: filter if we can't determine
        return InventoryDecision.FILTER

    def _extract_resource_type(self, emitted_fields: Dict[str, Any], resource_arn: str, service: str) -> Optional[str]:
        """Extract resource type from emitted fields or ARN"""
        # Try ARN pattern first (AWS)
        if resource_arn and resource_arn.startswith("arn:"):
            arn_parts = resource_arn.split(":")
            if len(arn_parts) >= 6:
                resource_part = arn_parts[5]
                if "/" in resource_part:
                    resource_type = resource_part.split("/")[0]
                    resource_type = resource_type.replace("-", "_")
                    return resource_type

        # Try common field names
        for field in ["ResourceType", "resource_type", "Type", "type", "kind"]:
            if field in emitted_fields:
                return str(emitted_fields[field]).lower()

        return None

    def get_service_summary(self, service: str, csp_id: Optional[str] = None) -> Dict[str, Any]:
        """Return service-level classification summary if available."""
        csp_id = csp_id or self.csp_id or "aws"
        index = self._get_index_for_csp(csp_id)
        return index["classifications"].get("by_service", {}).get(service, {})

    def resolve_resource_type(self, service: str, emitted_fields: Dict[str, Any], resource_arn: str,
                              csp_id: Optional[str] = None) -> Optional[str]:
        """
        Resolve a specific resource type for a service using the classification index.

        Returns:
            resource_type string (without service prefix) or None
        """
        csp_id = csp_id or self.csp_id or "aws"
        service_summary = self.get_service_summary(service, csp_id)
        if not service_summary:
            return None

        candidate_types = (
            service_summary.get("primary_resources", []) +
            service_summary.get("ephemeral_resources", []) +
            service_summary.get("config_resources", []) +
            service_summary.get("sub_resources", [])
        )
        if not candidate_types:
            return None

        # Try to extract from ARN resource part
        arn_type = self._extract_resource_type(emitted_fields, resource_arn, service)
        if arn_type and arn_type in candidate_types:
            index = self._get_index_for_csp(csp_id)
            service_resource_key = f"{service}.{arn_type}"
            resource_info = index["classifications"]["by_service_resource"].get(service_resource_key)
            if resource_info and resource_info.get("normalized_type"):
                return resource_info["normalized_type"]
            return arn_type

        # Try to match resource type by emitted fields
        for field in ["ResourceType", "resource_type", "Type", "type", "kind"]:
            if field in emitted_fields:
                value = str(emitted_fields[field]).lower().replace("-", "_")
                if value in candidate_types:
                    index = self._get_index_for_csp(csp_id)
                    service_resource_key = f"{service}.{value}"
                    resource_info = index["classifications"]["by_service_resource"].get(service_resource_key)
                    if resource_info and resource_info.get("normalized_type"):
                        return resource_info["normalized_type"]
                    return value

        # Try partial matches
        if arn_type:
            for candidate in candidate_types:
                if arn_type in candidate or candidate in arn_type:
                    index = self._get_index_for_csp(csp_id)
                    service_resource_key = f"{service}.{candidate}"
                    resource_info = index["classifications"]["by_service_resource"].get(service_resource_key)
                    if resource_info and resource_info.get("normalized_type"):
                        return resource_info["normalized_type"]
                    return candidate

        return None

    def _is_ephemeral_arn(self, resource_arn: str) -> bool:
        """Check if ARN matches ephemeral patterns"""
        arn_lower = resource_arn.lower()

        ephemeral_patterns = [
            r':finding/',
            r':product/',
            r':job/',
            r':task/',
            r':workflow/',
            r':request/',
        ]

        for pattern in ephemeral_patterns:
            if re.search(pattern, arn_lower):
                return True

        return False

    def get_classification_info(self, discovery_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get detailed classification information for a discovery record.

        Returns:
            Dict with classification details or None
        """
        discovery_id = discovery_record.get("discovery_id", "")
        normalized_id = self.normalize_discovery_id(discovery_id)

        csp_id = self.csp_id or self._detect_csp(discovery_record)
        index = self._get_index_for_csp(csp_id)

        # Check operation mapping
        op_info = index["classifications"]["by_discovery_operation"].get(normalized_id)
        if op_info:
            return op_info

        # Check service + resource type
        service = discovery_record.get("service", "")
        emitted_fields = discovery_record.get("emitted_fields", {})
        resource_arn = discovery_record.get("resource_arn", "")

        resource_type = self._extract_resource_type(emitted_fields, resource_arn, service)
        if resource_type and service:
            service_resource_key = f"{service}.{resource_type}"
            return index["classifications"]["by_service_resource"].get(service_resource_key)

        return None
