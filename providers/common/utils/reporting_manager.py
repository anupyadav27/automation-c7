import os
import json
import fnmatch
import logging
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Tuple
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# Import exception reading from exception_manager to avoid duplication
from .exception_manager import (
    list_service_exceptions,
    list_check_exceptions
)


def _config_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config"))


def _project_root() -> Path:
    """Repo root (relative to this file)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _output_dir() -> str:
    """Get output base directory"""
    # Prefer env var so Kubernetes can mount /output and sidecar can sync to S3.
    # Fallback to repo-local output folder for local/dev runs.
    output_dir = os.getenv("OUTPUT_DIR")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    # Default to the designed output path: engine_output/engine_configscan_aws/output/configscan/discoveries
    project_root = _project_root()
    output_dir = project_root / "engine_output" / "engine_configscan_aws" / "output" / "configscan" / "discoveries"
    os.makedirs(output_dir, exist_ok=True)
    return str(output_dir)


def _get_tenant_id() -> str:
    """Get tenant ID from environment or config, default to 'default-tenant'"""
    tenant_id = os.getenv("TENANT_ID") or os.getenv("tenant_id")
    if tenant_id:
        return tenant_id
    # Fallback to default for local/dev
    return "default-tenant"


def is_cspm_inventory_resource(discovery_id: str, discovery_config: Dict[str, Any] = None) -> bool:
    """
    Universal heuristic to determine if a discovery operation should produce discovered resources.
    Works across ALL AWS services automatically using structural patterns.
    
    Primary rule: If discovery has `for_each`, it's a detail view, NOT inventory.
    
    Args:
        discovery_id: Discovery operation ID (e.g., "aws.ec2.describe_instances")
        discovery_config: Optional discovery YAML config dict (if available)
    
    Returns:
        True if should produce discovered resources
    """
    import re
    
    # Extract operation name
    parts = discovery_id.split('.')
    if len(parts) < 3:
        return False
    operation = parts[2].lower()
    
    # ========================================================================
    # UNIVERSAL RULE #1: If has `for_each`, it's a detail view (NOT inventory)
    # ========================================================================
    # This is the MOST RELIABLE indicator - works across ALL services!
    if discovery_config and discovery_config.get('for_each'):
        return False
    
    # ========================================================================
    # UNIVERSAL RULE #2: Universal non-resource patterns (apply to ALL services)
    # ========================================================================
    UNIVERSAL_NON_RESOURCE_PATTERNS = [
        # Tasks and operations (not resources)
        r'.*_tasks?$',                    # import_tasks, copy_jobs
        r'.*_jobs?$',                     # backup_jobs, restore_jobs
        
        # Transfers and moves (not resources)
        r'.*_transfer.*',                 # address_transfers, responsibility_transfers
        
        # Deleted/temporary items
        r'.*_in_recycle_bin',             # list_images_in_recycle_bin
        r'.*_deleted',                    # deleted resources
        
        # Attributes (properties of resources, not resources themselves)
        r'.*_attribute$',                 # describe_load_balancer_attributes
        r'.*_attributes$',                # plural version
        
        # Status checks (not resources)
        r'.*get_.*_status$',              # get_serial_console_access_status
        r'.*_status$',                    # policy_status (when singular)
        
        # Configuration defaults (not resources)
        r'.*get_.*_defaults?$',           # get_ebs_encryption_by_default
        r'.*_defaults?$',                 # defaults
        
        # Data retrieval (not resources)
        r'.*get_.*_data$',                # get_launch_template_data
        r'.*get_.*_config$',              # get_distribution_config (config, not resource)
        
        # Account/service-level settings (not resources)
        r'.*account_settings',            # list_account_settings
        r'.*account_.*',                  # get_account_summary, get_contact_information
        r'.*get_alternate_contact',       # Account service
        
        # Options (configuration, not resources)
        r'.*_options$',                   # describe_option_group_options
        r'.*block_public_access.*options', # VPC block public access options
        
        # Policies/config retrieval (detail views, not resources)
        r'.*get_.*_policy$',              # get_backup_vault_access_policy
        r'.*get_.*_notification',         # get_backup_vault_notifications
        
        # Previews and findings (not resources themselves)
        r'.*_preview',                    # get_access_preview
        r'.*_findings?',                  # list_findings (findings, not resources)
        
        # Events (not resources)
        r'.*_events?$',                   # describe_stack_events (events, not stacks)
        
        # Parameters (detail views, not resources)
        r'.*_parameters?$',               # describe_db_cluster_parameters (params, not clusters)
        
        # Supported types/capabilities (not actual resources)
        r'.*_types?$',                    # describe_endpoint_types (supported types, not resources)
        r'.*_capabilities?$',              # describe_capabilities (supported features, not resources)
        r'.*_options?$',                   # describe_option_group_options (options, not resources)
    ]
    
    for pattern in UNIVERSAL_NON_RESOURCE_PATTERNS:
        if re.match(pattern, operation, re.IGNORECASE):
            return False
    
    # ========================================================================
    # UNIVERSAL RULE #3: Operation type patterns (work across ALL services)
    # ========================================================================
    
    # list_* operations → ALWAYS inventory
    if operation.startswith('list_'):
        return True
    
    # describe_* operations → Usually inventory if plural noun (list all pattern)
    if operation.startswith('describe_'):
        # Plural patterns (describe_instances, describe_load_balancers)
        if re.match(r'describe_.*s$', operation):  # Ends with 's' (plural)
            return True
        if 'groups' in operation or 'lists' in operation:  # Plural words
            return True
        # But exclude if it's a task/option/parameter (already in denylist)
        return False
    
    # get_* operations → Usually NOT inventory (config/details)
    if operation.startswith('get_'):
        return False
    
    # ========================================================================
    # Default: Conservative - only explicit inventory operations pass
    # ========================================================================
    return False


def compute_asset_hash(asset: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash for drift detection.
    Uses key fields that determine asset identity.
    
    Args:
        asset: Asset dictionary with canonical schema fields
    
    Returns:
        SHA256 hex digest
    """
    key_fields = {
        "provider": asset.get("provider", ""),
        "account_id": asset.get("account_id", ""),
        "region": asset.get("region", ""),
        "resource_type": asset.get("resource_type", ""),
        "resource_id": asset.get("resource_id", ""),
        "resource_uid": asset.get("resource_uid", ""),
        "name": asset.get("name", ""),
        "tags": json.dumps(asset.get("tags", {}), sort_keys=True)
    }
    
    key_string = json.dumps(key_fields, sort_keys=True)
    return hashlib.sha256(key_string.encode()).hexdigest()


