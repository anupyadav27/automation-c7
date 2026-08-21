"""
OCI Discovery Scanner

Implements OCI-specific discovery using handler registry pattern.
Each service handler is a simple function registered via @oci_handler decorator.
"""

from typing import Dict, List, Any, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
import asyncio
import logging

from providers.common.models.provider_interface import DiscoveryScanner, AuthenticationError, DiscoveryError

logger = logging.getLogger(__name__)

# Thread pool for blocking OCI SDK calls
_OCI_EXECUTOR = ThreadPoolExecutor(max_workers=10)

DEFAULT_OCI_REGIONS = [
    'us-ashburn-1', 'us-phoenix-1', 'us-sanjose-1',
    'eu-frankfurt-1', 'eu-amsterdam-1', 'eu-zurich-1',
    'uk-london-1', 'ap-mumbai-1', 'ap-tokyo-1',
    'ap-sydney-1', 'ca-toronto-1', 'sa-saopaulo-1',
]

# ─── Service Handler Registry ──────────────────────────────────────
OCI_SERVICE_HANDLERS: Dict[str, Callable] = {}


def oci_handler(service_name: str):
    """Decorator to register an OCI service discovery handler."""
    def decorator(fn: Callable):
        OCI_SERVICE_HANDLERS[service_name] = fn
        return fn
    return decorator


# ─── Resource Identifier Helper ────────────────────────────────────

def _enrich_oci_item(item: Dict) -> Dict:
    """Inject standard resource identifier fields used by database_manager.

    OCI resources use OCID as primary identifier. This maps them to
    resource_arn/resource_uid/resource_id so the DB layer stores them.
    """
    ocid = item.get('id', '')
    item['resource_arn'] = ocid       # OCID as ARN equivalent
    item['resource_id'] = ocid
    item['resource_uid'] = ocid

    # Build _raw_response (everything except internal/metadata fields)
    item['_raw_response'] = {k: v for k, v in item.items()
                             if not k.startswith('_') and k not in (
                                 'resource_arn', 'resource_uid', 'resource_id', 'resource_type')}
    return item


# ─── Service Handlers ───────────────────────────────────────────────

