"""GCP Architecture Builder — VPC/Subnetwork hierarchy."""
from .aws_builder import AWSArchitectureBuilder

_VPC_TYPES = {"compute.networks"}
_SUBNET_TYPES = {"compute.subnetworks"}


class GCPArchitectureBuilder(AWSArchitectureBuilder):
    """GCP builder — reuses AWS logic with GCP type mappings."""

    def _is_vpc_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _VPC_TYPES

    def _is_subnet_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _SUBNET_TYPES
