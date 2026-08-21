"""Azure Architecture Builder — VNet/Subnet hierarchy."""
from .aws_builder import AWSArchitectureBuilder

_VNET_TYPES = {"network.virtualNetworks", "network.virtual-network", "vnet.vnet"}
_SUBNET_TYPES = {"network.subnets", "network.subnet"}


class AzureArchitectureBuilder(AWSArchitectureBuilder):
    """Azure builder — reuses AWS logic with Azure type mappings."""

    def _is_vpc_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _VNET_TYPES or "virtualnetwork" in resource_type.lower()

    def _is_subnet_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _SUBNET_TYPES
