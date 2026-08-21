"""OCI Architecture Builder — VCN/Subnet hierarchy."""
from .aws_builder import AWSArchitectureBuilder

_VCN_TYPES = {"core.vcn"}
_SUBNET_TYPES = {"core.subnet"}


class OCIArchitectureBuilder(AWSArchitectureBuilder):
    """OCI builder — reuses AWS logic with OCI type mappings."""

    def _is_vpc_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _VCN_TYPES or "vcn" in resource_type.lower()

    def _is_subnet_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _SUBNET_TYPES
