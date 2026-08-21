"""
IBM Cloud Discovery Scanner

Implements IBM Cloud-specific discovery using handler registry pattern.
Each service handler is a simple function registered via @ibm_handler decorator.
"""

from typing import Dict, List, Any, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
import asyncio
import logging

from providers.common.models.provider_interface import DiscoveryScanner, AuthenticationError, DiscoveryError

logger = logging.getLogger(__name__)

# Thread pool for blocking IBM SDK calls
_IBM_EXECUTOR = ThreadPoolExecutor(max_workers=10)

DEFAULT_IBM_REGIONS = [
    'us-south', 'us-east', 'eu-gb', 'eu-de',
    'au-syd', 'jp-tok', 'jp-osa', 'ca-tor', 'br-sao',
]

# ─── Service Handler Registry ──────────────────────────────────────
IBM_SERVICE_HANDLERS: Dict[str, Callable] = {}


def ibm_handler(service_name: str):
    """Decorator to register an IBM Cloud service discovery handler."""
    def decorator(fn: Callable):
        IBM_SERVICE_HANDLERS[service_name] = fn
        return fn
    return decorator


# ─── Resource Identifier Helper ────────────────────────────────────

def _enrich_ibm_item(item: Dict) -> Dict:
    """Inject standard resource identifier fields used by database_manager.

    IBM Cloud uses CRN (Cloud Resource Name) as primary identifier.
    Maps CRN → resource_arn/resource_uid/resource_id.
    """
    crn = item.get('crn', item.get('id', ''))
    item['resource_arn'] = crn       # CRN as ARN equivalent
    item['resource_id'] = item.get('id', crn)
    item['resource_uid'] = crn or item.get('id', '')

    # Build _raw_response (everything except internal/metadata fields)
    item['_raw_response'] = {k: v for k, v in item.items()
                             if not k.startswith('_') and k not in (
                                 'resource_arn', 'resource_uid', 'resource_id', 'resource_type')}
    return item


# ─── Service Handlers ───────────────────────────────────────────────

