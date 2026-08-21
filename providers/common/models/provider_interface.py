"""
Provider Interface for Multi-CSP Discovery Scanners

This module defines the abstract base class that all CSP-specific discovery
scanners must implement (AWS, Azure, GCP, OCI, AliCloud).
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class DiscoveryScanner(ABC):
    """
    Abstract base class for CSP-specific discovery scanners.

    All provider-specific implementations (AWS, Azure, GCP, OCI, AliCloud)
    must inherit from this class and implement all abstract methods.
    """

    def __init__(self, credentials: Dict[str, Any], **kwargs):
        """
        Initialize scanner with provider credentials.

        Args:
            credentials: Provider-specific credentials dictionary
            **kwargs: Additional provider-specific configuration
        """
        self.credentials = credentials
        self.provider = kwargs.get('provider', 'unknown')
        self.session = None  # Will be set by authenticate()

    @abstractmethod
    def authenticate(self) -> Any:
        """
        Authenticate to cloud provider using provided credentials.

        Implementation should:
        - Use self.credentials to establish authenticated session
        - Handle provider-specific auth methods (IAM role, Service Principal, etc.)
        - Store authenticated session in self.session
        - Raise appropriate exceptions on auth failure

        Returns:
            Authenticated client/session object

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def scan_service(
        self,
        service: str,
        region: str,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute service discovery for a specific cloud service.

        Implementation should:
        - Use config['discovery'] array to determine which API calls to make
        - Execute SDK calls for the service
        - Extract resources from API responses
        - Apply filters and pagination as needed
        - Return list of discovered resources

        Args:
            service: Service name (e.g., 'ec2', 'storage', 'vm', 'compute')
            region: Region/location to scan
            config: Discovery configuration from rule_discoveries.discoveries_data
                    Example:
                    {
                        "discovery": [
                            {
                                "action": "list_buckets",
                                "response_field": "Buckets",
                                "params": {}
                            }
                        ]
                    }

        Returns:
            List of discovered resources (dicts with resource metadata)

        Raises:
            DiscoveryError: If discovery fails
        """
        pass

    @abstractmethod
    def get_client(self, service: str, region: str) -> Any:
        """
        Get cloud provider SDK client for specific service and region.

        Implementation should:
        - Map service name to provider-specific client name
        - Handle regional vs global services
        - Return authenticated client instance

        Args:
            service: Service name (e.g., 'ec2', 'storage')
            region: Region/location

        Returns:
            SDK client instance for the service

        Examples:
            AWS: boto3.client('ec2', region_name='us-east-1')
            Azure: ComputeManagementClient(credential, subscription_id)
            GCP: compute_v1.InstancesClient()
            OCI: oci.core.ComputeClient(config)
        """
        pass

    @abstractmethod
    def extract_resource_identifier(
        self,
        item: Dict[str, Any],
        service: str,
        region: str,
        account_id: str,
        resource_type: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Extract or generate resource identifiers (ARN, ID, name).

        Implementation should:
        - Extract resource ARN/ID/name from API response item
        - Generate ARN/ID if not present in response
        - Use provider-specific patterns for generation
        - Return dict with resource_arn, resource_id, resource_name

        Args:
            item: API response item (single resource)
            service: Service name
            region: Region/location
            account_id: Account/subscription/project ID
            resource_type: Optional resource type for multi-resource services

        Returns:
            Dict with extracted identifiers:
            {
                'resource_arn': 'arn:aws:ec2:us-east-1:123456789012:instance/i-123',
                'resource_id': 'i-123',
                'resource_name': 'my-instance'
            }

        Examples:
            AWS: Extract from 'InstanceArn' or generate arn:aws:ec2:{region}:{account}:instance/{id}
            Azure: Extract from 'id' field (/subscriptions/{sub}/resourceGroups/{rg}/...)
            GCP: Extract from 'selfLink' (projects/{project}/zones/{zone}/instances/{name})
            OCI: Extract from 'id' field (ocid1.instance.oc1.{region}.{unique_id})
        """
        pass

    @abstractmethod
    def get_service_client_name(self, service: str) -> str:
        """
        Map service name to provider SDK client name.

        Implementation should:
        - Handle service name aliases (e.g., 'cognito' -> 'cognito-idp')
        - Return SDK-specific client name

        Args:
            service: Service name from rule_discoveries table

        Returns:
            Provider SDK client name

        Examples:
            AWS: 'cognito' -> 'cognito-idp'
            Azure: 'compute' -> 'ComputeManagementClient'
            GCP: 'compute' -> 'compute_v1'
            OCI: 'compute' -> 'ComputeClient'
        """
        pass

    async def list_available_regions(self) -> List[str]:
        """
        Return list of available/enabled regions for this account.

        Override in CSP-specific implementations to dynamically discover regions.
        Default returns empty list, which causes DiscoveryEngine to fall back to
        hardcoded defaults (acceptable for Azure/GCP/OCI for now).

        Returns:
            Sorted list of region name strings, or empty list to trigger fallback
        """
        return []

    def get_account_id(self) -> str:
        """
        Get account/subscription/project ID from authenticated session.

        Optional override for providers that need custom implementation.

        Returns:
            Account identifier string
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_account_id()"
        )


class AuthenticationError(Exception):
    """Raised when cloud provider authentication fails"""
    pass


class DiscoveryError(Exception):
    """Raised when discovery execution fails"""
    pass


class ScannerConfigError(Exception):
    """Raised when scanner configuration is invalid"""
    pass
