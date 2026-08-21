"""
Kubernetes Discovery Scanner

Implements Kubernetes-specific discovery using handler registry pattern.
Each K8s resource type is a handler registered via @k8s_handler decorator.

K8s is unique: no region concept, uses in-cluster auth or kubeconfig,
discovers K8s API objects (pods, deployments, services, etc.).
"""

from typing import Dict, List, Any, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
import asyncio
import logging

from providers.common.models.provider_interface import DiscoveryScanner, AuthenticationError, DiscoveryError

logger = logging.getLogger(__name__)

# Thread pool for blocking K8s SDK calls
_K8S_EXECUTOR = ThreadPoolExecutor(max_workers=10)

# K8s has no regions — uses a single pseudo-region
DEFAULT_K8S_REGIONS = ['cluster']

# ─── Service Handler Registry ──────────────────────────────────────
K8S_SERVICE_HANDLERS: Dict[str, Callable] = {}


def k8s_handler(service_name: str):
    """Decorator to register a K8s resource discovery handler."""
    def decorator(fn: Callable):
        K8S_SERVICE_HANDLERS[service_name] = fn
        return fn
    return decorator


# ─── Resource Serialization Helper ─────────────────────────────────

def _serialize_k8s_object(obj) -> Dict:
    """Convert K8s SDK model object to a JSON-serializable dict.

    K8s Python client returns V1-prefixed model objects (V1Pod, V1Deployment).
    Use the API client sanitizer to convert to plain dicts.
    """
    from kubernetes import client
    return client.ApiClient().sanitize_for_serialization(obj)


def _enrich_k8s_item(item: Dict) -> Dict:
    """Inject standard resource identifier fields used by database_manager.

    K8s uses namespace/kind/name as logical identifier and uid as unique ID.
    """
    metadata = item.get('metadata', {}) or {}
    uid = metadata.get('uid', '')
    name = metadata.get('name', '')
    namespace = metadata.get('namespace', 'cluster')
    kind = item.get('kind', item.get('resource_type', 'Unknown')).lower()

    resource_path = f"{namespace}/{kind}/{name}"

    item['resource_arn'] = resource_path
    item['resource_id'] = uid
    item['resource_uid'] = uid

    # Build _raw_response (everything except internal/metadata fields)
    item['_raw_response'] = {k: v for k, v in item.items()
                             if not k.startswith('_') and k not in (
                                 'resource_arn', 'resource_uid', 'resource_id', 'resource_type')}
    return item


# ─── Service Handlers ───────────────────────────────────────────────

@k8s_handler('namespace')
def _scan_namespaces(core_v1, apps_v1, cluster_name: str, region: str, config: Dict) -> List[Dict]:
    """Discover all Kubernetes namespaces (cluster-scoped)."""
    resources = []
    try:
        ns_list = core_v1.list_namespace()
        for ns in ns_list.items:
            item = _serialize_k8s_object(ns)
            item['kind'] = 'Namespace'
            item['resource_type'] = 'k8s.core/Namespace'
            item['_discovery_id'] = 'k8s.core.list_namespace'
            resources.append(_enrich_k8s_item(item))
    except Exception as e:
        logger.warning(f"K8s list_namespace failed: {e}")
    logger.info(f"  namespace: {len(resources)} namespaces found")
    return resources


@k8s_handler('pod')
def _scan_pods(core_v1, apps_v1, cluster_name: str, region: str, config: Dict) -> List[Dict]:
    """Discover all Kubernetes pods across namespaces."""
    resources = []
    try:
        pod_list = core_v1.list_pod_for_all_namespaces()
        for pod in pod_list.items:
            item = _serialize_k8s_object(pod)
            item['kind'] = 'Pod'
            item['resource_type'] = 'k8s.core/Pod'
            item['_discovery_id'] = 'k8s.core.list_pod_for_all_namespaces'
            resources.append(_enrich_k8s_item(item))
    except Exception as e:
        logger.warning(f"K8s list_pod_for_all_namespaces failed: {e}")
    logger.info(f"  pod: {len(resources)} pods found")
    return resources


@k8s_handler('deployment')
def _scan_deployments(core_v1, apps_v1, cluster_name: str, region: str, config: Dict) -> List[Dict]:
    """Discover all Kubernetes deployments across namespaces."""
    resources = []
    try:
        dep_list = apps_v1.list_deployment_for_all_namespaces()
        for dep in dep_list.items:
            item = _serialize_k8s_object(dep)
            item['kind'] = 'Deployment'
            item['resource_type'] = 'k8s.apps/Deployment'
            item['_discovery_id'] = 'k8s.apps.list_deployment_for_all_namespaces'
            resources.append(_enrich_k8s_item(item))
    except Exception as e:
        logger.warning(f"K8s list_deployment_for_all_namespaces failed: {e}")
    logger.info(f"  deployment: {len(resources)} deployments found")
    return resources


