"""
GCP Discovery Scanner

Multi-cloud architecture: Uses a service handler registry pattern where each GCP
service has a registered handler. New services are added by defining a handler function
and registering it — no hardcoded if/elif chains.

Currently supported:
- iam (Global - Service Accounts)
- compute (Regional - VM Instances)
- bigquery (PaaS - Datasets)
- storage (SaaS - Buckets)

Extends to all GCP services by adding handler functions.
"""

from typing import Dict, List, Any, Optional, Tuple, Callable
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from providers.common.models.provider_interface import DiscoveryScanner, AuthenticationError, DiscoveryError

logger = logging.getLogger(__name__)

# Thread pool for blocking GCP SDK calls
_GCP_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# Default GCP regions for scanning
DEFAULT_GCP_REGIONS = [
    'us-central1', 'us-east1', 'us-east4', 'us-west1', 'us-west2',
    'europe-west1', 'europe-west2', 'europe-west3', 'europe-west4',
    'asia-east1', 'asia-southeast1', 'asia-northeast1',
    'australia-southeast1', 'southamerica-east1',
]

# ─── Service Handler Registry ──────────────────────────────────────
#
# Each handler: fn(credential, project_id, region, config) -> List[Dict]
# Add new services by defining a handler and adding to this dict.
#
GCP_SERVICE_HANDLERS: Dict[str, Callable] = {}


def gcp_handler(service_name: str):
    """Decorator to register a GCP service discovery handler."""
    def decorator(fn: Callable):
        GCP_SERVICE_HANDLERS[service_name] = fn
        return fn
    return decorator


# ─── Resource Identifier Helper ────────────────────────────────────

def _enrich_gcp_item(item: Dict) -> Dict:
    """Inject standard resource identifier fields used by database_manager.

    GCP resources use selfLink or name as primary identifier. This maps
    them to resource_arn/resource_uid/resource_id so the DB layer can
    store them correctly.
    """
    self_link = item.get('selfLink', '')
    resource_id = item.get('id', '')
    uid = self_link or str(resource_id)

    item['resource_arn'] = uid
    item['resource_id'] = str(resource_id) if resource_id else uid
    item['resource_uid'] = uid

    # Build _raw_response (everything except internal/metadata fields)
    item['_raw_response'] = {k: v for k, v in item.items()
                             if not k.startswith('_') and k not in (
                                 'resource_arn', 'resource_uid', 'resource_id', 'resource_type')}
    return item


# ─── Service Handlers ───────────────────────────────────────────────

