"""
fetch_real_assets.py — Standalone AWS Asset Fetcher

Fetches real resources from your AWS account using boto3 and writes them
to a JSON file in cspm_asset.v1 format — the same schema the FinOps engine
expects from the Inventory Engine.

No database, no K8s, no extra services needed.

Usage:
    # Set credentials first:
    export AWS_ACCESS_KEY_ID=AKIA...
    export AWS_SECRET_ACCESS_KEY=your-secret-key
    export AWS_DEFAULT_REGION=us-east-1

    # Then run:
    python3 fetch_real_assets.py --account-id YOUR_ACCOUNT_ID

    # Scope to specific regions:
    python3 fetch_real_assets.py --account-id YOUR_ACCOUNT_ID --regions us-east-1 ap-south-1

    # Output to custom file:
    python3 fetch_real_assets.py --account-id YOUR_ACCOUNT_ID --output my_assets.json

Output:
    assets.json — list of assets in cspm_asset.v1 format
    (consumed by FinOps engine when USE_FILE_INVENTORY=true)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("fetch_real_assets")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tags_list_to_dict(tags: Optional[List[Dict]]) -> Dict[str, str]:
    """Convert AWS Tags format [{Key, Value}] → {key: value}."""
    if not tags:
        return {}
    return {t.get("Key", ""): t.get("Value", "") for t in tags if t.get("Key")}


def _get_regions(session: boto3.Session, requested: Optional[List[str]]) -> List[str]:
    """Return the list of regions to scan."""
    if requested:
        return requested
    try:
        ec2 = session.client("ec2", region_name="us-east-1")
        resp = ec2.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])
        return [r["RegionName"] for r in resp.get("Regions", [])]
    except Exception as e:
        logger.warning("Could not list regions, falling back to us-east-1: %s", e)
        return ["us-east-1"]


def _get_account_id(session: boto3.Session) -> str:
    """Get the AWS account ID via STS."""
    try:
        sts = session.client("sts")
        return sts.get_caller_identity()["Account"]
    except Exception as e:
        raise RuntimeError(f"Cannot get AWS account ID: {e}") from e


# ── EC2 Instances ─────────────────────────────────────────────────────────────

def fetch_ec2_instances(session: boto3.Session, account_id: str, region: str) -> List[Dict[str, Any]]:
    """Fetch all EC2 instances in a region."""
    assets = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    instance_id = inst.get("InstanceId", "")
                    state = inst.get("State", {}).get("Name", "unknown")
                    launch_time = inst.get("LaunchTime")
                    launch_str = launch_time.isoformat() if launch_time else None

                    # CPU utilization — not available from describe_instances.
                    # Would need CloudWatch. We leave it as None here;
                    # the FinOps rules still fire on the resource type match.
                    # To enrich: add CloudWatch call below (see fetch_cpu_utilization).
                    assets.append({
                        "schema_version": "cspm_asset.v1",
                        "provider": "aws",
                        "account_id": account_id,
                        "region": region,
                        "resource_type": "ec2.instance",
                        "resource_id": instance_id,
                        "resource_uid": f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}",
                        "name": _get_name_tag(inst.get("Tags")),
                        "tags": _tags_list_to_dict(inst.get("Tags")),
                        "metadata": {
                            "instance_type": inst.get("InstanceType"),
                            "state": state,
                            "launch_time": launch_str,
                            "platform": inst.get("Platform", "linux"),
                            "architecture": inst.get("Architecture"),
                            "image_id": inst.get("ImageId"),
                            "vpc_id": inst.get("VpcId"),
                            "subnet_id": inst.get("SubnetId"),
                            "private_ip": inst.get("PrivateIpAddress"),
                            "public_ip": inst.get("PublicIpAddress"),
                            "iam_instance_profile": (inst.get("IamInstanceProfile") or {}).get("Arn"),
                            "monitoring_state": (inst.get("Monitoring") or {}).get("State"),
                            "cpu_utilization": None,  # enriched below via CloudWatch
                            "stopped_days": None,      # enriched below if state==stopped
                        },
                    })
        logger.info("EC2 instances | region=%s count=%d", region, len(assets))
    except ClientError as e:
        logger.warning("EC2 describe_instances failed | region=%s error=%s", region, e)
    return assets


def fetch_cpu_utilization(session: boto3.Session, instance_id: str, account_id: str, region: str) -> Optional[float]:
    """Fetch 14-day average CPU utilization for an EC2 instance from CloudWatch."""
    try:
        cw = session.client("cloudwatch", region_name=region)
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=14)
        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=1209600,  # 14 days in seconds
            Statistics=["Average"],
        )
        datapoints = resp.get("Datapoints", [])
        if datapoints:
            return round(datapoints[0].get("Average", 0), 2)
    except Exception:
        pass
    return None


# ── EBS Volumes ───────────────────────────────────────────────────────────────

def fetch_ebs_volumes(session: boto3.Session, account_id: str, region: str) -> List[Dict[str, Any]]:
    """Fetch all EBS volumes in a region."""
    assets = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_volumes")
        for page in paginator.paginate():
            for vol in page.get("Volumes", []):
                vol_id = vol.get("VolumeId", "")
                attachments = vol.get("Attachments", [])
                attached = len(attachments) > 0 and attachments[0].get("State") == "attached"
                assets.append({
                    "schema_version": "cspm_asset.v1",
                    "provider": "aws",
                    "account_id": account_id,
                    "region": region,
                    "resource_type": "ec2.volume",
                    "resource_id": vol_id,
                    "resource_uid": f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}",
                    "name": _get_name_tag(vol.get("Tags")),
                    "tags": _tags_list_to_dict(vol.get("Tags")),
                    "metadata": {
                        "size_gb": vol.get("Size"),
                        "volume_type": vol.get("VolumeType"),
                        "state": vol.get("State"),
                        "attached": attached,
                        "iops": vol.get("Iops"),
                        "encrypted": vol.get("Encrypted"),
                        "availability_zone": vol.get("AvailabilityZone"),
                        "create_time": vol.get("CreateTime", "").isoformat() if vol.get("CreateTime") else None,
                        "attached_to": attachments[0].get("InstanceId") if attached else None,
                    },
                })
        logger.info("EBS volumes | region=%s count=%d", region, len(assets))
    except ClientError as e:
        logger.warning("EBS describe_volumes failed | region=%s error=%s", region, e)
    return assets


# ── EBS Snapshots ─────────────────────────────────────────────────────────────

def fetch_ebs_snapshots(session: boto3.Session, account_id: str, region: str) -> List[Dict[str, Any]]:
    """Fetch all owned EBS snapshots in a region."""
    assets = []
    try:
        ec2 = session.client("ec2", region_name=region)

        # Snapshots referenced by an AMI are excluded from stale-snapshot findings
        ami_by_snapshot: Dict[str, str] = {}
        try:
            for image in ec2.describe_images(Owners=["self"]).get("Images", []):
                for bdm in image.get("BlockDeviceMappings", []):
                    snap_ref = (bdm.get("Ebs") or {}).get("SnapshotId")
                    if snap_ref:
                        ami_by_snapshot[snap_ref] = image.get("ImageId")
        except ClientError as e:
            logger.warning("describe_images failed | region=%s error=%s", region, e)

        now = datetime.now(timezone.utc)
        paginator = ec2.get_paginator("describe_snapshots")
        for page in paginator.paginate(OwnerIds=["self"]):
            for snap in page.get("Snapshots", []):
                snap_id = snap.get("SnapshotId", "")
                start_time = snap.get("StartTime")
                assets.append({
                    "schema_version": "cspm_asset.v1",
                    "provider": "aws",
                    "account_id": account_id,
                    "region": region,
                    "resource_type": "ec2.snapshot",
                    "resource_id": snap_id,
                    "resource_uid": f"arn:aws:ec2:{region}:{account_id}:snapshot/{snap_id}",
                    "name": _get_name_tag(snap.get("Tags")),
                    "tags": _tags_list_to_dict(snap.get("Tags")),
                    "metadata": {
                        "volume_id": snap.get("VolumeId"),
                        "volume_size_gb": snap.get("VolumeSize"),
                        "size_gb": snap.get("VolumeSize"),
                        "state": snap.get("State"),
                        "description": snap.get("Description"),
                        "encrypted": snap.get("Encrypted"),
                        "start_time": start_time.isoformat() if start_time else None,
                        "age_days": (now - start_time).days if start_time else None,
                        "ami_id": ami_by_snapshot.get(snap_id),
                    },
                })
        logger.info("EBS snapshots | region=%s count=%d", region, len(assets))
    except ClientError as e:
        logger.warning("EBS describe_snapshots failed | region=%s error=%s", region, e)
    return assets


# ── Elastic IPs ───────────────────────────────────────────────────────────────

def fetch_elastic_ips(session: boto3.Session, account_id: str, region: str) -> List[Dict[str, Any]]:
    """Fetch all Elastic IPs in a region."""
    assets = []
    try:
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_addresses()
        for addr in resp.get("Addresses", []):
            alloc_id = addr.get("AllocationId", addr.get("PublicIp", ""))
            public_ip = addr.get("PublicIp", "")
            associated = addr.get("AssociationId") is not None
            assets.append({
                "schema_version": "cspm_asset.v1",
                "provider": "aws",
                "account_id": account_id,
                "region": region,
                "resource_type": "ec2.elastic-ip",
                "resource_id": alloc_id,
                "resource_uid": f"arn:aws:ec2:{region}:{account_id}:elastic-ip/{alloc_id}",
                "name": _get_name_tag(addr.get("Tags")) or public_ip,
                "tags": _tags_list_to_dict(addr.get("Tags")),
                "metadata": {
                    "public_ip": public_ip,
                    "associated": associated,
                    "association_id": addr.get("AssociationId"),
                    "instance_id": addr.get("InstanceId"),
                    "domain": addr.get("Domain"),
                },
            })
        logger.info("Elastic IPs | region=%s count=%d", region, len(assets))
    except ClientError as e:
        logger.warning("Elastic IPs failed | region=%s error=%s", region, e)
    return assets


# ── S3 Buckets (global, fetched once) ─────────────────────────────────────────

def _bucket_size_gb(session: boto3.Session, bucket_name: str, region: str) -> Optional[float]:
    """
    Latest CloudWatch BucketSizeBytes (StandardStorage) in GB, or None.
    The metric is emitted daily, so a 3-day window guarantees a datapoint
    for any non-empty bucket. The CloudWatch client must be in the
    bucket's own region.
    """
    try:
        cw = session.client("cloudwatch", region_name=region)
        resp = cw.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=datetime.now(timezone.utc) - timedelta(days=3),
            EndTime=datetime.now(timezone.utc),
            Period=86400,
            Statistics=["Average"],
        )
        points = resp.get("Datapoints", [])
        if not points:
            return None
        latest = max(points, key=lambda p: p["Timestamp"])
        return round(latest["Average"] / (1024 ** 3), 2)
    except ClientError as e:
        logger.warning("BucketSizeBytes failed | bucket=%s region=%s error=%s", bucket_name, region, e)
        return None


def fetch_s3_buckets(session: boto3.Session, account_id: str) -> List[Dict[str, Any]]:
    """Fetch all S3 buckets (S3 is global — fetched once, not per region)."""
    assets = []
    try:
        s3 = session.client("s3", region_name="us-east-1")
        resp = s3.list_buckets()
        for bucket in resp.get("Buckets", []):
            name = bucket.get("Name", "")

            # Get bucket region (legacy API quirk: null → us-east-1, "EU" → eu-west-1)
            try:
                loc = s3.get_bucket_location(Bucket=name)
                region = loc.get("LocationConstraint") or "us-east-1"
                if region == "EU":
                    region = "eu-west-1"
            except ClientError:
                region = "us-east-1"

            # Get tags
            tags = {}
            try:
                tag_resp = s3.get_bucket_tagging(Bucket=name)
                tags = _tags_list_to_dict(tag_resp.get("TagSet", []))
            except ClientError:
                pass  # NoSuchTagSet is expected for untagged buckets

            # Lifecycle policy exists?
            has_lifecycle = False
            try:
                s3.get_bucket_lifecycle_configuration(Bucket=name)
                has_lifecycle = True
            except ClientError:
                pass

            # Versioning
            versioning = "Disabled"
            try:
                ver = s3.get_bucket_versioning(Bucket=name)
                versioning = ver.get("Status", "Disabled")
            except ClientError:
                pass

            # Intelligent Tiering
            intelligent_tiering = False
            try:
                it = s3.list_bucket_intelligent_tiering_configurations(Bucket=name)
                intelligent_tiering = len(it.get("IntelligentTieringConfigurationList", [])) > 0
            except ClientError:
                pass

            assets.append({
                "schema_version": "cspm_asset.v1",
                "provider": "aws",
                "account_id": account_id,
                "region": region,
                "resource_type": "s3.bucket",
                "resource_id": name,
                "resource_uid": f"arn:aws:s3:::{name}",
                "name": name,
                "tags": tags,
                "metadata": {
                    "lifecycle_policy": has_lifecycle,
                    "versioning": versioning,
                    "intelligent_tiering_enabled": intelligent_tiering,
                    "creation_date": bucket.get("CreationDate", "").isoformat() if bucket.get("CreationDate") else None,
                    "size_gb": _bucket_size_gb(session, name, region),
                    "storage_class": "STANDARD",
                },
            })
        logger.info("S3 buckets | count=%d", len(assets))
    except ClientError as e:
        logger.warning("S3 list_buckets failed: %s", e)
    return assets


# ── CloudWatch CPU enrichment ─────────────────────────────────────────────────

def enrich_ec2_with_cpu(session: boto3.Session, assets: List[Dict[str, Any]], region: str) -> None:
    """Enrich EC2 instance assets with 14-day average CPU from CloudWatch (in-place)."""
    instance_assets = [a for a in assets if a["resource_type"] == "ec2.instance" and a["region"] == region]
    if not instance_assets:
        return
    logger.info("Fetching CloudWatch CPU for %d instances in %s ...", len(instance_assets), region)
    for asset in instance_assets:
        cpu = fetch_cpu_utilization(session, asset["resource_id"], asset["account_id"], region)
        asset["metadata"]["cpu_utilization"] = cpu


def _get_name_tag(tags: Optional[List[Dict]]) -> str:
    """Extract Name tag value, fallback to empty string."""
    if not tags:
        return ""
    for t in tags:
        if t.get("Key") == "Name":
            return t.get("Value", "")
    return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def fetch_all_assets(
    account_id: str,
    regions: Optional[List[str]] = None,
    enrich_cpu: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch all supported AWS resource types from the given account.
    Returns a flat list of cspm_asset.v1 dicts.
    """
    try:
        session = boto3.Session()
        # Validate credentials early
        actual_account = _get_account_id(session)
        if account_id and actual_account != account_id:
            logger.warning(
                "Account ID mismatch: you passed %s but credentials belong to %s. Using %s.",
                account_id, actual_account, actual_account,
            )
        account_id = actual_account
        logger.info("Connected to AWS account: %s", account_id)
    except RuntimeError as e:
        logger.error("AWS authentication failed: %s", e)
        logger.error("Make sure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set, or ~/.aws/credentials exists.")
        sys.exit(1)
    except NoCredentialsError:
        logger.error("No AWS credentials found. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY or configure ~/.aws/credentials")
        sys.exit(1)

    all_assets: List[Dict[str, Any]] = []

    # S3 is global — fetch once
    logger.info("=== Fetching S3 buckets (global) ===")
    all_assets.extend(fetch_s3_buckets(session, account_id))

    # Get regions to scan
    scan_regions = _get_regions(session, regions)
    logger.info("Scanning %d regions: %s", len(scan_regions), scan_regions)

    for region in scan_regions:
        logger.info("=== Region: %s ===", region)

        regional_assets: List[Dict[str, Any]] = []
        regional_assets.extend(fetch_ec2_instances(session, account_id, region))
        regional_assets.extend(fetch_ebs_volumes(session, account_id, region))
        regional_assets.extend(fetch_ebs_snapshots(session, account_id, region))
        regional_assets.extend(fetch_elastic_ips(session, account_id, region))

        # Enrich EC2 with CloudWatch CPU (optional, takes extra time)
        if enrich_cpu:
            enrich_ec2_with_cpu(session, regional_assets, region)

        all_assets.extend(regional_assets)

    return all_assets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch real AWS assets in cspm_asset.v1 format for FinOps analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--account-id",
        default="",
        help="AWS account ID (auto-detected from credentials if omitted)",
    )
    parser.add_argument(
        "--regions",
        nargs="*",
        metavar="REGION",
        help="Regions to scan (default: all enabled regions). Example: us-east-1 ap-south-1",
    )
    parser.add_argument(
        "--output",
        default="assets.json",
        help="Output file path (default: assets.json)",
    )
    parser.add_argument(
        "--no-cpu",
        action="store_true",
        default=False,
        help="Skip CloudWatch CPU enrichment (faster, but cpu_utilization will be null)",
    )
    args = parser.parse_args()

    assets = fetch_all_assets(
        account_id=args.account_id,
        regions=args.regions,
        enrich_cpu=not args.no_cpu,
    )

    summary = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_assets": len(assets),
        "by_resource_type": {},
    }
    for asset in assets:
        rt = asset["resource_type"]
        summary["by_resource_type"][rt] = summary["by_resource_type"].get(rt, 0) + 1

    output = {"meta": summary, "assets": assets}

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info("=" * 60)
    logger.info("Done! Total assets fetched: %d", len(assets))
    for rt, count in summary["by_resource_type"].items():
        logger.info("  %-35s %d", rt, count)
    logger.info("Output written to: %s", args.output)
    logger.info("=" * 60)
    logger.info("")
    logger.info("Next step — run FinOps engine against these real assets:")
    logger.info("  export USE_FILE_INVENTORY=true")
    logger.info("  export INVENTORY_FILE_PATH=%s", args.output)
    logger.info("  python3 main.py --account-id %s --provider aws --tenant-id my-tenant --no-scan",
                assets[0]["account_id"] if assets else "YOUR_ACCOUNT_ID")


if __name__ == "__main__":
    main()