@k8s_handler('service')
def _scan_services(core_v1, apps_v1, cluster_name: str, region: str, config: Dict) -> List[Dict]:
    """Discover all Kubernetes services across namespaces."""
    resources = []
    try:
        svc_list = core_v1.list_service_for_all_namespaces()
        for svc in svc_list.items:
            item = _serialize_k8s_object(svc)
            item['kind'] = 'Service'
            item['resource_type'] = 'k8s.core/Service'
            item['_discovery_id'] = 'k8s.core.list_service_for_all_namespaces'
            resources.append(_enrich_k8s_item(item))
    except Exception as e:
        logger.warning(f"K8s list_service_for_all_namespaces failed: {e}")
    logger.info(f"  service: {len(resources)} services found")
    return resources


# ─── Scanner Class ──────────────────────────────────────────────────

class K8sDiscoveryScanner(DiscoveryScanner):
    """
    Kubernetes-specific discovery scanner implementation.

    Uses handler registry pattern: K8S_SERVICE_HANDLERS maps resource types
    to handler functions. Add new resources by decorating with @k8s_handler.

    K8s is unique:
    - No region concept (single pseudo-region 'cluster')
    - Authentication via in-cluster config or kubeconfig
    - Discovers K8s API objects, not cloud resources
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        super().__init__(credentials, **kwargs)
        self.core_v1 = None
        self.apps_v1 = None
        self.cluster_name = (
            credentials.get('cluster_name')
            or credentials.get('account_id')
            or 'unknown-cluster'
        )

    def authenticate(self) -> Any:
        """
        Authenticate to Kubernetes cluster.

        Supports:
        - in_cluster: Use service account mounted in pod (self-scan)
        - kubeconfig: Use kubeconfig content from credentials
        - Default: Try in-cluster first, then fall back to kubeconfig
        """
        try:
            from kubernetes import client, config as k8s_config
            import yaml

            cred_type = self.credentials.get('credential_type', '').lower()

            if cred_type in ('in_cluster', 'k8s_in_cluster'):
                k8s_config.load_incluster_config()
                logger.info("K8s authentication successful (in-cluster)")

            elif cred_type in ('kubeconfig', 'k8s_kubeconfig'):
                kubeconfig_data = self.credentials.get('kubeconfig')
                if kubeconfig_data:
                    k8s_config.load_kube_config_from_dict(yaml.safe_load(kubeconfig_data))
                else:
                    k8s_config.load_kube_config()
                logger.info("K8s authentication successful (kubeconfig)")

            else:
                # Default: try in-cluster first, fall back to kubeconfig
                try:
                    k8s_config.load_incluster_config()
                    logger.info("K8s authentication successful (auto: in-cluster)")
                except k8s_config.ConfigException:
                    k8s_config.load_kube_config()
                    logger.info("K8s authentication successful (auto: kubeconfig)")

            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()

            return self.core_v1

        except Exception as e:
            logger.error(f"K8s authentication failed: {e}")
            raise AuthenticationError(f"K8s authentication failed: {e}")

    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute K8s resource discovery via registered handler."""
        handler = K8S_SERVICE_HANDLERS.get(service)
        if not handler:
            logger.warning(f"No K8s handler registered for service: {service}")
            return ([], {'service': service, 'status': 'no_handler'})

        loop = asyncio.get_event_loop()
        try:
            discoveries = await loop.run_in_executor(
                _K8S_EXECUTOR,
                handler,
                self.core_v1,        # CoreV1Api client
                self.apps_v1,        # AppsV1Api client
                self.cluster_name,   # Cluster name
                region,              # Ignored for K8s (always 'cluster')
                config
            )
            metadata = {
                'service': service,
                'region': 'cluster',
                'resources_found': len(discoveries),
                'status': 'completed'
            }
            return (discoveries, metadata)
        except Exception as e:
            logger.error(f"K8s {service} scan failed: {e}")
            return ([], {'service': service, 'status': 'error', 'error': str(e)})

    def get_client(self, service: str, region: str) -> Any:
        """Get K8s API client."""
        if service in ('namespace', 'pod', 'service'):
            return self.core_v1
        elif service in ('deployment',):
            return self.apps_v1
        return self.core_v1

    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None
    ) -> Dict[str, str]:
        """Extract resource identifiers from K8s response."""
        metadata = item.get('metadata', {}) or {}
        uid = metadata.get('uid', '')
        name = metadata.get('name', '')
        namespace = metadata.get('namespace', 'cluster')
        kind = item.get('kind', service).lower()

        return {
            'resource_arn': f"{namespace}/{kind}/{name}",
            'resource_id': uid,
            'resource_name': name,
            'resource_uid': uid,
            'resource_type': resource_type or item.get('resource_type', f'k8s/{kind}'),
        }

    def get_service_client_name(self, service: str) -> str:
        """Map service name to K8s API group."""
        return f"k8s.{service}"

    async def list_available_regions(self) -> List[str]:
        """K8s has no regions — return single pseudo-region."""
        return DEFAULT_K8S_REGIONS

    def get_account_id(self) -> str:
        """Return cluster name as account ID."""
        return self.cluster_name
