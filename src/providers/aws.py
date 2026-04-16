"""AWS resource provider using boto3."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AWSProvider:
    """Fetch AWS resources for policy evaluation."""

    def fetch_resources(self, region: str | None = None) -> list[dict[str, Any]]:
        """Fetch resources from AWS using boto3."""
        try:
            import boto3
        except ImportError:
            logger.warning("boto3 not installed - returning empty resource list")
            return []

        resources: list[dict[str, Any]] = []
        session = boto3.Session(region_name=region or "us-east-1")

        resources.extend(self._fetch_ec2_instances(session))
        resources.extend(self._fetch_s3_buckets(session))
        resources.extend(self._fetch_rds_instances(session))
        resources.extend(self._fetch_ebs_volumes(session))
        resources.extend(self._fetch_security_groups(session))

        return resources

    def _fetch_ec2_instances(self, session: Any) -> list[dict[str, Any]]:
        try:
            ec2 = session.client("ec2")
            resp = ec2.describe_instances()
            resources = []
            for reservation in resp.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                    resources.append({
                        "resource_id": inst["InstanceId"],
                        "resource_type": "ec2_instance",
                        "provider": "aws",
                        "region": session.region_name,
                        "state": inst.get("State", {}).get("Name"),
                        "instance_type": inst.get("InstanceType"),
                        "tags": tags,
                        "launch_time": str(inst.get("LaunchTime", "")),
                        "monitoring": inst.get("Monitoring", {}).get("State"),
                        "ebs_optimized": inst.get("EbsOptimized", False),
                    })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch EC2 instances: {e}")
            return []

    def _fetch_s3_buckets(self, session: Any) -> list[dict[str, Any]]:
        try:
            s3 = session.client("s3")
            resp = s3.list_buckets()
            resources = []
            for bucket in resp.get("Buckets", []):
                name = bucket["Name"]
                encryption = self._get_bucket_encryption(s3, name)
                public_access = self._get_bucket_public_access(s3, name)
                versioning = self._get_bucket_versioning(s3, name)
                resources.append({
                    "resource_id": name,
                    "resource_type": "s3_bucket",
                    "provider": "aws",
                    "region": "global",
                    "encryption_enabled": encryption,
                    "public_access_blocked": public_access,
                    "versioning_enabled": versioning,
                    "tags": {},
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch S3 buckets: {e}")
            return []

    def _get_bucket_encryption(self, s3: Any, bucket: str) -> bool:
        try:
            s3.get_bucket_encryption(Bucket=bucket)
            return True
        except Exception:
            return False

    def _get_bucket_public_access(self, s3: Any, bucket: str) -> bool:
        try:
            resp = s3.get_public_access_block(Bucket=bucket)
            config = resp.get("PublicAccessBlockConfiguration", {})
            return all([
                config.get("BlockPublicAcls", False),
                config.get("IgnorePublicAcls", False),
                config.get("BlockPublicPolicy", False),
                config.get("RestrictPublicBuckets", False),
            ])
        except Exception:
            return False

    def _get_bucket_versioning(self, s3: Any, bucket: str) -> bool:
        try:
            resp = s3.get_bucket_versioning(Bucket=bucket)
            return resp.get("Status") == "Enabled"
        except Exception:
            return False

    def _fetch_rds_instances(self, session: Any) -> list[dict[str, Any]]:
        try:
            rds = session.client("rds")
            resp = rds.describe_db_instances()
            resources = []
            for db in resp.get("DBInstances", []):
                resources.append({
                    "resource_id": db["DBInstanceIdentifier"],
                    "resource_type": "rds_instance",
                    "provider": "aws",
                    "region": session.region_name,
                    "engine": db.get("Engine"),
                    "instance_class": db.get("DBInstanceClass"),
                    "storage_encrypted": db.get("StorageEncrypted", False),
                    "multi_az": db.get("MultiAZ", False),
                    "publicly_accessible": db.get("PubliclyAccessible", False),
                    "auto_minor_version_upgrade": db.get("AutoMinorVersionUpgrade", False),
                    "backup_retention_period": db.get("BackupRetentionPeriod", 0),
                    "tags": {},
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch RDS instances: {e}")
            return []

    def _fetch_ebs_volumes(self, session: Any) -> list[dict[str, Any]]:
        try:
            ec2 = session.client("ec2")
            resp = ec2.describe_volumes()
            resources = []
            for vol in resp.get("Volumes", []):
                tags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
                resources.append({
                    "resource_id": vol["VolumeId"],
                    "resource_type": "ebs_volume",
                    "provider": "aws",
                    "region": session.region_name,
                    "state": vol.get("State"),
                    "size_gb": vol.get("Size", 0),
                    "volume_type": vol.get("VolumeType"),
                    "encrypted": vol.get("Encrypted", False),
                    "attachments": len(vol.get("Attachments", [])),
                    "tags": tags,
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch EBS volumes: {e}")
            return []

    def _fetch_security_groups(self, session: Any) -> list[dict[str, Any]]:
        try:
            ec2 = session.client("ec2")
            resp = ec2.describe_security_groups()
            resources = []
            for sg in resp.get("SecurityGroups", []):
                open_to_world = any(
                    any(
                        ip_range.get("CidrIp") == "0.0.0.0/0"
                        for ip_range in rule.get("IpRanges", [])
                    )
                    for rule in sg.get("IpPermissions", [])
                )
                resources.append({
                    "resource_id": sg["GroupId"],
                    "resource_type": "security_group",
                    "provider": "aws",
                    "region": session.region_name,
                    "group_name": sg.get("GroupName"),
                    "description": sg.get("Description"),
                    "open_to_world": open_to_world,
                    "inbound_rules_count": len(sg.get("IpPermissions", [])),
                    "outbound_rules_count": len(sg.get("IpPermissionsEgress", [])),
                    "tags": {},
                })
            return resources
        except Exception as e:
            logger.error(f"Failed to fetch security groups: {e}")
            return []