def generate_arn(service: str, region: str, account_id: str, resource_id: str, resource_type: str = None) -> str:
    """
    Generate ARN for any AWS resource based on service configuration.
    Generic implementation - automatically detects required parameters from ARN pattern.
    """
    import re
    
    config_path = os.path.join(_config_dir(), "service_list.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Find service configuration
    service_config = None
    for svc in config.get("services", []):
        if svc["name"] == service:
            service_config = svc
            break
    
    if not service_config:
        raise ValueError(f"Service '{service}' not found in configuration")
    
    # Get ARN pattern
    arn_pattern = service_config.get("arn_pattern")
    if not arn_pattern:
        raise ValueError(f"ARN pattern not defined for service '{service}'")
    
    # Determine scope
    scope = service_config.get("scope", "regional")
    
    # Extract required parameters from ARN pattern using regex
    # Find all {placeholder} patterns in the ARN pattern
    required_params = set(re.findall(r'\{(\w+)\}', arn_pattern))
    
    # Build format parameters dict - only include what's needed
    format_params = {}
    
    if 'resource_id' in required_params:
        if not resource_id:
            raise ValueError(f"resource_id is required for service '{service}' ARN")
        format_params['resource_id'] = resource_id
    
    if 'region' in required_params:
        if not region and scope == "regional":
            raise ValueError(f"Region is required for regional service '{service}'")
        format_params['region'] = region or ""
    
    if 'account_id' in required_params:
        if not account_id:
            raise ValueError(f"account_id is required for service '{service}' ARN")
        format_params['account_id'] = account_id
    
    if 'resource_type' in required_params:
        format_params['resource_type'] = resource_type or "resource"
    
    # Format ARN pattern with only the required parameters
    try:
        return arn_pattern.format(**format_params)
    except KeyError as e:
        raise ValueError(f"Missing required parameter for ARN generation: {e}. Pattern: {arn_pattern}, Required: {required_params}")


def parse_arn(arn: str) -> Dict[str, Any]:
    """Parse ARN to extract components"""
    parts = arn.split(":")
    
    if len(parts) < 6:
        return {
            "arn": arn,
            "service": "unknown",
            "region": None,
            "account_id": None,
            "resource_id": None,
            "resource_type": None,
            "scope": "unknown"
        }
    
    # Extract basic components
    service = parts[2]
    region = parts[3] if parts[3] != "" else None
    account_id = parts[4] if parts[4] != "" else None
    
    # Parse resource part (format: resource_type/resource_id or just resource_id)
    resource_part = parts[5]
    if "/" in resource_part:
        resource_type, resource_id = resource_part.split("/", 1)
    else:
        resource_type = None
        resource_id = resource_part
    
    # Determine scope
    config_path = os.path.join(_config_dir(), "service_list.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    scope = "unknown"
    for svc in config.get("services", []):
        if svc["name"] == service:
            scope = svc.get("scope", "unknown")
            break
    
    return {
        "arn": arn,
        "service": service,
        "region": region,
        "account_id": account_id,
        "resource_id": resource_id,
        "resource_type": resource_type,
        "scope": scope
    }


def is_global_service(service: str) -> bool:
    """Check if a service is global (no region required)"""
    config_path = os.path.join(_config_dir(), "service_list.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    for svc in config.get("services", []):
        if svc["name"] == service:
            return svc.get("scope") == "global"
    return False


def _timestamp() -> str:
    """Generate timestamp for scan ID"""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def create_scan_folder(scan_id: str = None) -> tuple:
    """
    Create timestamped scan folder with logs subdirectory
    
    Returns:
        (scan_folder_path, scan_id)
    """
    if scan_id is None:
        scan_id = f"scan_{_timestamp()}"
    
    output_base = _output_dir()
    scan_folder = os.path.join(output_base, scan_id)
    os.makedirs(scan_folder, exist_ok=True)
    
    # Create logs subdirectory inside scan folder
    logs_dir = os.path.join(scan_folder, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create latest symlink
    latest_link = os.path.join(output_base, "latest")
    if os.path.islink(latest_link) or os.path.exists(latest_link):
        os.remove(latest_link)
    os.symlink(scan_id, latest_link)
    
    return scan_folder, scan_id


def create_report_folder() -> str:
    """Legacy compatibility - calls create_scan_folder"""
    scan_folder, _ = create_scan_folder()
    return scan_folder


def get_scan_log_file(scan_folder: str, log_type: str = "scan") -> str:
    """
    Get log file path inside scan folder
    
    Args:
        scan_folder: Path to scan folder
        log_type: 'scan', 'errors', or account_id
    
    Returns:
        Path to log file
    """
    logs_dir = os.path.join(scan_folder, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    if log_type == "scan":
        return os.path.join(logs_dir, "scan.log")
    elif log_type == "errors":
        return os.path.join(logs_dir, "errors.log")
    else:
        # Account-specific log
        return os.path.join(logs_dir, f"account_{log_type}.log")


def setup_scan_logging(scan_folder: str, scan_id: str):
    """
    Setup logging for a scan
    
    Args:
        scan_folder: Path to scan folder
        scan_id: Scan identifier
    
    Returns:
        Logger instance
    """
    import logging
    
    log_file = get_scan_log_file(scan_folder, "scan")
    error_log_file = get_scan_log_file(scan_folder, "errors")
    
    # Ensure log files exist
    Path(log_file).touch(exist_ok=True)
    Path(error_log_file).touch(exist_ok=True)
    
    # Create main scan logger
    logger = logging.getLogger(f'compliance_scan_{scan_id}')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # Remove any existing handlers
    
    # File handler - all logs
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(fh)
    
    # Error file handler - errors only
    eh = logging.FileHandler(error_log_file)
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(eh)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(ch)
    
    # ALSO configure the service scanner logger (compliance-boto3)
    # This ensures service-level logs also go to the scan folder
    service_logger = logging.getLogger('compliance-boto3')
    service_logger.setLevel(logging.INFO)
    service_logger.handlers.clear()
    
    # Add same handlers to service logger
    service_logger.addHandler(fh)
    service_logger.addHandler(eh)
    service_logger.addHandler(ch)
    
    # Configure root logger for botocore and other libs
    root_logger = logging.getLogger()
    root_logger.addHandler(fh)
    root_logger.addHandler(eh)
    
    logger.info(f"[SCAN-START] {scan_id}")
    logger.info(f"Scan folder: {scan_folder}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Error log: {error_log_file}")
    
    return logger


def _meta(account_id: str | None, folder: str) -> Dict[str, Any]:
    return {"account_id": account_id, "generated_at": datetime.utcnow().isoformat() + "Z", "report_folder": os.path.abspath(folder)}


# NOTE: Exception reading functions removed - now using exception_manager.py
# This eliminates code duplication and provides single source of truth
# Use list_service_exceptions() and list_check_exceptions() imported above


def _load_actions_config() -> Dict[str, Any]:
    path = os.path.join(_config_dir(), "actions.yaml")
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def _load_actions_selection() -> Dict[str, List[str]]:
    path = os.path.join(_config_dir(), "actions_selection.yaml")
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    profiles = data.get("profiles") or {}
    active = data.get("active_profile") or "default"
    profile = profiles.get(active) or {}
    return (profile.get("selected_actions_by_check") or {})


def _iso_not_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return True
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.utcnow() <= dt
    except Exception:
        return True


def _match_scope(val: str | None, pattern: str | None) -> bool:
    if pattern is None:
        return True
    if val is None:
        return False
    return fnmatch.fnmatch(val, pattern)


def save_metadata(scan_folder: str, metadata: dict) -> None:
    """Save scan metadata to metadata.json"""
    metadata_path = os.path.join(scan_folder, "metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)


def save_summary(scan_folder: str, summary: dict) -> None:
    """Save scan summary to summary.json"""
    summary_path = os.path.join(scan_folder, "summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)


def save_account_summary(scan_folder: str, account_id: str, summary: dict) -> None:
    """Save account-level summary"""
    account_dir = os.path.join(scan_folder, f"account_{account_id}")
    os.makedirs(account_dir, exist_ok=True)
    
    summary_path = os.path.join(account_dir, "account_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)


def save_region_summary(scan_folder: str, account_id: str, region: str, summary: dict) -> None:
    """Save region-level summary"""
    region_dir = os.path.join(scan_folder, f"account_{account_id}", region)
    os.makedirs(region_dir, exist_ok=True)
    
    summary_path = os.path.join(region_dir, "region_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)


def save_chunked_resources(scan_folder: str, account_id: str, region: str, 
                           service: str, resources: list, chunk_size: int = 100) -> str:
    """
    Save resources in chunked, compressed format
    
    Args:
        scan_folder: Base scan folder path
        account_id: AWS account ID
        region: AWS region (or 'global')
        service: Service name (e.g., 'ec2', 's3')
        resources: List of resource dictionaries with inventory + compliance
        chunk_size: Number of resources per chunk file
    
    Returns:
        Path to service directory
    """
    import gzip
    
    # Create directory structure
    service_dir = os.path.join(
        scan_folder,
        f"account_{account_id}",
        region,
        service
    )
    os.makedirs(service_dir, exist_ok=True)
    
    # Split into chunks and save
    chunks_metadata = []
    total_resources = len(resources)
    
    for i in range(0, total_resources, chunk_size):
        chunk = resources[i:i + chunk_size]
        chunk_id = i // chunk_size
        
        chunk_data = {
            "chunk_id": chunk_id,
            "account_id": account_id,
            "region": region,
            "service": service,
            "scan_id": os.path.basename(scan_folder),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "resource_count": len(chunk),
            "resources": chunk
        }
        
        # Write compressed chunk
        chunk_file = f"chunk_{chunk_id:03d}.json.gz"
        chunk_path = os.path.join(service_dir, chunk_file)
        
        with gzip.open(chunk_path, 'wt', encoding='utf-8') as f:
            json.dump(chunk_data, f, indent=2)
        
        # Get file sizes
        compressed_size = os.path.getsize(chunk_path)
        
        # Calculate stats
        failed_count = sum(1 for r in chunk 
                          if r.get("compliance", {}).get("failed", 0) > 0)
        total_checks = sum(r.get("compliance", {}).get("total_checks", 0) 
                          for r in chunk)
        passed_checks = sum(r.get("compliance", {}).get("passed", 0) 
                           for r in chunk)
        failed_checks = sum(r.get("compliance", {}).get("failed", 0) 
                           for r in chunk)
        
        chunks_metadata.append({
            "chunk_id": chunk_id,
            "file": chunk_file,
            "resource_count": len(chunk),
            "size_compressed": compressed_size,
            "resource_ids": [r["resource_id"] for r in chunk],
            "stats": {
                "resources_with_failures": failed_count,
                "total_checks": total_checks,
                "passed": passed_checks,
                "failed": failed_checks
            }
        })
    
    # Write service index
    index_data = {
        "account_id": account_id,
        "region": region,
        "service": service,
        "scan_id": os.path.basename(scan_folder),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_resources": total_resources,
        "total_chunks": len(chunks_metadata),
        "chunk_size": chunk_size,
        "chunks": chunks_metadata,
        "summary": {
            "total_checks": sum(c["stats"]["total_checks"] for c in chunks_metadata),
            "passed": sum(c["stats"]["passed"] for c in chunks_metadata),
            "failed": sum(c["stats"]["failed"] for c in chunks_metadata),
            "resources_with_failures": sum(c["stats"]["resources_with_failures"] 
                                          for c in chunks_metadata),
            "compliance_rate": 0
        }
    }
    
    # Calculate compliance rate
    if index_data["summary"]["total_checks"] > 0:
        index_data["summary"]["compliance_rate"] = round(
            100.0 * index_data["summary"]["passed"] / 
            index_data["summary"]["total_checks"], 2
        )
    
    index_path = os.path.join(service_dir, "index.json")
    with open(index_path, 'w') as f:
        json.dump(index_data, f, indent=2)
    
    return service_dir


def save_reporting_bundle(results: List[Dict[str, Any]], account_id: str | None = None, scan_folder: str = None) -> str:
    # Use provided scan_folder or create new one
    folder = scan_folder if scan_folder else create_report_folder()
    svc_ex = list_service_exceptions()  # Using exception_manager (no duplication)
    chk_ex = list_check_exceptions()     # Using exception_manager (no duplication)
    actions_cfg = _load_actions_config()
    selected = _load_actions_selection()
    standard_actions = actions_cfg.get("standard_actions") or {}

    # Service-specific data organization
    service_data = {}
    checks_main = []
    checks_skipped = []
    
    # Hierarchical structure
    hierarchical_data = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_accounts": 0,
            "total_resources": 0,
            "total_checks": 0
        },
        "accounts": {}
    }

    # Import here (not top-level) to avoid circular imports:
    # `engine/service_scanner.py` imports `utils.reporting_manager` at module import time.
    from .resource_identifier import extract_resource_identifier

    for r in results:
        service = r.get("service")
        acct = r.get("account") or account_id or "unknown"
        region = r.get("region") or "unknown"
        
        # Initialize account in hierarchical structure
        if acct not in hierarchical_data["accounts"]:
            hierarchical_data["accounts"][acct] = {
                "account_id": acct,
                "total_resources": 0,
                "total_checks": 0,
                "regions": {},
                "global_services": {}
            }
        
        # Skip inventory processing for now - focus on checks only
        # Process checks with ARN generation
        for c in r.get("checks", []) or []:
            item = {**c}
            item.setdefault("service", service)
            item.setdefault("account", acct)
            if region:
                item.setdefault("region", region)

            reporting_result = item.get("reporting_result")

            # service-level exceptions
            for ex in svc_ex:
                if ex.get("effect") not in {"mark_skipped", "skip_service"}:
                    continue
                if ex.get("service") != service:
                    continue
                sel = ex.get("selector") or {}
                if not _match_scope(acct, sel.get("account")):
                    continue
                if "region" in sel and not _match_scope(region, sel.get("region")):
                    continue
                if not _iso_not_expired(ex.get("expires_at")):
                    continue
                reporting_result = "SKIPPED"
                item["skip_meta"] = {"id": ex.get("id"), "scope": "service", "reason": ex.get("reason"), "expires_at": ex.get("expires_at")}
                break

            if reporting_result != "SKIPPED":
                for ex in chk_ex:
                    if ex.get("effect") not in {"mark_skipped", "skip_check"}:
                        continue
                    if ex.get("rule_id") != item.get("rule_id"):
                        continue
                    sel = ex.get("selector") or {}
                    if not _match_scope(acct, sel.get("account")):
                        continue
                    if "region" in sel and not _match_scope(region, sel.get("region")):
                        continue
                    if not _iso_not_expired(ex.get("expires_at")):
                        continue
                    reporting_result = "SKIPPED"
                    item["skip_meta"] = {"id": ex.get("id"), "scope": "check", "reason": ex.get("reason"), "expires_at": ex.get("expires_at")}
                    break

            if item.get("result") == "FAIL":
                sel_actions = selected.get(item.get("rule_id")) or []
                if sel_actions:
                    item["actions"] = [{"action": a, "args": (standard_actions.get(a) or {})} for a in sel_actions]

            # Add stable identifiers to each check using a single, shared extractor.
            # This keeps the logic uniform across new services (only global vs regional differs).
            try:
                id_region = None if is_global_service(service) else region
                resource_info = extract_resource_identifier(item, service, id_region, acct)
                item["resource_arn"] = resource_info.get("resource_arn")
                item["resource_uid"] = resource_info.get("resource_uid")
                item["resource_id"] = resource_info.get("resource_id")
                item["resource_type"] = resource_info.get("resource_type")
            except Exception as e:
                logger.debug(f"Failed to derive resource identifiers for check {item.get('rule_id')}: {e}")
                # Always keep at least a service-level ARN so downstream engines have something stable-ish.
                if is_global_service(service):
                    item["resource_arn"] = f"arn:aws:{service}::{acct}:{service}"
                else:
                    item["resource_arn"] = f"arn:aws:{service}:{region}:{acct}:{service}"
                item["resource_uid"] = item["resource_arn"]
                item["resource_id"] = None
                item["resource_type"] = "resource"

            # Get checked fields from the record (if stored)
            checked_fields = set(item.get('_checked_fields', []))
            # Remove the metadata field
            if '_checked_fields' in item:
                del item['_checked_fields']
            
            # Context fields that are always useful (ARN, ID, name, identifier, etc.)
            context_field_patterns = ['arn', 'id', 'name', 'identifier', 'arn']
            
            # Group evidence fields into a clean evidence dictionary
            evidence_fields = []
            for key, value in item.items():
                # Skip standard check fields
                if key in ["rule_id", "title", "severity", "assertion_id", "result", "region", 
                              "service", "account", "resource_arn", "reporting_result", "skip_meta", 
                              "actions", "timestamp", "message"]:
                    continue
                
                # Include if:
                # 1. It's a checked field (the var being evaluated)
                # 2. It's a context field (ARN, ID, name, etc.)
                key_lower = key.lower()
                is_checked_field = key in checked_fields
                is_context_field = any(key_lower.endswith(pattern) for pattern in context_field_patterns)
                
                # If we have checked fields, only include checked + context
                # If no checked fields (backward compat), include all
                if checked_fields:
                    if is_checked_field or is_context_field:
                        evidence_fields.append((key, value))
                else:
                    # Backward compatibility: include all if no checked fields specified
                    evidence_fields.append((key, value))
            
            # Create clean evidence dictionary
            item["evidence"] = dict(evidence_fields)
            
            # Remove evidence fields from main object to avoid duplication
            for key, _ in evidence_fields:
                if key in item:
                    del item[key]

            if reporting_result == "SKIPPED":
                item["reporting_result"] = "SKIPPED"
                checks_skipped.append(item)
            else:
                checks_main.append(item)

            # Add to hierarchical structure
            try:
                if is_global_service(service):
                    if service not in hierarchical_data["accounts"][acct]["global_services"]:
                        hierarchical_data["accounts"][acct]["global_services"][service] = {
                            "service": service,
                            "total_resources": 0,
                            "total_checks": 0,
                            "resources": [],
                            "checks": []
                        }
                    hierarchical_data["accounts"][acct]["global_services"][service]["checks"].append(item)
                    hierarchical_data["accounts"][acct]["global_services"][service]["total_checks"] += 1
                else:
                    if region not in hierarchical_data["accounts"][acct]["regions"]:
                        hierarchical_data["accounts"][acct]["regions"][region] = {
                            "region": region,
                            "total_resources": 0,
                            "total_checks": 0,
                            "services": {}
                        }
                    if service not in hierarchical_data["accounts"][acct]["regions"][region]["services"]:
                        hierarchical_data["accounts"][acct]["regions"][region]["services"][service] = {
                            "service": service,
                            "total_resources": 0,
                            "total_checks": 0,
                            "resources": [],
                            "checks": []
                        }
                    hierarchical_data["accounts"][acct]["regions"][region]["services"][service]["checks"].append(item)
                    hierarchical_data["accounts"][acct]["regions"][region]["services"][service]["total_checks"] += 1
                    hierarchical_data["accounts"][acct]["regions"][region]["total_checks"] += 1
                
                hierarchical_data["accounts"][acct]["total_checks"] += 1
            except Exception as e:
                print(f"Warning: Failed to add check to hierarchical structure: {e}")

    # Update hierarchical metadata
    hierarchical_data["metadata"]["total_accounts"] = len(hierarchical_data["accounts"])
    hierarchical_data["metadata"]["total_resources"] = sum(acc["total_resources"] for acc in hierarchical_data["accounts"].values())
    hierarchical_data["metadata"]["total_checks"] = sum(acc["total_checks"] for acc in hierarchical_data["accounts"].values())

    # Create account-specific folders and service-specific files
    account_folders = {}
    for account_id, account_data in hierarchical_data["accounts"].items():
        account_folder = os.path.join(folder, f"account_{account_id}")
        os.makedirs(account_folder, exist_ok=True)
        account_folders[account_id] = account_folder
        
        # Process global services
        for service, service_data in account_data["global_services"].items():
            if service_data["total_checks"] > 0:
                filename = f"{account_id}_global_{service}_checks.json"
                filepath = os.path.join(account_folder, filename)
                
                # Filter checks for this service
                service_checks = [check for check in checks_main if check.get("service") == service and check.get("account") == account_id]
                
                with open(filepath, "w") as fh:
                    json.dump({
                        "metadata": _meta(account_id, folder),
                        "service": service,
                        "scope": "global",
                        "account": account_id,
                        "total_checks": len(service_checks),
                        "checks": service_checks
                    }, fh, indent=2)
        
        # Process regional services
        for region, region_data in account_data["regions"].items():
            if region != "unknown":
                for service, service_data in region_data["services"].items():
                    if service_data["total_checks"] > 0:
                        filename = f"{account_id}_{region}_{service}_checks.json"
                        filepath = os.path.join(account_folder, filename)
                        
                        # Filter checks for this service and region
                        service_checks = [check for check in checks_main if check.get("service") == service and check.get("account") == account_id and check.get("region") == region]
                        
                        with open(filepath, "w") as fh:
                            json.dump({
                                "metadata": _meta(account_id, folder),
                                "service": service,
                                "scope": "regional",
                                "account": account_id,
                                "region": region,
                                "total_checks": len(service_checks),
                                "checks": service_checks
                            }, fh, indent=2)

    # Hierarchical summary removed - using individual service files instead
    
    # Save index with new file structure
    with open(os.path.join(folder, "index.json"), "w") as fh:
        json.dump({
            "metadata": _meta(account_id, folder),
            "summary": {
                "total_checks": hierarchical_data["metadata"]["total_checks"],
                "total_resources": hierarchical_data["metadata"]["total_resources"],
                "total_accounts": hierarchical_data["metadata"]["total_accounts"]
            },
            "account_folders": list(account_folders.keys()),
            "files": {
                "index": "index.json"
            }
        }, fh, indent=2)

    # Extract discovered resources using generic approach
    try:
        discoveries_path = extract_inventory_assets(results, folder, account_id)
        logger.info(f"Inventory assets extracted to: {inventory_path}")
    except Exception as e:
        logger.warning(f"Failed to extract discovered resources: {e}")
    
    # Always emit discoveries.ndjson (best-effort). This is consumed by Inventory/Threat engines.
    try:
        discoveries_path = extract_inventory_assets(results, folder, account_id)
        logger.info(f"Generated discovered resources: {discoveries_path}")
    except Exception as e:
        logger.warning(f"Failed to generate discovered resources: {e}")

    return os.path.abspath(folder)


def extract_inventory_assets(
    results: List[Dict[str, Any]], 
    scan_folder: str,
    account_id: str = None
) -> str:
    """
    Extract discovered resources from scan results using generic approach.
    
    Uses the existing extract_resource_identifier logic from service_scanner
    to handle all services uniformly (global and regional).
    
    Args:
        results: List of scan result dictionaries with 'inventory' and 'checks' keys
        scan_folder: Path to scan folder where discoveries.ndjson will be saved
        account_id: Default account ID if not found in results
    
    Returns:
        Path to discoveries.ndjson file
    """
    # Import here (not top-level) to avoid circular import issues.
    from .resource_identifier import extract_resource_identifier
    
    tenant_id = _get_tenant_id()
    scan_run_id = os.path.basename(scan_folder)
    assets = []
    seen_resources = set()  # Track by resource_uid to avoid duplicates
    
    for result in results:
        service = result.get("service")
        account = result.get("account") or account_id or "unknown"
        region = result.get("region") or "global"
        # scope may exist in result, but we compute scope/region from the service itself for consistency.
        _ = result.get("scope", "regional")
        inventory = result.get("inventory", {})
        
        # Build raw_ref path for metadata
        raw_ref_base = os.path.join(scan_folder, "raw", "aws", account, region)
        
        # Process each discovery operation's results
        for discovery_id, items in inventory.items():
            if not isinstance(items, list):
                continue
            
            # Check if this discovery should produce discovered resources (universal heuristic)
            # Skip if it's a detail view, task, or config operation
            if not is_cspm_inventory_resource(discovery_id, discovery_config=None):
                continue
            
            # Extract service name from discovery_id (e.g., "aws.s3.list_buckets" -> "s3")
            # Format: "aws.{service}.{operation}"
            parts = discovery_id.split(".")
            if len(parts) >= 2 and parts[0] == "aws":
                service_from_discovery = parts[1]
            else:
                service_from_discovery = service
            
            # Determine if service is global or regional
            discovery_service_is_global = is_global_service(service_from_discovery)
            discovery_region = None if discovery_service_is_global else (region if region != "global" else "us-east-1")
            final_region = "global" if discovery_service_is_global else (discovery_region or "global")
            final_scope = "global" if discovery_service_is_global else "regional"
            
            # Build raw_ref path
            raw_ref_path = os.path.join(raw_ref_base, f"{service_from_discovery}.json")
            
            for item in items:
                if not isinstance(item, dict):
                    continue
                
                # Debug: Check if enriched fields are present (generic for any service)
                # Only log first item to avoid spam
                if items.index(item) == 0 and '_dependent_data' in item:
                    dep_data = item.get('_dependent_data', {})
                    logger.debug(f"[INVENTORY-DEBUG] {service_from_discovery} {discovery_id} has enriched fields from {len(dep_data)} dependent discoveries")
                
                # Use existing extract_resource_identifier function (handles all services generically)
                try:
                    resource_info = extract_resource_identifier(
                        item, 
                        service_from_discovery, 
                        discovery_region, 
                        account
                    )
                    
                    resource_id = resource_info.get("resource_id")
                    resource_type = resource_info.get("resource_type", "resource")
                    resource_arn = resource_info.get("resource_arn")
                    resource_uid = resource_info.get("resource_uid")
                    
                    # Skip if no valid identifiers
                    if not resource_id and not resource_arn:
                        continue
                    
                    # Skip duplicates (same resource_uid)
                    if resource_uid in seen_resources:
                        continue
                    seen_resources.add(resource_uid)
                    
                    # Extract tags (generic approach)
                    tags = {}
                    if "Tags" in item and isinstance(item["Tags"], list):
                        for tag in item["Tags"]:
                            if isinstance(tag, dict) and "Key" in tag and "Value" in tag:
                                tags[tag["Key"]] = tag["Value"]
                    elif "tags" in item and isinstance(item["tags"], dict):
                        tags = item["tags"]
                    elif "tags" in item and isinstance(item["tags"], str):
                        try:
                            tags = json.loads(item["tags"]) if item["tags"] else {}
                        except:
                            tags = {}
                    
                    # Extract name
                    name = item.get("name") or item.get("Name") or item.get("resource_name") or resource_id or ""
                    
                    # Extract created_at (for UI: created_at)
                    created_at = item.get("CreationDate") or item.get("CreateDate") or item.get("createdAt") or item.get("CreatedAt")
                    if created_at and isinstance(created_at, str):
                        # Try to keep ISO format if already string
                        pass
                    elif created_at:
                        # Convert datetime to ISO string
                        try:
                            created_at = created_at.isoformat() + "Z" if hasattr(created_at, 'isoformat') else str(created_at)
                        except:
                            created_at = None
                    
                    # Extract updated_at (for UI: updated_at)
                    updated_at = item.get("LastModifiedDate") or item.get("UpdateDate") or item.get("updatedAt") or item.get("UpdatedAt") or item.get("LastUpdateDate")
                    if updated_at and isinstance(updated_at, str):
                        pass
                    elif updated_at:
                        try:
                            updated_at = updated_at.isoformat() + "Z" if hasattr(updated_at, 'isoformat') else str(updated_at)
                        except:
                            updated_at = None
                    
                    # Extract environment from tags (for UI: environment)
                    environment = (
                        tags.get("Environment") or 
                        tags.get("env") or 
                        tags.get("Env") or 
                        tags.get("environment") or
                        tags.get("ENV") or
                        ""
                    )
                    
                    # Derive category from service/resource_type (for UI: category)
                    category_map = {
                        "ec2": "Compute",
                        "s3": "Storage",
                        "rds": "Database",
                        "lambda": "Compute",
                        "iam": "Security",
                        "vpc": "Network",
                        "elb": "Network",
                        "cloudfront": "Network",
                        "route53": "Network",
                        "sns": "Application",
                        "sqs": "Application",
                        "dynamodb": "Database",
                        "kms": "Security",
                        "secretsmanager": "Security",
                        "cloudwatch": "Monitoring",
                        "account": "Account"
                    }
                    category = category_map.get(service_from_discovery.lower(), "Other")
                    
                    # Extract lifecycle_state (for UI: lifecycle_state)
                    lifecycle_state = (
                        item.get("State") or 
                        item.get("Status") or 
                        item.get("LifecycleState") or 
                        item.get("InstanceState") or
                        item.get("DBInstanceStatus") or
                        item.get("BucketLocationConstraint") or
                        ""
                    )
                    # Normalize state values for UI
                    if lifecycle_state and isinstance(lifecycle_state, dict):
                        lifecycle_state = lifecycle_state.get("Name", "")
                    lifecycle_state = str(lifecycle_state).title() if lifecycle_state else ""
                    
                    # Extract health_status (for UI: health_status)
                    health_status = (
                        item.get("HealthStatus") or 
                        item.get("Health") or 
                        item.get("StateReason") or  # For EC2 instances
                        ""
                    )
                    # Normalize health status for UI
                    if health_status and isinstance(health_status, str):
                        health_status = health_status.title()
                    health_status = health_status if health_status else "Unknown"
                    
                    # Use ARN as resource_id if available (more useful for AWS UI)
                    display_resource_id = resource_arn or resource_id or ""
                    
                    # Standard template fields (protected)
                    standard_fields = {
                        "schema_version", "tenant_id", "scan_run_id", "provider", "service",
                        "account_id", "region", "scope", "resource_type", "resource_id",
                        "resource_arn", "resource_uid", "name", "tags", "metadata", "hash_sha256",
                        "environment", "category", "lifecycle_state", "health_status",
                        "created_at", "updated_at", "is_aws_managed"
                    }
                    
                    # Create asset record with canonical cspm_asset.v1 schema + UI fields
                    asset = {
                        "schema_version": "cspm_asset.v1",
                        "tenant_id": tenant_id,
                        "scan_run_id": scan_run_id,
                        "provider": "aws",
                        "account_id": account,
                        "region": final_region,
                        "scope": final_scope,
                        "resource_type": f"{service_from_discovery}:{resource_type}",  # Use : separator (service:type)
                        "resource_id": display_resource_id,  # Prefer ARN if available
                        "resource_uid": resource_uid,
                        "name": name,
                        "tags": tags,
                        # UI-required fields (add to top level for easy access)
                        "environment": environment,
                        "category": category,
                        "lifecycle_state": lifecycle_state,
                        "health_status": health_status,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "metadata": {
                            "created_at": created_at,  # Keep in metadata for compatibility
                            "updated_at": updated_at,  # Keep in metadata
                            "labels": {},  # Can be populated from tags if needed
                            "raw_refs": [raw_ref_path],
                            "discovery_operation": discovery_id,
                            "resource_arn": resource_arn,  # Keep ARN in metadata for AWS-specific use
                            "original_resource_id": resource_id  # Keep original ID if ARN was used
                        }
                    }
                    
                    # Preserve enriched fields from dependent discoveries (nested approach)
                    # Store entire dependent discovery data under _dependent_data key
                    # This must be done BEFORE the loop that skips _ fields
                    if '_dependent_data' in item:
                        logger.debug(f"[DISCOVERIES-WRITE] Found _dependent_data in item for {name}: type={type(item['_dependent_data']).__name__}")
                        if isinstance(item['_dependent_data'], dict):
                            asset['_dependent_data'] = item['_dependent_data']
                            enriched_discoveries = list(item['_dependent_data'].keys())
                            logger.info(f"[DISCOVERIES-WRITE] Preserved _dependent_data with {len(enriched_discoveries)} discoveries: {enriched_discoveries[:3]}")
                            # Debug: Log sample data from first discovery
                            if enriched_discoveries:
                                first_disc = enriched_discoveries[0]
                                first_data = item['_dependent_data'][first_disc]
                                if isinstance(first_data, dict):
                                    logger.debug(f"[DISCOVERIES-WRITE] Sample data from {first_disc}: {len(first_data)} fields - {list(first_data.keys())[:5]}")
                        else:
                            logger.warning(f"[DISCOVERIES-WRITE] _dependent_data is not a dict for {name}: {type(item['_dependent_data']).__name__}")
                    else:
                        logger.debug(f"[DISCOVERIES-WRITE] No _dependent_data in item for {name} (item keys: {list(item.keys())[:10]})")
                    
                    # Also preserve individual enriched fields for backward compatibility (if not using nested approach)
                    enriched_fields_added = []
                    for key, value in item.items():
                        # Skip standard fields, matching keys, internal tracking fields
                        # NOTE: _dependent_data is already handled above, so skip it here
                        if key in standard_fields or (key.startswith('_') and key != '_dependent_data') or key in ['Name', 'Bucket', 'ResourceId', 'CreationDate', 'CreateDate']:
                            continue
                        # Skip None values
                        if value is None:
                            continue
                        # Add enriched field to asset
                        asset[key] = value
                        enriched_fields_added.append(key)
                    
                    # Debug logging for enriched fields (generic for any service)
                    if enriched_fields_added:
                        logger.debug(f"[DISCOVERIES-WRITE] {service_from_discovery} {name}: Preserved {len(enriched_fields_added)} enriched fields")
                    
                    # Preserve _enriched_from if present (for tracking)
                    if '_enriched_from' in item and item['_enriched_from']:
                        asset['metadata']['enriched_from'] = item['_enriched_from']
                    
                    # Compute hash for drift detection
                    asset["hash_sha256"] = compute_asset_hash(asset)
                    
                    # Debug: Verify _dependent_data is in asset (generic for any service)
                    if '_dependent_data' in asset:
                        logger.debug(f"[DISCOVERIES-WRITE] ✅ Asset for {service_from_discovery} {name} has _dependent_data: {len(asset['_dependent_data'])} dependent discoveries")
                    elif items.index(item) == 0:  # Only log first item to avoid spam
                        logger.debug(f"[DISCOVERIES-WRITE] ⚠️  Asset for {service_from_discovery} {name} has no _dependent_data")
                    
                    assets.append(asset)
                    
                except Exception as e:
                    # Log but continue processing other items
                    logger.debug(f"Failed to extract resource identifier for {discovery_id}: {e}")
                    continue
    
    # Save as NDJSON
    discoveries_path = os.path.join(scan_folder, "discoveries.ndjson")
    with open(discoveries_path, 'w') as f:
        for asset in assets:
            # Debug: Log first asset with _dependent_data for verification (generic)
            if assets.index(asset) == 0 and '_dependent_data' in asset:
                logger.debug(f"[DISCOVERIES-WRITE] Sample asset with _dependent_data: {asset.get('service')} {asset.get('name')} - {len(asset['_dependent_data'])} dependent discoveries")
            f.write(json.dumps(asset, default=str) + "\n")
    
    logger.info(f"Generated {len(assets)} discovered resources in {discoveries_path}")
    
    return discoveries_path 