@oci_handler('audit')
def _scan_audit(config_dict, signer, tenancy_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover OCI audit events (tenancy-scoped, last 24h)."""
    import oci
    from datetime import datetime, timedelta, timezone

    audit_client = oci.audit.AuditClient(config_dict, signer=signer)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)

    resources = []
    try:
        response = oci.pagination.list_call_get_all_results(
            audit_client.list_events,
            compartment_id=tenancy_id,
            start_time=start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            end_time=end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        )
        for event in response.data:
            item = {
                'id': getattr(event, 'event_id', ''),
                'event_type': getattr(event, 'event_type', ''),
                'source': getattr(event, 'source', ''),
                'compartment_id': getattr(event, 'compartment_id', ''),
                'event_time': str(getattr(event, 'event_time', '')),
                'credential_id': getattr(event, 'credential_id', ''),
                'request_action': getattr(event, 'request_action', ''),
                'request_agent': getattr(event, 'request_agent', ''),
                'resource_type': 'oci.audit/Event',
                '_discovery_id': 'oci.audit.list_events',
            }
            resources.append(_enrich_oci_item(item))
    except oci.exceptions.ServiceError as e:
        logger.warning(f"OCI audit list_events failed: {e.message}")
    except Exception as e:
        logger.warning(f"OCI audit scan error: {e}")
    logger.info(f"  audit/{region}: {len(resources)} events found")
    return resources


@oci_handler('compute')
def _scan_compute(config_dict, signer, tenancy_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover OCI compute instances in a compartment."""
    import oci

    compute_client = oci.core.ComputeClient(config_dict, signer=signer)

    resources = []
    try:
        response = oci.pagination.list_call_get_all_results(
            compute_client.list_instances,
            compartment_id=tenancy_id,
        )
        for instance in response.data:
            item = {
                'id': instance.id,
                'display_name': instance.display_name,
                'lifecycle_state': instance.lifecycle_state,
                'availability_domain': instance.availability_domain,
                'shape': instance.shape,
                'region': instance.region,
                'compartment_id': instance.compartment_id,
                'time_created': str(instance.time_created),
                'image_id': getattr(instance, 'image_id', None),
                'fault_domain': getattr(instance, 'fault_domain', None),
                'freeform_tags': instance.freeform_tags or {},
                'defined_tags': instance.defined_tags or {},
                'resource_type': 'oci.core/Instance',
                '_discovery_id': 'oci.compute.list_instances',
            }
            resources.append(_enrich_oci_item(item))
    except oci.exceptions.ServiceError as e:
        logger.warning(f"OCI compute list_instances failed: {e.message}")
    except Exception as e:
        logger.warning(f"OCI compute scan error: {e}")
    logger.info(f"  compute/{region}: {len(resources)} instances found")
    return resources


@oci_handler('database')
def _scan_database(config_dict, signer, tenancy_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover OCI database systems in a compartment."""
    import oci

    db_client = oci.database.DatabaseClient(config_dict, signer=signer)

    resources = []
    try:
        response = oci.pagination.list_call_get_all_results(
            db_client.list_db_systems,
            compartment_id=tenancy_id,
        )
        for db_system in response.data:
            item = {
                'id': db_system.id,
                'display_name': db_system.display_name,
                'lifecycle_state': db_system.lifecycle_state,
                'availability_domain': db_system.availability_domain,
                'shape': db_system.shape,
                'compartment_id': db_system.compartment_id,
                'database_edition': getattr(db_system, 'database_edition', None),
                'time_created': str(db_system.time_created),
                'hostname': getattr(db_system, 'hostname', None),
                'domain': getattr(db_system, 'domain', None),
                'cpu_core_count': getattr(db_system, 'cpu_core_count', None),
                'data_storage_size_in_gbs': getattr(db_system, 'data_storage_size_in_gbs', None),
                'freeform_tags': db_system.freeform_tags or {},
                'defined_tags': db_system.defined_tags or {},
                'resource_type': 'oci.database/DbSystem',
                '_discovery_id': 'oci.database.list_db_systems',
            }
            resources.append(_enrich_oci_item(item))
    except oci.exceptions.ServiceError as e:
        logger.warning(f"OCI database list_db_systems failed: {e.message}")
    except Exception as e:
        logger.warning(f"OCI database scan error: {e}")
    logger.info(f"  database/{region}: {len(resources)} DB systems found")
    return resources


@oci_handler('object_storage')
def _scan_object_storage(config_dict, signer, tenancy_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover OCI Object Storage buckets."""
    import oci

    os_client = oci.object_storage.ObjectStorageClient(config_dict, signer=signer)

    resources = []
    try:
        # Get namespace first (required for bucket listing)
        namespace = os_client.get_namespace(compartment_id=tenancy_id).data

        response = oci.pagination.list_call_get_all_results(
            os_client.list_buckets,
            namespace_name=namespace,
            compartment_id=tenancy_id,
        )
        for bucket in response.data:
            item = {
                'id': f"oci.objectstorage:{namespace}:{bucket.name}",
                'name': bucket.name,
                'namespace': namespace,
                'compartment_id': bucket.compartment_id,
                'time_created': str(bucket.time_created),
                'etag': getattr(bucket, 'etag', None),
                'freeform_tags': bucket.freeform_tags or {},
                'defined_tags': bucket.defined_tags or {},
                'resource_type': 'oci.objectstorage/Bucket',
                '_discovery_id': 'oci.object_storage.list_buckets',
            }
            resources.append(_enrich_oci_item(item))
    except oci.exceptions.ServiceError as e:
        logger.warning(f"OCI object_storage failed: {e.message}")
    except Exception as e:
        logger.warning(f"OCI object_storage scan error: {e}")
    logger.info(f"  object_storage/{region}: {len(resources)} buckets found")
    return resources


# ─── Scanner Class ──────────────────────────────────────────────────

class OCIDiscoveryScanner(DiscoveryScanner):
    """
    OCI-specific discovery scanner implementation.

    Uses handler registry pattern: OCI_SERVICE_HANDLERS maps service names
    to handler functions. Add new services by decorating with @oci_handler.
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        super().__init__(credentials, **kwargs)
        self.oci_config = None
        self.signer = None
        # Extract tenancy_id from top level or nested credentials
        self.tenancy_id = (
            credentials.get('tenancy_id')
            or credentials.get('tenancy_ocid')
            or credentials.get('account_id')
            or (credentials.get('credentials') or {}).get('tenancy_id')
            or (credentials.get('credentials') or {}).get('tenancy_ocid')
        )

    def authenticate(self) -> Any:
        """
        Authenticate to OCI using provided credentials.

        Supports:
        - API Key (user OCID, fingerprint, private key)
        - Instance Principal
        """
        try:
            import oci

            cred_type = self.credentials.get('credential_type', '').lower()

            # Support nested credentials (Secrets Manager wrapper)
            creds = self.credentials
            if 'credentials' in creds and isinstance(creds['credentials'], dict):
                inner = creds['credentials']
                if inner.get('user_ocid') or inner.get('tenancy_ocid'):
                    creds = {**creds, **inner}

            if cred_type in ('api_key', 'oci_user_principal', 'oci_api_key'):
                user_ocid = creds.get('user_ocid')
                tenancy_ocid = creds.get('tenancy_ocid') or creds.get('tenancy_id')
                fingerprint = creds.get('fingerprint')
                private_key = creds.get('private_key')
                region = creds.get('region', 'us-ashburn-1')

                if not self.tenancy_id:
                    self.tenancy_id = tenancy_ocid

                self.oci_config = {
                    'user': user_ocid,
                    'key_content': private_key,
                    'fingerprint': fingerprint,
                    'tenancy': tenancy_ocid,
                    'region': region,
                }

                self.signer = oci.signer.Signer(
                    tenancy=tenancy_ocid,
                    user=user_ocid,
                    fingerprint=fingerprint,
                    private_key_content=private_key,
                )

                logger.info("OCI authentication successful (API Key)")

            elif cred_type == 'instance_principal':
                from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.oci_config = {}
                logger.info("OCI authentication successful (Instance Principal)")

            else:
                raise AuthenticationError(f"Unsupported OCI credential type: {cred_type}")

            return self.signer

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"OCI authentication failed: {e}")
            raise AuthenticationError(f"OCI authentication failed: {e}")

    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute OCI service discovery via registered handler."""
        handler = OCI_SERVICE_HANDLERS.get(service)
        if not handler:
            logger.warning(f"No OCI handler registered for service: {service}")
            return ([], {'service': service, 'status': 'no_handler'})

        # Update config region for this scan
        scan_config = dict(self.oci_config) if self.oci_config else {}
        scan_config['region'] = region

        loop = asyncio.get_event_loop()
        try:
            discoveries = await loop.run_in_executor(
                _OCI_EXECUTOR,
                handler,
                scan_config,        # OCI config dict
                self.signer,         # OCI signer
                self.tenancy_id,     # compartment/tenancy ID
                region,
                config
            )
            metadata = {
                'service': service,
                'region': region,
                'resources_found': len(discoveries),
                'status': 'completed'
            }
            return (discoveries, metadata)
        except Exception as e:
            logger.error(f"OCI {service}/{region} scan failed: {e}")
            return ([], {'service': service, 'status': 'error', 'error': str(e)})

    def get_client(self, service: str, region: str) -> Any:
        """Get OCI SDK client for specific service."""
        import oci
        config = dict(self.oci_config) if self.oci_config else {}
        config['region'] = region
        client_map = {
            'compute': oci.core.ComputeClient,
            'database': oci.database.DatabaseClient,
            'object_storage': oci.object_storage.ObjectStorageClient,
            'audit': oci.audit.AuditClient,
        }
        client_class = client_map.get(service)
        if not client_class:
            raise DiscoveryError(f"No OCI client mapping for service: {service}")
        return client_class(config, signer=self.signer)

    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None
    ) -> Dict[str, str]:
        """Extract resource identifiers from OCI response (OCID-based)."""
        ocid = item.get('id', '')
        resource_name = item.get('display_name', item.get('name', ''))
        return {
            'resource_arn': ocid,
            'resource_id': ocid,
            'resource_name': resource_name,
            'resource_uid': ocid,
            'resource_type': resource_type or item.get('resource_type', ''),
        }

    def get_service_client_name(self, service: str) -> str:
        """Map service name to OCI SDK client name."""
        return f"oci.{service}"

    async def list_available_regions(self) -> List[str]:
        """Dynamically list OCI regions; falls back to defaults."""
        try:
            import oci
            identity_client = oci.identity.IdentityClient(
                self.oci_config, signer=self.signer
            )
            regions = identity_client.list_regions().data
            return [r.name for r in regions]
        except Exception as e:
            logger.warning(f"Failed to list OCI regions: {e}; using defaults")
            return DEFAULT_OCI_REGIONS

    def get_account_id(self) -> str:
        """Return OCI tenancy OCID."""
        return self.tenancy_id or ''
