"""
Asset Normalizer

Transforms raw provider JSON into canonical Asset records.

=== DATABASE & TABLE MAP ===
Database: None — pure transformation logic (no direct DB access).

Input:  Raw discovery dicts from DiscoveryDBReader (discovery_findings rows)
Output: List[Asset] Pydantic models consumed by IndexWriter and RelationshipBuilder

Discovery emitted_fields structure (three patterns):
  1. Flat top-level — list_roles:   {Arn, RoleName, Path, CreateDate, resource_arn, _raw_response}
  2. Nested under operation key — get_role:  {get_role: {Role: {Arn, RoleName,...}}, resource_arn, _raw_response}
  3. With dependent data — list_buckets: {Name, BucketArn, _dependent_data: {get_bucket_versioning: {...}}, _enriched_from: [...]}

The normalizer deep-extracts names, tags, resource IDs, and configuration properties
from all three patterns to build rich Asset records.

Tables READ:  None (receives data from callers)
Tables WRITTEN: None (returns Asset objects to callers)
===
"""

import json
import logging
from typing import List, Dict, Any, Optional
from ..schemas.asset_schema import Asset, Provider, Scope, compute_asset_hash
from .resource_classifier import ResourceClassifier, InventoryDecision

# ARN normalizer — converts short-form UIDs to canonical ARN format
try:
    from shared.common.arn import normalize_resource_uid, is_arn
except ImportError:
    from providers.common.arn import normalize_resource_uid, is_arn

logger = logging.getLogger(__name__)