@ibm_handler('iam')
def _scan_iam(authenticator, account_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover IBM IAM service IDs and API keys (global)."""
    from ibm_platform_services import IamIdentityV1

    iam_client = IamIdentityV1(authenticator=authenticator)

    resources = []

    # List service IDs
    try:
        response = iam_client.list_service_ids(
            account_id=account_id,
        ).get_result()
        for sid in response.get('serviceids', []):
            item = {
                'id': sid.get('id', ''),
                'iam_id': sid.get('iam_id', ''),
                'name': sid.get('name', ''),
                'description': sid.get('description', ''),
                'crn': sid.get('crn', ''),
                'account_id': sid.get('account_id', ''),
                'created_at': sid.get('created_at', ''),
                'modified_at': sid.get('modified_at', ''),
                'locked': sid.get('locked', False),
                'resource_type': 'ibm.iam/ServiceId',
                '_discovery_id': 'ibm.iam.list_service_ids',
            }
            resources.append(_enrich_ibm_item(item))
    except Exception as e:
        logger.warning(f"IBM IAM list_service_ids failed: {e}")

    # List API keys
    try:
        response = iam_client.list_api_keys(
            account_id=account_id,
        ).get_result()
        for key in response.get('apikeys', []):
            item = {
                'id': key.get('id', ''),
                'name': key.get('name', ''),
                'description': key.get('description', ''),
                'crn': key.get('crn', ''),
                'account_id': key.get('account_id', ''),
                'iam_id': key.get('iam_id', ''),
                'entity_tag': key.get('entity_tag', ''),
                'created_at': key.get('created_at', ''),
                'locked': key.get('locked', False),
                'resource_type': 'ibm.iam/ApiKey',
                '_discovery_id': 'ibm.iam.list_api_keys',
            }
            resources.append(_enrich_ibm_item(item))
    except Exception as e:
        logger.warning(f"IBM IAM list_api_keys failed: {e}")

    logger.info(f"  iam: {len(resources)} IAM resources found")
    return resources


@ibm_handler('vpc')
def _scan_vpc(authenticator, account_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover IBM VPC instances (regional — per-region URL)."""
    from ibm_vpc import VpcV1

    # IBM VPC requires per-region service URL
    service_url = f"https://{region}.iaas.cloud.ibm.com/v1"
    vpc_client = VpcV1(authenticator=authenticator)
    vpc_client.set_service_url(service_url)

    resources = []
    try:
        response = vpc_client.list_instances().get_result()
        for instance in response.get('instances', []):
            item = {
                'id': instance.get('id', ''),
                'name': instance.get('name', ''),
                'crn': instance.get('crn', ''),
                'status': instance.get('status', ''),
                'profile': instance.get('profile', {}).get('name', ''),
                'zone': instance.get('zone', {}).get('name', ''),
                'vpc': instance.get('vpc', {}).get('name', ''),
                'created_at': instance.get('created_at', ''),
                'memory': instance.get('memory', None),
                'vcpu': instance.get('vcpu', {}).get('count', None),
                'image': instance.get('image', {}).get('name', ''),
                'bandwidth': instance.get('bandwidth', None),
                'resource_type': 'ibm.vpc/Instance',
                '_discovery_id': 'ibm.vpc.list_instances',
            }
            resources.append(_enrich_ibm_item(item))
    except Exception as e:
        logger.warning(f"IBM VPC list_instances ({region}) failed: {e}")
    logger.info(f"  vpc/{region}: {len(resources)} instances found")
    return resources


@ibm_handler('code_engine')
def _scan_code_engine(authenticator, account_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover IBM Code Engine projects (global)."""
    resources = []
    try:
        from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2

        ce_client = CodeEngineV2(authenticator=authenticator)
        response = ce_client.list_projects().get_result()
        for project in response.get('projects', []):
            item = {
                'id': project.get('id', ''),
                'name': project.get('name', ''),
                'crn': project.get('crn', ''),
                'status': project.get('status', ''),
                'account_id': project.get('account_id', ''),
                'region': project.get('region', ''),
                'created_at': project.get('created_at', ''),
                'resource_group_id': project.get('resource_group_id', ''),
                'resource_type': 'ibm.codeengine/Project',
                '_discovery_id': 'ibm.code_engine.list_projects',
            }
            resources.append(_enrich_ibm_item(item))
    except ImportError:
        logger.warning("IBM Code Engine SDK not available")
    except Exception as e:
        logger.warning(f"IBM Code Engine list_projects failed: {e}")
    logger.info(f"  code_engine: {len(resources)} projects found")
    return resources


@ibm_handler('object_storage')
def _scan_object_storage(authenticator, account_id: str, region: str, config: Dict) -> List[Dict]:
    """Discover IBM Cloud Object Storage buckets (global, S3-compatible)."""
    resources = []
    try:
        import ibm_boto3
        from ibm_botocore.client import Config as IBMConfig

        # Get IAM token from authenticator for S3-compatible access
        token = authenticator.token_manager.get_token()

        cos_client = ibm_boto3.client(
            's3',
            ibm_api_key_id=getattr(authenticator, 'apikey', None) or '',
            ibm_auth_endpoint='https://iam.cloud.ibm.com/identity/token',
            config=IBMConfig(signature_version='oauth'),
            endpoint_url='https://s3.us.cloud-object-storage.appdomain.cloud'
        )

        response = cos_client.list_buckets()
        for bucket in response.get('Buckets', []):
            item = {
                'id': bucket.get('Name', ''),
                'name': bucket.get('Name', ''),
                'creation_date': str(bucket.get('CreationDate', '')),
                'resource_type': 'ibm.cos/Bucket',
                '_discovery_id': 'ibm.cos.list_buckets',
            }
            resources.append(_enrich_ibm_item(item))
    except ImportError:
        logger.warning("IBM COS SDK (ibm_boto3) not available")
    except Exception as e:
        logger.warning(f"IBM COS list_buckets failed: {e}")
    logger.info(f"  cloud_object_storage: {len(resources)} buckets found")
    return resources


# ─── Scanner Class ──────────────────────────────────────────────────

class IBMDiscoveryScanner(DiscoveryScanner):
    """
    IBM Cloud-specific discovery scanner implementation.

    Uses handler registry pattern: IBM_SERVICE_HANDLERS maps service names
    to handler functions. Add new services by decorating with @ibm_handler.
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        super().__init__(credentials, **kwargs)
        self.authenticator = None
        self.account_id = (
            credentials.get('account_id')
            or credentials.get('account_id')
            or (credentials.get('credentials') or {}).get('account_id')
        )

    def authenticate(self) -> Any:
        """
        Authenticate to IBM Cloud using IAM API Key.

        Supports:
        - ibm_api_key: IAM authenticator with API key
        """
        try:
            from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

            cred_type = self.credentials.get('credential_type', '').lower()

            # Support nested credentials (Secrets Manager wrapper)
            creds = self.credentials
            if 'credentials' in creds and isinstance(creds['credentials'], dict):
                inner = creds['credentials']
                if inner.get('api_key'):
                    creds = {**creds, **inner}

            if cred_type in ('ibm_api_key', 'api_key'):
                api_key = creds.get('api_key')
                if not api_key:
                    raise AuthenticationError("Missing required field: api_key")

                self.authenticator = IAMAuthenticator(api_key=api_key)

                # Try to get account_id from IAM if not provided
                if not self.account_id:
                    try:
                        from ibm_platform_services import IamIdentityV1
                        iam_client = IamIdentityV1(authenticator=self.authenticator)
                        api_key_details = iam_client.get_api_keys_details(
                            iam_api_key=api_key
                        ).get_result()
                        self.account_id = api_key_details.get('account_id', '')
                        logger.info(f"IBM account_id resolved: {self.account_id}")
                    except Exception as e:
                        logger.warning(f"Could not resolve IBM account_id: {e}")

                logger.info("IBM Cloud authentication successful (API Key)")

            else:
                raise AuthenticationError(f"Unsupported IBM credential type: {cred_type}")

            return self.authenticator

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"IBM Cloud authentication failed: {e}")
            raise AuthenticationError(f"IBM Cloud authentication failed: {e}")

    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute IBM Cloud service discovery via registered handler."""
        handler = IBM_SERVICE_HANDLERS.get(service)
        if not handler:
            logger.warning(f"No IBM handler registered for service: {service}")
            return ([], {'service': service, 'status': 'no_handler'})

        loop = asyncio.get_event_loop()
        try:
            discoveries = await loop.run_in_executor(
                _IBM_EXECUTOR,
                handler,
                self.authenticator,   # IBM IAM authenticator
                self.account_id,      # IBM account ID
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
            logger.error(f"IBM {service}/{region} scan failed: {e}")
            return ([], {'service': service, 'status': 'error', 'error': str(e)})

    def get_client(self, service: str, region: str) -> Any:
        """Get IBM Cloud SDK client for specific service."""
        raise NotImplementedError("Use IBM_SERVICE_HANDLERS for service-specific clients")

    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None
    ) -> Dict[str, str]:
        """Extract resource identifiers from IBM response (CRN-based)."""
        crn = item.get('crn', item.get('id', ''))
        resource_name = item.get('name', '')
        return {
            'resource_arn': crn,
            'resource_id': item.get('id', crn),
            'resource_name': resource_name,
            'resource_uid': crn,
            'resource_type': resource_type or item.get('resource_type', ''),
        }

    def get_service_client_name(self, service: str) -> str:
        """Map service name to IBM SDK client name."""
        return f"ibm.{service}"

    async def list_available_regions(self) -> List[str]:
        """Return default IBM Cloud regions."""
        return DEFAULT_IBM_REGIONS

    def get_account_id(self) -> str:
        """Return IBM Cloud account ID."""
        return self.account_id or ''
