"""
Generic resource-identifier extraction for discovery records.

Replaces the old `engine/service_scanner.extract_resource_identifier` (the
2,060-line scanner was dropped in the merge; this keeps its one shared
helper). Given one raw discovery item, derive stable identifiers:

    {resource_id, resource_name, resource_type, resource_arn, resource_uid}

Uniform across services: ARN fields are trusted first, then well-known id
fields; the last resort is a synthetic service-level ARN so downstream
engines always get something stable-ish. Callers wrap this in try/except —
prefer returning a weak identifier over raising.
"""
from typing import Any, Dict, Optional

_ARN_FIELDS = (
    "Arn", "ARN", "arn", "ResourceArn", "ResourceARN", "resource_arn",
    "TopicArn", "QueueArn", "FunctionArn", "RoleArn", "PolicyArn",
    "InstanceArn", "ClusterArn", "TaskArn", "LoadBalancerArn", "CertificateArn",
)

# Ordered: more specific id fields first
_ID_FIELDS = (
    "InstanceId", "VolumeId", "SnapshotId", "ImageId", "GroupId", "VpcId",
    "SubnetId", "NetworkInterfaceId", "AllocationId", "NatGatewayId",
    "InternetGatewayId", "RouteTableId", "TransitGatewayId", "DBInstanceIdentifier",
    "DBClusterIdentifier", "FunctionName", "TableName", "QueueUrl", "TopicArn",
    "BucketName", "Name", "KeyId", "UserName", "RoleName", "PolicyName",
    "CertificateId", "ClusterName", "StackId", "Id", "id", "name",
    "resource_id", "ResourceId",
)

_NAME_FIELDS = ("Name", "name", "resource_name", "GroupName", "KeyName", "Title")


def _first(item: Dict[str, Any], fields) -> Optional[str]:
    for field in fields:
        value = item.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _tag_name(item: Dict[str, Any]) -> Optional[str]:
    tags = item.get("Tags") or item.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("Key") == "Name":
                return tag.get("Value")
    if isinstance(tags, dict):
        return tags.get("Name")
    return None


def extract_resource_identifier(
    item: Dict[str, Any],
    service: str,
    region: Optional[str],
    account_id: str,
) -> Dict[str, Optional[str]]:
    """Derive stable identifiers from one raw discovery record."""
    if not isinstance(item, dict):
        item = {}

    resource_arn = _first(item, _ARN_FIELDS)
    resource_id = _first(item, _ID_FIELDS)
    resource_name = _first(item, _NAME_FIELDS) or _tag_name(item) or resource_id

    if resource_arn and not resource_id:
        # Last ARN segment after ':' or '/' is the native id
        tail = resource_arn.split(":")[-1]
        resource_id = tail.split("/")[-1] or tail

    # arn:aws:s3:::bucket → resource_type "bucket"; else infer from id prefix
    resource_type = None
    if resource_arn:
        parts = resource_arn.split(":")
        if len(parts) >= 6:
            rest = parts[5]
            resource_type = rest.split("/")[0] if "/" in rest else (
                parts[6] if len(parts) > 6 else None
            )
    if not resource_type and isinstance(resource_id, str) and "-" in resource_id:
        prefix = resource_id.split("-")[0]
        if prefix.isalpha():
            resource_type = prefix
    resource_type = resource_type or "resource"

    if not resource_arn:
        region_part = "" if region is None else (region or "")
        rid = resource_id or service
        resource_arn = f"arn:aws:{service}:{region_part}:{account_id}:{rid}"

    return {
        "resource_id": resource_id,
        "resource_name": resource_name,
        "resource_type": resource_type,
        "resource_arn": resource_arn,
        "resource_uid": resource_arn,
    }
