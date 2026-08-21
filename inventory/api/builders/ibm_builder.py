"""IBM Cloud Architecture Builder — VPC/Subnet hierarchy."""
from .aws_builder import AWSArchitectureBuilder

_VPC_TYPES = {"vpc.vpc"}
_SUBNET_TYPES = {"vpc.subnet"}


class IBMArchitectureBuilder(AWSArchitectureBuilder):
    """IBM builder — reuses AWS logic with IBM type mappings."""

    def _is_vpc_type(self, resource_type: str) -> bool:
        rt = resource_type.lower()
        return rt in _VPC_TYPES or (rt.startswith("vpc.") and "subnet" not in rt and rt.endswith("vpc"))

    def _is_subnet_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _SUBNET_TYPES