@gcp_handler('iam')
def _scan_iam(credential, project_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover GCP IAM service accounts (global — not region-specific)."""
    from google.cloud import iam_admin_v1

    client = iam_admin_v1.IAMClient(credentials=credential)
    request = iam_admin_v1.ListServiceAccountsRequest(
        name=f"projects/{project_id}"
    )
    resources = []
    for sa in client.list_service_accounts(request=request):
        item = {
            'name': sa.name,
            'email': sa.email,
            'display_name': sa.display_name,
            'unique_id': sa.unique_id,
            'description': sa.description,
            'disabled': sa.disabled,
            'oauth2_client_id': sa.oauth2_client_id,
            'project_id': sa.project_id,
            'selfLink': sa.name,
            'id': sa.unique_id,
            'resource_type': 'iam.googleapis.com/ServiceAccount',
            '_discovery_id': 'gcp.iam.service_accounts.list',
        }
        resources.append(_enrich_gcp_item(item))
    logger.info(f"  iam: {len(resources)} service accounts found")
    return resources


@gcp_handler('compute')
def _scan_compute(credential, project_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover GCP compute instances using aggregated list (all zones)."""
    from google.cloud import compute_v1

    client = compute_v1.InstancesClient(credentials=credential)
    resources = []
    agg_list = client.aggregated_list(project=project_id)
    for zone_key, instances_scoped_list in agg_list:
        if not instances_scoped_list.instances:
            continue
        # Filter by region (zone: us-central1-a → region: us-central1)
        zone_region = '-'.join(zone_key.replace('zones/', '').split('-')[:-1])
        if region and region.lower() != zone_region.lower():
            continue
        for instance in instances_scoped_list.instances:
            item = {
                'id': str(instance.id),
                'name': instance.name,
                'selfLink': instance.self_link,
                'zone': instance.zone,
                'machine_type': instance.machine_type,
                'status': instance.status,
                'creation_timestamp': instance.creation_timestamp,
                'can_ip_forward': instance.can_ip_forward,
                'deletion_protection': instance.deletion_protection,
                'labels': dict(instance.labels) if instance.labels else {},
                'resource_type': 'compute.googleapis.com/Instance',
                '_discovery_id': 'gcp.compute.instances.aggregated_list',
            }
            resources.append(_enrich_gcp_item(item))
    logger.info(f"  compute/{region}: {len(resources)} instances found")
    return resources


@gcp_handler('bigquery')
def _scan_bigquery(credential, project_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover GCP BigQuery datasets (global — not region-specific)."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id, credentials=credential)
    resources = []
    for dataset_ref in client.list_datasets(project=project_id):
        try:
            dataset = client.get_dataset(dataset_ref.reference)
            item = {
                'id': f"projects/{project_id}/datasets/{dataset.dataset_id}",
                'name': dataset.dataset_id,
                'selfLink': f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets/{dataset.dataset_id}",
                'friendly_name': dataset.friendly_name,
                'description': dataset.description,
                'location': dataset.location,
                'creation_time': dataset.created.isoformat() if dataset.created else None,
                'modified_time': dataset.modified.isoformat() if dataset.modified else None,
                'default_table_expiration_ms': dataset.default_table_expiration_ms,
                'labels': dict(dataset.labels) if dataset.labels else {},
                'resource_type': 'bigquery.googleapis.com/Dataset',
                '_discovery_id': 'gcp.bigquery.datasets.list',
            }
            resources.append(_enrich_gcp_item(item))
        except Exception as e:
            logger.warning(f"Failed to get BigQuery dataset {dataset_ref.dataset_id}: {e}")
    logger.info(f"  bigquery: {len(resources)} datasets found")
    return resources


@gcp_handler('storage')
def _scan_storage(credential, project_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover GCP Cloud Storage buckets (global — not region-specific)."""
    from google.cloud import storage

    client = storage.Client(project=project_id, credentials=credential)
    resources = []
    for bucket in client.list_buckets(project=project_id):
        item = {
            'id': bucket.id,
            'name': bucket.name,
            'selfLink': f"https://storage.googleapis.com/storage/v1/b/{bucket.name}",
            'location': bucket.location,
            'location_type': getattr(bucket, 'location_type', None),
            'storage_class': bucket.storage_class,
            'time_created': bucket.time_created.isoformat() if bucket.time_created else None,
            'versioning_enabled': bucket.versioning_enabled,
            'labels': dict(bucket.labels) if bucket.labels else {},
            'requester_pays': bucket.requester_pays,
            'resource_type': 'storage.googleapis.com/Bucket',
            '_discovery_id': 'gcp.storage.buckets.list',
        }
        resources.append(_enrich_gcp_item(item))
    logger.info(f"  storage: {len(resources)} buckets found")
    return resources


# ─── Main Scanner Class ─────────────────────────────────────────────

class GCPDiscoveryScanner(DiscoveryScanner):
    """
    GCP-specific discovery scanner implementation.

    Uses a handler registry pattern: GCP_SERVICE_HANDLERS maps service names
    to handler functions. To add a new GCP service, just define a handler
    function with the @gcp_handler('service_name') decorator above.
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        super().__init__(credentials, **kwargs)
        self.credential = None
        # Extract project_id from top level or nested credentials
        self.project_id = (
            credentials.get('project_id')
            or credentials.get('account_id')
            or (credentials.get('credentials') or {}).get('project_id')
        )

    def authenticate(self) -> Any:
        """
        Authenticate to GCP using provided credentials.

        Supports:
        - Service Account (JSON key file)
        - Workload Identity
        - Application Default Credentials (gcloud CLI auth)
        """
        try:
            cred_type = self.credentials.get('credential_type', '').lower()

            if cred_type in ('service_account', 'gcp_service_account'):
                from google.oauth2 import service_account
                # Support multiple credential formats:
                # 1. {"credentials_json": {...}}
                # 2. {"service_account_json": {...}}
                # 3. {"credentials": {...}}  (Secrets Manager wrapper format)
                # 4. Direct SA JSON with "type": "service_account" at top level
                credentials_data = (
                    self.credentials.get('credentials_json')
                    or self.credentials.get('service_account_json')
                    or self.credentials.get('credentials')
                )
                if not credentials_data and self.credentials.get('type') == 'service_account':
                    credentials_data = self.credentials
                if isinstance(credentials_data, str):
                    import json
                    credentials_data = json.loads(credentials_data)
                self.credential = service_account.Credentials.from_service_account_info(
                    credentials_data
                )
                if not self.project_id and credentials_data:
                    self.project_id = credentials_data.get('project_id')
                logger.info("GCP authentication successful (Service Account)")

            elif cred_type == 'application_default':
                import google.auth
                self.credential, default_project = google.auth.default()
                if not self.project_id:
                    self.project_id = default_project
                logger.info(f"GCP authentication successful (Application Default, project={self.project_id})")

            else:
                import google.auth
                self.credential, default_project = google.auth.default()
                if not self.project_id:
                    self.project_id = default_project
                logger.info(f"GCP auth: unknown type '{cred_type}', using Application Default (project={self.project_id})")

            return self.credential

        except Exception as e:
            logger.error(f"GCP authentication failed: {e}")
            raise AuthenticationError(f"GCP authentication failed: {e}")

    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute GCP service discovery.

        Dispatches to the registered handler for the service.
        Runs GCP SDK calls in a thread pool (SDK is blocking).
        Returns (discoveries, scan_metadata) tuple.
        """
        handler = GCP_SERVICE_HANDLERS.get(service)
        if not handler:
            logger.warning(f"GCP: no handler registered for service '{service}'. "
                           f"Available: {list(GCP_SERVICE_HANDLERS.keys())}")
            return [], {'service': service, 'region': region, 'error': f'No handler for {service}'}

        loop = asyncio.get_event_loop()
        try:
            discoveries = await loop.run_in_executor(
                _GCP_EXECUTOR,
                handler,
                self.credential,
                self.project_id,
                region,
                config
            )
            scan_metadata = {
                'service': service,
                'region': region,
                'resource_count': len(discoveries),
                'provider': 'gcp',
            }
            logger.info(f"GCP {service}/{region}: {len(discoveries)} resources discovered")
            return discoveries, scan_metadata

        except Exception as e:
            logger.error(f"GCP scan_service failed for {service}/{region}: {e}")
            return [], {'service': service, 'region': region, 'error': str(e)}

    def get_client(self, service: str, region: str) -> Any:
        """Get GCP SDK client for specific service."""
        if service == 'iam':
            from google.cloud import iam_admin_v1
            return iam_admin_v1.IAMClient(credentials=self.credential)
        elif service == 'compute':
            from google.cloud import compute_v1
            return compute_v1.InstancesClient(credentials=self.credential)
        elif service == 'bigquery':
            from google.cloud import bigquery
            return bigquery.Client(project=self.project_id, credentials=self.credential)
        elif service == 'storage':
            from google.cloud import storage
            return storage.Client(project=self.project_id, credentials=self.credential)
        else:
            raise DiscoveryError(f"Unsupported GCP service: {service}")

    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Extract resource identifiers from GCP response.

        GCP uses selfLink format:
        https://www.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}
        """
        self_link = item.get('selfLink', '')
        resource_name = item.get('name', '')
        resource_id = item.get('id', '')
        if not resource_type:
            resource_type = item.get('resource_type', '')

        return {
            'resource_arn': self_link or str(resource_id),
            'resource_id': str(resource_id) if resource_id else self_link,
            'resource_name': resource_name,
            'resource_uid': self_link or str(resource_id),
            'resource_type': resource_type,
        }

    def get_service_client_name(self, service: str) -> str:
        """Map service name to GCP SDK client name."""
        mapping = {
            'iam': 'iam_admin_v1',
            'compute': 'compute_v1',
            'bigquery': 'bigquery',
            'storage': 'storage',
        }
        return mapping.get(service, f"{service}_v1")

    async def list_available_regions(self) -> List[str]:
        """List available GCP regions for the project."""
        try:
            from google.cloud import compute_v1
            client = compute_v1.RegionsClient(credentials=self.credential)
            regions = []
            for region in client.list(project=self.project_id):
                if region.status == 'UP':
                    regions.append(region.name)
            logger.info(f"GCP: {len(regions)} regions available")
            return sorted(regions)
        except Exception as e:
            logger.warning(f"Failed to list GCP regions, using defaults: {e}")
            return DEFAULT_GCP_REGIONS

    def get_account_id(self) -> str:
        """Return project ID as account identifier."""
        return self.project_id or ''