class AssetNormalizer:
    """Normalizes raw provider data to canonical assets"""

    def __init__(self, tenant_id: str, scan_run_id: str):
        self.tenant_id = tenant_id
        self.scan_run_id = scan_run_id
        self.classifier = ResourceClassifier()


    def _extract_tags(self, resource: Dict[str, Any]) -> Dict[str, str]:
        """Extract tags from resource data (supports nested discovery structures)."""
        tags = {}

        # AWS Tags format: [{Key: ..., Value: ...}]
        if "Tags" in resource and isinstance(resource["Tags"], list):
            for tag in resource["Tags"]:
                if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                    tags[tag["Key"]] = tag["Value"]

        # Direct tags dict
        if "tags" in resource and isinstance(resource["tags"], dict):
            tags.update(resource["tags"])

        # Azure / GCP / generic tags
        if "labels" in resource and isinstance(resource["labels"], dict):
            tags.update(resource["labels"])

        # Deep search: tags inside _dependent_data (e.g. get_bucket_tagging, list_tags)
        dep_data = resource.get("_dependent_data", {})
        if isinstance(dep_data, dict):
            for op_name, op_result in dep_data.items():
                if not isinstance(op_result, dict):
                    continue
                # AWS get_bucket_tagging → {TagSet: [{Key, Value}]}
                tag_set = op_result.get("TagSet")
                if isinstance(tag_set, list):
                    for tag in tag_set:
                        if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                            tags[tag["Key"]] = str(tag["Value"])
                # AWS list_tags → {Tags: [{Key, Value}]}
                tag_list = op_result.get("Tags")
                if isinstance(tag_list, list):
                    for tag in tag_list:
                        if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                            tags[tag["Key"]] = str(tag["Value"])
                # AWS list_tags_for_resource → {tags: {k: v}}
                if "tags" in op_result and isinstance(op_result["tags"], dict):
                    tags.update(op_result["tags"])

        # Deep search: tags inside nested operation keys (get_role → {Role: {Tags: [...]}})
        for key, val in resource.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            # Traverse one level deeper for nested dicts containing Tags
            for inner_key, inner_val in val.items():
                if isinstance(inner_val, dict):
                    inner_tags = inner_val.get("Tags")
                    if isinstance(inner_tags, list):
                        for tag in inner_tags:
                            if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                                tags[tag["Key"]] = str(tag["Value"])

        return tags

    def _flatten_emitted_fields(self, emitted_fields: Dict[str, Any], discovery_id: str) -> Dict[str, Any]:
        """
        Flatten emitted_fields that may have data nested under operation keys.

        Discovery engine stores data in three patterns:
          1. Flat:   {Name, Arn, RoleName, ...}
          2. Nested: {get_role: {Role: {Arn, RoleName, ...}}, resource_arn, _raw_response}
          3. Mixed:  {Name, BucketArn, _dependent_data: {...}, _enriched_from: [...]}

        Returns a flat dict with all resource fields merged for easy extraction.
        """
        flat = {}

        # Copy top-level scalar/simple fields (skip internal _ keys and nested dicts)
        for key, val in emitted_fields.items():
            if key.startswith("_"):
                continue
            if not isinstance(val, dict) and not isinstance(val, list):
                flat[key] = val
            elif key in ("Tags", "tags", "labels"):
                flat[key] = val  # Keep tag structures

        # Extract from nested operation keys (pattern 2: get_role → {Role: {...}})
        # The operation key matches the last part of discovery_id
        op_suffix = discovery_id.split(".")[-1] if discovery_id else ""
        for key, val in emitted_fields.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            # Operation key matches (e.g. "get_role", "get_function")
            if key == op_suffix or key.startswith("get_") or key.startswith("describe_"):
                # Traverse nested structure to find actual resource dict
                for inner_key, inner_val in val.items():
                    if isinstance(inner_val, dict):
                        # This is the resource object (Role, Function, etc.)
                        for rk, rv in inner_val.items():
                            if rk not in flat and not isinstance(rv, (dict, list)):
                                flat[rk] = rv
                            elif rk in ("Tags", "tags", "labels") and rk not in flat:
                                flat[rk] = rv
                    elif not isinstance(inner_val, list) and inner_key not in flat:
                        flat[inner_key] = inner_val

        # Also include raw_response if it has useful top-level fields
        raw_resp = emitted_fields.get("_raw_response", {})
        if isinstance(raw_resp, dict):
            for key, val in raw_resp.items():
                if key not in flat and not isinstance(val, (dict, list)):
                    flat[key] = val
                elif key in ("Tags", "tags") and key not in flat:
                    flat[key] = val

        return flat
    
    def normalize_from_discovery(
        self,
        discovery_record: Dict[str, Any],
        raw_ref: str,
        skip_classification: bool = False
    ) -> Optional[Asset]:
        """
        Normalize a discovery record to an Asset.

        Args:
            discovery_record: Discovery record from configscan-engine
            raw_ref: Reference to source file
            skip_classification: If True, skip classification check (caller already filtered).
                                Used by the two-pass orchestrator which classifies externally.

        Returns:
            Asset or None if record doesn't represent a resource
        """
        # Extract metadata from discovery record
        provider_str = discovery_record.get("provider", "aws")
        provider = Provider(provider_str.lower())
        account_id = discovery_record.get("account_id")
        region = discovery_record.get("region")
        service = discovery_record.get("service")
        resource_arn = discovery_record.get("resource_arn")
        resource_id = discovery_record.get("resource_id")
        discovery_id = discovery_record.get("discovery_id", "")

        # Use classification index to determine if this should be inventoried
        # (skip if caller already filtered — e.g. two-pass orchestrator)
        if not skip_classification:
            decision = self.classifier.classify_discovery_record(discovery_record)

            # Filter based on classification decision
            if decision == InventoryDecision.FILTER:
                return None  # Don't inventory ephemeral/config-only resources

            if decision == InventoryDecision.ENRICHMENT_ONLY:
                return None  # Use for enrichment only, don't create asset

        # Extract emitted fields (actual resource data)
        emitted_fields = discovery_record.get("emitted_fields", {})
        # Merge raw_response as fallback field source so relationship builder
        # can find AWS native fields (SecurityGroups, BlockDeviceMappings, etc.)
        # emitted_fields explicit extractions take priority over raw API response
        raw_response = discovery_record.get("raw_response")
        if isinstance(raw_response, dict) and isinstance(emitted_fields, dict):
            emitted_fields = {**raw_response, **emitted_fields}

        # Normalize based on provider
        if provider == Provider.AWS:
            return self._normalize_aws_discovery(
                discovery_record, emitted_fields, account_id, region, service, raw_ref
            )

        # Generic normalization for non-AWS providers (Azure, GCP, K8s, OCI, IBM, Alicloud)
        # Uses resource_uid from discovery_findings directly
        return self._normalize_generic_discovery(
            discovery_record, emitted_fields, provider, account_id, region, service, raw_ref
        )
    
    def _normalize_aws_discovery(
        self,
        discovery_record: Dict[str, Any],
        emitted_fields: Dict[str, Any],
        account_id: str,
        region: Optional[str],
        service: str,
        raw_ref: str
    ) -> Optional[Asset]:
        """
        Normalize AWS discovery record.

        emitted_fields from the discovery engine has three patterns:
          1. Flat:   {Name, Arn, RoleName, resource_arn, _dependent_data, _enriched_from}
          2. Nested: {get_role: {Role: {Arn, RoleName,...}}, resource_arn, _raw_response}
          3. Mixed:  {Name, BucketArn, _dependent_data: {get_bucket_versioning: {...}}}

        Root/independent operations (list_roles, list_buckets) carry the primary resource
        identity at top level. Dependent operations (get_role, get_bucket_acl) store
        enrichment data inside _dependent_data.
        """
        discovery_id = discovery_record.get("discovery_id", "")

        # Flatten nested operation keys to get a uniform dict
        flat = self._flatten_emitted_fields(emitted_fields, discovery_id)

        # --- Resource ARN / UID ---
        resource_arn = discovery_record.get("resource_arn") or discovery_record.get("resource_uid")
        if not resource_arn:
            resource_arn = (
                emitted_fields.get("resource_arn") or
                flat.get("Arn") or flat.get("ARN") or
                flat.get("BucketArn") or flat.get("FunctionArn") or
                flat.get("SecurityGroupRuleArn")
            )

        # --- Resource ID (human-friendly identifier) ---
        resource_id = discovery_record.get("resource_id")
        if not resource_id:
            resource_id = (
                flat.get("Name") or flat.get("BucketName") or
                flat.get("RoleName") or flat.get("UserName") or flat.get("GroupName") or
                flat.get("PolicyName") or flat.get("FunctionName") or
                flat.get("InstanceId") or flat.get("VolumeId") or
                flat.get("SecurityGroupId") or flat.get("VpcId") or flat.get("SubnetId") or
                flat.get("DBInstanceIdentifier") or flat.get("ClusterIdentifier") or
                flat.get("InstanceProfileName") or flat.get("InstanceProfileId") or
                flat.get("Id") or flat.get("ResourceId") or
                emitted_fields.get("resource_name") or
                emitted_fields.get("resource_id")
            )

        if not resource_arn and not resource_id:
            return None

        # --- Resource Type ---
        resource_type = self._extract_aws_resource_type_from_discovery(
            flat, service, resource_arn, discovery_id=discovery_id
        )
        # Use resource_uid for type correction (more reliable than resource_arn which may be wrong)
        resource_uid = discovery_record.get("resource_uid") or resource_arn or ""
        resource_type = self._correct_resource_type(resource_type, resource_uid)

        # --- Name (human-readable) ---
        name = (
            flat.get("Name") or flat.get("BucketName") or
            flat.get("RoleName") or flat.get("UserName") or flat.get("GroupName") or
            flat.get("PolicyName") or flat.get("FunctionName") or
            flat.get("DBInstanceIdentifier") or flat.get("ClusterIdentifier") or
            flat.get("InstanceProfileName") or
            flat.get("GroupId") or flat.get("SecurityGroupId") or
            emitted_fields.get("resource_name") or
            resource_id
        )

        # Fallback: extract name from ARN (e.g. arn:aws:iam::123:user/admin → admin)
        if not name and resource_arn and resource_arn.startswith("arn:"):
            arn_parts = resource_arn.split(":")
            if len(arn_parts) >= 6:
                resource_part = arn_parts[5]
                if "/" in resource_part:
                    name = resource_part.split("/")[-1]
                elif resource_part:
                    name = resource_part

        # --- Tags ---
        tags = self._extract_tags(emitted_fields)
        # Also try flat fields for tags that the flat extractor kept
        if not tags:
            tags = self._extract_tags(flat)

        # --- Scope ---
        if region in ["global", None]:
            scope = Scope.GLOBAL
        elif service in ["iam", "s3", "cloudfront", "route53", "organizations", "account"]:
            scope = Scope.GLOBAL
        else:
            scope = Scope.REGIONAL

        # --- Region ---
        if region in ["global", None, ""]:
            region = (
                flat.get("BucketRegion") or flat.get("Region") or
                emitted_fields.get("BucketRegion") or
                None
            )
            # Try extracting region from ARN (field 3)
            if not region and resource_arn and resource_arn.startswith("arn:"):
                arn_parts = resource_arn.split(":")
                if len(arn_parts) >= 4 and arn_parts[3]:
                    region = arn_parts[3]
            region = region or "global"

        # --- Configuration / Properties from dependent data ---
        configuration = {}
        dep_data = emitted_fields.get("_dependent_data", {})
        if isinstance(dep_data, dict):
            for dep_op, dep_result in dep_data.items():
                if isinstance(dep_result, dict):
                    configuration[dep_op] = dep_result

        # --- Map Specific FinOps Rule Fields ---
        mapped_fields = {}
        if resource_type == "ec2.instance":
            state = flat.get("State", {})
            if isinstance(state, dict):
                mapped_fields["state"] = state.get("Name")
            elif isinstance(state, str):
                mapped_fields["state"] = state.lower()
            
            mapped_fields["instance_type"] = flat.get("InstanceType")
            mapped_fields["launch_time"] = flat.get("LaunchTime")
            
            metrics = flat.get("metrics", {})
            if isinstance(metrics, dict) and "CPUUtilization" in metrics:
                mapped_fields["cpu_utilization"] = metrics.get("CPUUtilization")
            else:
                mapped_fields["cpu_utilization"] = None
                
            # Attempt to derive stopped_days if instance is stopped
            if mapped_fields.get("state") == "stopped" and "StateTransitionReason" in flat:
                import re
                from datetime import datetime, timezone
                match = re.search(r'\((\d{4}-\d{2}-\d{2})', str(flat.get("StateTransitionReason")))
                if match:
                    try:
                        stop_time = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        now = datetime.now(timezone.utc)
                        mapped_fields["stopped_days"] = (now - stop_time).days
                    except ValueError:
                        pass
        elif resource_type == "ec2.volume":
            mapped_fields["state"] = flat.get("State")
            attachments = flat.get("Attachments", [])
            mapped_fields["attached"] = len(attachments) > 0 if isinstance(attachments, list) else False
            mapped_fields["size_gb"] = flat.get("Size")
            mapped_fields["volume_type"] = flat.get("VolumeType")
        elif resource_type == "s3.bucket":
            mapped_fields["lifecycle_policy"] = "get_bucket_lifecycle_configuration" in configuration or bool(flat.get("Rules"))
            mapped_fields["intelligent_tiering_enabled"] = "get_bucket_intelligent_tiering_configuration" in configuration

        # --- Build metadata ---
        metadata = {
            "created_at": flat.get("CreationDate") or flat.get("CreateDate"),
            "labels": {},
            "raw_refs": [raw_ref],
            "discovery_id": discovery_id,
            "first_seen_at": discovery_record.get("first_seen_at"),
            "enriched_from": emitted_fields.get("_enriched_from", []),
            "configuration": configuration,
            "emitted_fields": emitted_fields,
            **mapped_fields
        }

        # --- Generate ARN if missing ---
        if not resource_arn:
            resource_arn = self._generate_arn_from_fields(flat, service, account_id, region)

        # --- Normalize resource_uid to canonical ARN ---
        # Always prefer full ARN format as the canonical identifier.
        # If resource_arn is already available, use it; otherwise attempt to
        # construct the ARN from short-form components via the normalizer.
        if resource_arn and is_arn(resource_arn):
            canonical_uid = resource_arn
        else:
            short_uid = resource_arn or f"{service}:{region}:{account_id}:{resource_id}"
            canonical_uid = normalize_resource_uid(
                resource_uid=short_uid,
                resource_type=resource_type,
                provider="aws",
                region=region or "global",
                account_id=account_id,
                resource_arn=resource_arn or "",
            )

        # --- Create asset ---
        asset = Asset(
            tenant_id=self.tenant_id,
            scan_run_id=self.scan_run_id,
            provider=Provider.AWS,
            account_id=account_id,
            region=region or "global",
            scope=scope,
            resource_type=resource_type,
            resource_id=resource_id or "",
            resource_uid=canonical_uid,
            name=name,
            tags=tags,
            metadata=metadata,
            hash_sha256="",
        )

        asset.hash_sha256 = compute_asset_hash(asset)
        return asset
    
    def _normalize_generic_discovery(
        self,
        discovery_record: Dict[str, Any],
        emitted_fields: Dict[str, Any],
        provider: 'Provider',
        account_id: str,
        region: Optional[str],
        service: str,
        raw_ref: str
    ) -> Optional[Asset]:
        """
        Generic normalizer for non-AWS providers (Azure, GCP, K8s, OCI, IBM, Alicloud).

        Uses resource_uid from the discovery record directly (no ARN construction needed).
        Resource type is derived from service + discovery_id or emitted_fields.
        """
        resource_uid = discovery_record.get("resource_uid", "")
        resource_arn = discovery_record.get("resource_arn", "")
        resource_id = discovery_record.get("resource_id", "")
        discovery_id = discovery_record.get("discovery_id", "")

        # Must have at least one identifier
        uid = resource_uid or resource_arn or resource_id
        if not uid:
            return None

        # Extract resource type — prefer the record's own resource_type if set
        # (e.g. Azure scanner sets ARM type directly on the discovery record)
        raw_type = discovery_record.get("resource_type", "")
        if raw_type:
            # Route through _extract_generic_resource_type with it as emitted field
            merged_fields = {"resource_type": raw_type, **emitted_fields}
        else:
            merged_fields = emitted_fields
        resource_type = self._extract_generic_resource_type(
            discovery_id, merged_fields, service, provider
        )

        # Extract name
        name = (
            emitted_fields.get("Name") or
            emitted_fields.get("name") or
            emitted_fields.get("display_name") or
            emitted_fields.get("displayName") or
            resource_id or
            uid
        )

        # Extract tags
        tags = self._extract_tags(emitted_fields)

        # Normalize region
        if region in ["global", None, ""]:
            region = emitted_fields.get("location") or emitted_fields.get("region") or "global"

        # Determine scope
        scope = Scope.GLOBAL if region == "global" else Scope.REGIONAL

        # --- Map Specific FinOps Rule Fields ---
        mapped_fields = {}
        
        # AZURE MAPPINGS
        if resource_type == "azure.virtual_machine":
            mapped_fields["instance_type"] = emitted_fields.get("hardwareProfile", {}).get("vmSize")
            state = "unknown"
            props = emitted_fields.get("properties", emitted_fields)
            iv = props.get("instanceView", {})
            statuses = iv.get("statuses", [])
            for s in statuses:
                code = s.get("code", "").lower()
                if code.startswith("powerstate/"):
                    state = code.replace("powerstate/", "")
            mapped_fields["state"] = "running" if state == "running" else ("stopped" if state in ("deallocated", "stopped") else state)
            
        elif resource_type == "azure.disk":
            mapped_fields["size_gb"] = emitted_fields.get("diskSizeGB") or emitted_fields.get("disk_size_gb")
            mapped_fields["attached"] = bool(emitted_fields.get("managedBy") or emitted_fields.get("managed_by"))
            state = emitted_fields.get("diskState") or emitted_fields.get("disk_state")
            mapped_fields["state"] = str(state).lower() if state else "unknown"
            
        # GCP MAPPINGS
        elif resource_type == "gcp.compute_instance":
            mt = emitted_fields.get("machineType", "")
            mapped_fields["instance_type"] = mt.split("/")[-1] if "/" in mt else mt
            mapped_fields["state"] = str(emitted_fields.get("status", "")).lower()
            
        elif resource_type == "gcp.compute_disk":
            mapped_fields["size_gb"] = emitted_fields.get("sizeGb")
            mapped_fields["attached"] = bool(emitted_fields.get("users", []))
            mapped_fields["state"] = str(emitted_fields.get("status", "")).lower()
            
        elif resource_type == "gcp.gcs_bucket":
            mapped_fields["lifecycle_policy"] = bool(emitted_fields.get("lifecycle", {}).get("rule", []))
            mapped_fields["storage_class"] = emitted_fields.get("storageClass")

        # Build metadata
        metadata = {
            "created_at": emitted_fields.get("creationTimestamp") or emitted_fields.get("timeCreated"),
            "labels": emitted_fields.get("labels", {}),
            "raw_refs": [raw_ref],
            "discovery_id": discovery_id,
            "first_seen_at": discovery_record.get("first_seen_at"),
            "emitted_fields": emitted_fields,
            **mapped_fields
        }

        # Create asset
        asset = Asset(
            tenant_id=self.tenant_id,
            scan_run_id=self.scan_run_id,
            provider=provider,
            account_id=account_id or "",
            region=region or "global",
            scope=scope,
            resource_type=resource_type,
            resource_id=resource_id or uid,
            resource_uid=uid,
            name=name,
            tags=tags,
            metadata=metadata,
            hash_sha256=""
        )

        asset.hash_sha256 = compute_asset_hash(asset)
        return asset

    # ── GCP API type → canonical type mapping ────────────────────────────────
    # Maps lowercase GCP API resource type → canonical "gcp.X" resource_type.
    # GCP API types follow "service.googleapis.com/ResourceKind" format.
    _GCP_API_TYPE_MAP: Dict[str, str] = {
        "iam.googleapis.com/serviceaccount": "gcp.iam_service_account",
        "iam.googleapis.com/role": "gcp.iam_role",
        "iam.googleapis.com/policy": "gcp.iam_policy",
        "compute.googleapis.com/instance": "gcp.compute_instance",
        "compute.googleapis.com/disk": "gcp.compute_disk",
        "compute.googleapis.com/firewall": "gcp.vpc_firewall_rule",
        "compute.googleapis.com/network": "gcp.vpc_network",
        "compute.googleapis.com/subnetwork": "gcp.vpc_subnetwork",
        "compute.googleapis.com/backendservice": "gcp.backend_service",
        "compute.googleapis.com/forwardingrule": "gcp.forwarding_rule",
        "compute.googleapis.com/sslcertificate": "gcp.ssl_certificate",
        "storage.googleapis.com/bucket": "gcp.gcs_bucket",
        "bigquery.googleapis.com/dataset": "gcp.bigquery_dataset",
        "bigquery.googleapis.com/table": "gcp.bigquery_table",
        "container.googleapis.com/cluster": "gcp.gke_cluster",
        "container.googleapis.com/nodepools": "gcp.gke_nodepool",
        "cloudfunctions.googleapis.com/function": "gcp.cloud_function",
        "run.googleapis.com/service": "gcp.cloud_run_service",
        "sqladmin.googleapis.com/instance": "gcp.cloud_sql_instance",
        "cloudkms.googleapis.com/keyring": "gcp.kms_key_ring",
        "cloudkms.googleapis.com/cryptokey": "gcp.kms_crypto_key",
        "pubsub.googleapis.com/topic": "gcp.pubsub_topic",
        "pubsub.googleapis.com/subscription": "gcp.pubsub_subscription",
        "dns.googleapis.com/managedzone": "gcp.dns_zone",
        "logging.googleapis.com/logsink": "gcp.log_sink",
        "monitoring.googleapis.com/alertpolicy": "gcp.alert_policy",
        "secretmanager.googleapis.com/secret": "gcp.secret",
        "redis.googleapis.com/instance": "gcp.redis_instance",
        "spanner.googleapis.com/instance": "gcp.spanner_instance",
        "bigtable.googleapis.com/instance": "gcp.bigtable_instance",
    }

    # ── Azure ARM type → canonical type mapping ─────────────────────────────
    # Maps lowercase ARM type → canonical "azure.X" resource_type stored in inventory_findings.
    # Add new mappings as Azure scanner expands to more services.
    _AZURE_ARM_TYPE_MAP: Dict[str, str] = {
        "microsoft.compute/virtualmachines": "azure.virtual_machine",
        "microsoft.compute/disks": "azure.disk",
        "microsoft.compute/snapshots": "azure.snapshot",
        "microsoft.compute/availabilitysets": "azure.availability_set",
        "microsoft.compute/virtualmachinescalesets": "azure.vmss",
        "microsoft.storage/storageaccounts": "azure.storage_account",
        "microsoft.storage/storageaccounts/blobservices/containers": "azure.blob_container",
        "microsoft.sql/servers": "azure.sql_server",
        "microsoft.sql/servers/databases": "azure.sql_database",
        "microsoft.sql/servers/firewallrules": "azure.sql_firewall_rule",
        "microsoft.network/networksecuritygroups": "azure.network_security_group",
        "microsoft.network/virtualnetworks": "azure.virtual_network",
        "microsoft.network/publicipaddresses": "azure.public_ip",
        "microsoft.network/networkinterfaces": "azure.network_interface",
        "microsoft.network/loadbalancers": "azure.load_balancer",
        "microsoft.network/applicationgateways": "azure.application_gateway",
        "microsoft.network/dnszones": "azure.dns_zone",
        "microsoft.keyvault/vaults": "azure.key_vault",
        "microsoft.web/sites": "azure.app_service",
        "microsoft.web/serverfarms": "azure.app_service_plan",
        "microsoft.containerservice/managedclusters": "azure.aks_cluster",
        "microsoft.containerregistry/registries": "azure.container_registry",
        "microsoft.msi/userassignedidentities": "azure.managed_identity",
        "microsoft.resources/resourcegroups": "azure.resource_group",
        "microsoft.resources/subscriptions": "azure.subscription",
        "microsoft.authorization/roleassignments": "azure.role_assignment",
        "microsoft.authorization/roledefinitions": "azure.role_definition",
        "microsoft.documentdb/databaseaccounts": "azure.cosmosdb",
        "microsoft.servicebus/namespaces": "azure.servicebus",
        "microsoft.eventhub/namespaces": "azure.eventhub",
        "microsoft.logic/workflows": "azure.logic_app",
        "microsoft.monitor/activitylogalerts": "azure.activity_log_alert",
        "microsoft.security/pricings": "azure.defender_pricing",
        "microsoft.security/securitycontacts": "azure.security_contact",
        "microsoft.insights/diagnosticsettings": "azure.diagnostic_setting",
    }

    def _extract_generic_resource_type(
        self,
        discovery_id: str,
        emitted_fields: Dict[str, Any],
        service: str,
        provider: 'Provider'
    ) -> str:
        """Extract resource type for non-AWS providers from discovery_id or emitted fields."""
        import re
        provider_str = str(provider).lower().replace("provider.", "")

        # Try emitted fields first
        for field in ["resourceType", "resource_type", "type", "Type", "kind"]:
            if field in emitted_fields and emitted_fields[field]:
                val = str(emitted_fields[field])

                # Azure ARM type: "Microsoft.Compute/virtualMachines" → "azure.virtual_machine"
                # ARM types start with "Microsoft." (canonical) or match pattern "Namespace/ResourceKind"
                # where namespace doesn't start with "http" (to exclude GCP selfLink URLs)
                is_arm_type = (
                    val.startswith("Microsoft.") or
                    (provider_str == "azure" and "/" in val and not val.startswith("http"))
                )
                if is_arm_type:
                    canonical = self._AZURE_ARM_TYPE_MAP.get(val.lower())
                    if canonical:
                        return canonical
                    # Fallback: derive from ARM kind (last path segment), snake_case
                    kind = val.split("/")[-1] if "/" in val else val.split(".")[-1]
                    kind = re.sub(r'(?<!^)(?=[A-Z])', '_', kind).lower().rstrip("s")
                    return f"azure.{kind}"

                # K8s: "kind" field → "k8s.pod", "k8s.deployment", etc.
                if field == "kind" and provider_str == "k8s":
                    return f"k8s.{val.lower()}"

                # GCP API type: "compute.googleapis.com/Instance" → "gcp.compute_instance"
                if provider_str == "gcp" and not val.startswith("gcp."):
                    canonical = self._GCP_API_TYPE_MAP.get(val.lower())
                    if canonical:
                        return canonical
                    if ".googleapis.com/" in val:
                        # "service.googleapis.com/ResourceKind" → "gcp.service_resource_kind"
                        svc = val.split(".googleapis.com/")[0]
                        kind = val.split("/")[-1]
                        kind_snake = re.sub(r'(?<!^)(?=[A-Z])', '_', kind).lower()
                        return f"gcp.{svc}_{kind_snake}"
                    kind = re.sub(r'(?<!^)(?=[A-Z])', '_', val).lower()
                    return f"gcp.{kind}"

                return f"{service}.{val}" if not val.startswith(service) else val

        # Extract from discovery_id: e.g., azure.compute.list_virtual_machines → compute.virtual_machines
        if discovery_id:
            parts = discovery_id.split(".")
            # Remove CSP prefix and operation prefix (list_, describe_, get_)
            if len(parts) >= 3:
                svc = parts[-2] if len(parts) > 2 else service
                op_name = parts[-1]
                # Strip common operation prefixes to get resource type
                for prefix in ["list_", "describe_", "get_", "list", "describe", "get"]:
                    if op_name.lower().startswith(prefix):
                        resource = op_name[len(prefix):]
                        if resource:
                            return f"{provider_str}.{svc}_{resource}" if provider_str not in ("aws",) else f"{service}.{resource}"
                return f"{provider_str}.{svc}_{op_name}" if provider_str not in ("aws",) else f"{service}.{op_name}"

        return f"{service}.resource"

    # ── Post-normalization type corrections ──────────────────────────────
    # Maps known misclassified types to their correct values.
    # None = junk resource that should be filtered / deprioritized.
    _TYPE_CORRECTIONS: Dict[str, Optional[str]] = {
        # VPC resources discovered via local gateway / block-access operations
        # whose ARN contains vpc/ but extraction yields the wrong sub-resource
        "ec2.local_gateway_route_table_vpc_association": "ec2.vpc",
        "ec2.local_gateway_route_table_vpc_association_local_gateway_route_table": "ec2.vpc",
        # Junk sub-resources that pollute the asset set
        "ec2.vpc_block_public_access_exclusion_resource": None,
        "ec2.vpc_block_public_access_exclusion": None,
    }

    def _correct_resource_type(self, resource_type: str, resource_arn: str) -> str:
        """Post-normalization correction for known misclassified resource types.

        Args:
            resource_type: The type string produced by _extract_aws_resource_type_*
            resource_arn:  Original ARN of the resource

        Returns:
            Corrected resource type, or original if no correction needed.
            For junk types (mapped to None), returns original so the caller
            can still create the asset — the UI/graph query will deprioritise it.
        """
        if resource_type in self._TYPE_CORRECTIONS:
            corrected = self._TYPE_CORRECTIONS[resource_type]
            if corrected:
                logger.debug(
                    "Type correction: %s → %s (arn=%s)",
                    resource_type, corrected, resource_arn[:80] if resource_arn else ""
                )
                return corrected
            # None → junk; return original (let graph query deprioritise)
            return resource_type

        # ARN-based correction: extract real type from resource_uid/resource_arn pattern
        # arn:aws:ec2:region:account:RESOURCE_TYPE/id → use RESOURCE_TYPE
        if resource_arn and resource_arn.startswith("arn:aws:"):
            parts = resource_arn.split(":")
            if len(parts) >= 6:
                resource_part = parts[5]
                if "/" in resource_part:
                    arn_type = resource_part.split("/")[0]
                    service = parts[2]  # e.g. "ec2", "iam", "s3"
                    expected = f"{service}.{arn_type}"
                    if expected != resource_type and arn_type:
                        logger.debug(
                            "ARN-based type correction: %s → %s (arn=%s)",
                            resource_type, expected, resource_arn[:80]
                        )
                        return expected

        return resource_type

    def _extract_aws_resource_type_from_discovery(
        self,
        fields: Dict[str, Any],
        service: str,
        resource_arn: Optional[str] = None,
        discovery_id: str = "",
    ) -> str:
        """
        Extract resource type from flat emitted fields or ARN.

        Uses multiple strategies:
          0. Discovery_id → type mapping (most reliable)
          1. ARN resource-type segment (e.g. arn:aws:iam::123:role/name → iam.role)
          2. Primary ID field signatures (specific fields like NetworkAclId before generic VpcId)
          3. Fallback to service.resource
        """
        # --- Strategy 0: Discovery_id → type (most reliable) ---
        if discovery_id:
            # aws.ec2.describe_network_acls → network-acl
            action = discovery_id.split(".")[-1] if "." in discovery_id else ""
            _DID_TO_TYPE = {
                "describe_network_acls": "network-acl",
                "describe_route_tables": "route-table",
                "describe_network_interfaces": "network-interface",
                "describe_instances": "instance",
                "describe_vpcs": "vpc",
                "describe_subnets": "subnet",
                "describe_security_groups": "security-group",
                "describe_security_group_rules": "security-group-rule",
                "describe_volumes": "volume",
                "describe_internet_gateways": "internet-gateway",
                "describe_nat_gateways": "nat-gateway",
                "describe_transit_gateways": "transit-gateway",
                "describe_vpc_endpoints": "vpc-endpoint",
                "describe_addresses": "elastic-ip",
                "describe_key_pairs": "key-pair",
                "describe_launch_templates": "launch-template",
                "describe_images": "image",
                "describe_snapshots": "snapshot",
                "describe_dhcp_options": "dhcp-options",
                "describe_flow_logs": "flow-log",
                "list_roles": "role",
                "list_users": "user",
                "list_policies": "policy",
                "list_groups": "group",
                "list_instance_profiles": "instance-profile",
                "list_functions": "function",
                "list_buckets": "bucket",
                "list_tables": "table",
                "list_queues": "queue",
                "list_topics": "topic",
                "list_keys": "key",
                "describe_db_instances": "db-instance",
                "describe_clusters": "cluster",
                "list_clusters": "cluster",
                "describe_repositories": "repository",
                "describe_log_groups": "log-group",
                "describe_alarms": "alarm",
                "describe_trails": "trail",
            }
            if action in _DID_TO_TYPE:
                return f"{service}.{_DID_TO_TYPE[action]}"

        # --- Strategy 1: ARN-based type extraction ---
        if resource_arn and resource_arn.startswith("arn:"):
            arn_parts = resource_arn.split(":")
            if len(arn_parts) >= 6:
                resource_part = arn_parts[5]
                if "/" in resource_part:
                    arn_type = resource_part.split("/")[0]
                    if arn_type:
                        return f"{service}.{arn_type}"
                elif resource_part and ":::" in resource_arn:
                    return f"{service}.bucket"

        # --- Strategy 2: Primary ID field signatures ---
        # Order matters: specific IDs before generic ones (NetworkAclId before VpcId)
        _FIELD_TO_TYPE = {
            # Specific IDs first
            "NetworkAclId": "network-acl",
            "RouteTableId": "route-table",
            "NetworkInterfaceId": "network-interface",
            "SecurityGroupRuleId": "security-group-rule",
            "SecurityGroupId": "security-group", "GroupId": "security-group",
            "NatGatewayId": "nat-gateway",
            "InternetGatewayId": "internet-gateway",
            "TransitGatewayId": "transit-gateway",
            "FlowLogId": "flow-log",
            "InstanceId": "instance",
            "VolumeId": "volume",
            # Generic IDs last
            "SubnetId": "subnet",
            "VpcId": "vpc",
            # Service-specific
            "BucketName": "bucket", "BucketArn": "bucket",
            "UserName": "user",
            "RoleName": "role", "RoleId": "role",
            "GroupName": "group",
            "PolicyName": "policy", "PolicyId": "policy",
            "InstanceProfileName": "instance-profile", "InstanceProfileId": "instance-profile",
            "FunctionName": "function", "FunctionArn": "function",
            "DBInstanceIdentifier": "db-instance",
            "ClusterIdentifier": "cluster",
            "DistributionId": "distribution",
            "HostedZoneId": "hosted-zone",
            "CertificateArn": "certificate",
            "TopicArn": "topic",
            "QueueUrl": "queue",
            "TableName": "table",
            "StreamName": "stream",
        }

        for field_name, rtype in _FIELD_TO_TYPE.items():
            if field_name in fields and fields[field_name]:
                return f"{service}.{rtype}"

        # --- S3 service default ---
        if service == "s3" and ("Name" in fields or "BucketRegion" in fields):
            return "s3.bucket"

        # --- DB-based index resolution ---
        if self.classifier:
            resolved = self.classifier.resolve_resource_type(service, fields, resource_arn or "")
            if resolved:
                return f"{service}.{resolved}"

        return f"{service}.resource"
    
    def enrich_asset(self, asset: Asset, discovery_record: Dict[str, Any]) -> Asset:
        """
        Enrich an existing asset with data from a dependent/enrichment discovery record.

        Dependent discovery records (get_bucket_versioning, get_role, etc.) carry
        operation-specific configuration data that should be merged into the asset's
        metadata.configuration dict.

        The root discovery's _dependent_data may already contain this data, but separate
        dependent discovery records can have additional/different data.

        Args:
            asset: Existing asset to enrich
            discovery_record: Dependent discovery record

        Returns:
            Enriched asset (same object, mutated)
        """
        discovery_id = discovery_record.get("discovery_id", "")
        emitted_fields = discovery_record.get("emitted_fields", {})

        if not isinstance(emitted_fields, dict):
            return asset

        # Extract the operation suffix (e.g. "get_bucket_versioning" from "aws.s3.get_bucket_versioning")
        op_suffix = discovery_id.split(".")[-1] if discovery_id else ""

        # Ensure metadata.configuration exists
        if not asset.metadata:
            asset.metadata = {}
        if "configuration" not in asset.metadata:
            asset.metadata["configuration"] = {}
        configuration = asset.metadata["configuration"]

        # --- Extract operation-specific data ---
        # Pattern 1: Data is directly in emitted_fields under op_suffix key
        #   e.g. get_bucket_versioning: {get_bucket_versioning: {Status: "Enabled", ...}}
        if op_suffix and op_suffix in emitted_fields:
            op_data = emitted_fields[op_suffix]
            if isinstance(op_data, dict) and op_suffix not in configuration:
                configuration[op_suffix] = op_data

        # Pattern 2: Data is in _raw_response
        raw_resp = emitted_fields.get("_raw_response", {})
        if isinstance(raw_resp, dict) and raw_resp and op_suffix not in configuration:
            configuration[op_suffix] = raw_resp

        # Pattern 3: Also check for nested operation keys (get_, describe_)
        for key, val in emitted_fields.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            if key.startswith("get_") or key.startswith("describe_") or key.startswith("list_"):
                if key not in configuration:
                    configuration[key] = val

        # --- Extract tags from enrichment record ---
        enrichment_tags = self._extract_tags(emitted_fields)
        if enrichment_tags:
            if not asset.tags:
                asset.tags = {}
            asset.tags.update(enrichment_tags)

        # --- Merge emitted_fields into asset.metadata["emitted_fields"] ---
        # Critical for relationship builder: it reads fields like IamInstanceProfile,
        # SecurityGroups, SubnetId from emitted_fields — not from configuration.
        # Without this merge, enrichment discoveries (describe_instances) have their
        # fields stored in configuration but invisible to the relationship builder.
        if "emitted_fields" not in asset.metadata:
            asset.metadata["emitted_fields"] = {}
        existing_ef = asset.metadata["emitted_fields"]
        if isinstance(existing_ef, dict) and isinstance(emitted_fields, dict):
            for key, val in emitted_fields.items():
                if key.startswith("_"):
                    continue  # skip internal fields
                # Overwrite if key missing OR existing value is None/empty
                # This ensures describe_instances' IamInstanceProfile overwrites
                # the None from describe_instance_image_metadata
                existing_val = existing_ef.get(key)
                if existing_val is None or existing_val == "" or existing_val == {} or existing_val == []:
                    if val is not None:
                        existing_ef[key] = val
                elif key not in existing_ef:
                    existing_ef[key] = val
            asset.metadata["emitted_fields"] = existing_ef

        # --- Track enrichment source ---
        if "enriched_from" not in asset.metadata:
            asset.metadata["enriched_from"] = []
        if discovery_id not in asset.metadata["enriched_from"]:
            asset.metadata["enriched_from"].append(discovery_id)

        return asset

    def extract_enrichment_uid(self, discovery_record: Dict[str, Any]) -> Optional[str]:
        """
        Extract the canonical resource UID that an enrichment record refers to,
        normalised to ARN format so it matches assets_by_uid built from Pass 1.

        Discovery enrichment records often carry a short-form resource_uid
        (e.g. "ec2:ap-south-1:123456:i-0abc123") while the root asset was stored
        with a full ARN ("arn:aws:ec2:ap-south-1:123456:instance/i-0abc123").
        We normalise here so the lookup in the orchestrator succeeds.

        Returns:
            Canonical ARN/UID string, or None
        """
        resource_arn = discovery_record.get("resource_arn")
        resource_uid = discovery_record.get("resource_uid")

        # Prefer explicit ARN if already in ARN format
        if resource_arn and is_arn(resource_arn):
            return resource_arn

        # Try to normalise short-form UID to canonical ARN
        uid = resource_arn or resource_uid
        if uid:
            if is_arn(uid):
                return uid
            # Use the normalizer to convert short-form to ARN
            try:
                service = discovery_record.get("service", "")
                region = discovery_record.get("region", "")
                account_id = discovery_record.get("account_id", "")
                resource_type = discovery_record.get("resource_type", "")
                normalised = normalize_resource_uid(
                    resource_uid=uid,
                    resource_type=resource_type,
                    provider="aws",
                    region=region or "global",
                    account_id=account_id,
                    resource_arn=resource_arn or "",
                )
                if normalised and is_arn(normalised):
                    return normalised
            except Exception:
                pass
            return uid  # fallback: return as-is, orchestrator will also try param_sources
        return None

    def _generate_arn_from_fields(self, fields: Dict[str, Any], service: str, account_id: str, region: str) -> Optional[str]:
        """Generate ARN from flat fields if possible."""
        # Try existing ARN fields first
        arn = (
            fields.get("Arn") or fields.get("ARN") or
            fields.get("BucketArn") or fields.get("FunctionArn") or
            fields.get("SecurityGroupRuleArn") or fields.get("TopicArn") or
            fields.get("CertificateArn") or fields.get("PolicyArn")
        )
        if arn:
            return arn

        # Service-specific ARN generation
        region = region or "global"
        if service == "s3":
            name = fields.get("Name") or fields.get("BucketName")
            if name:
                return f"arn:aws:s3:::{name}"
        elif service == "ec2":
            iid = fields.get("InstanceId")
            if iid:
                return f"arn:aws:ec2:{region}:{account_id}:instance/{iid}"
            vid = fields.get("VolumeId")
            if vid:
                return f"arn:aws:ec2:{region}:{account_id}:volume/{vid}"
            sgid = fields.get("SecurityGroupId") or fields.get("GroupId")
            if sgid:
                return f"arn:aws:ec2:{region}:{account_id}:security-group/{sgid}"
            vpcid = fields.get("VpcId")
            if vpcid:
                return f"arn:aws:ec2:{region}:{account_id}:vpc/{vpcid}"
            subid = fields.get("SubnetId")
            if subid:
                return f"arn:aws:ec2:{region}:{account_id}:subnet/{subid}"
        elif service == "iam":
            user = fields.get("UserName")
            if user:
                return f"arn:aws:iam::{account_id}:user/{user}"
            role = fields.get("RoleName")
            if role:
                path = fields.get("Path", "/")
                return f"arn:aws:iam::{account_id}:role{path}{role}" if path != "/" else f"arn:aws:iam::{account_id}:role/{role}"
            group = fields.get("GroupName")
            if group:
                return f"arn:aws:iam::{account_id}:group/{group}"
            policy = fields.get("PolicyName")
            if policy and fields.get("PolicyId"):
                return f"arn:aws:iam::{account_id}:policy/{policy}"
            ip_name = fields.get("InstanceProfileName")
            if ip_name:
                return f"arn:aws:iam::{account_id}:instance-profile/{ip_name}"
        elif service == "lambda":
            fn_name = fields.get("FunctionName")
            if fn_name:
                return f"arn:aws:lambda:{region}:{account_id}:function:{fn_name}"
        elif service == "rds":
            db_id = fields.get("DBInstanceIdentifier")
            if db_id:
                return f"arn:aws:rds:{region}:{account_id}:db:{db_id}"

        return None

