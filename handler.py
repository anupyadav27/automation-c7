"""
Lambda handler that runs Cloud Custodian policies on demand
via API Gateway trigger.

Supports 3 levels of execution:
  - group:  {"policy": "ec2"}           → runs all policies in ec2-instances.yml
  - single: {"policy": "ec2-stopped-30d"} → runs ONLY that one policy
  - all:    {"policy": "all"}           → runs everything
  - list:   {"policy": "list"}          → returns available policies
"""

import json
import os
import subprocess
import tempfile
import logging
import yaml
import boto3
from datetime import datetime, timezone
import copy

def _now():
    return datetime.now(timezone.utc)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

POLICY_DIR = os.environ.get("POLICY_DIR", "/app/policies")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
REGION = os.environ.get("C7N_REGION", os.environ.get("AWS_REGION", "us-east-1"))

# ---------------------------------------------------------------
# Policy metadata — drives severity, finding text, recommendation,
# resource ID field, and which AWS fields to surface in the UI.
# ---------------------------------------------------------------
POLICY_META = {
    # EC2 Security
    "sg-open-ssh": {
        "severity": "CRITICAL", "id_field": "GroupId",
        "finding": "Security group allows SSH (port 22) from 0.0.0.0/0",
        "recommendation": "Remove the 0.0.0.0/0 ingress rule on port 22.\nUse SSM Session Manager for shell access instead:\n  aws ssm start-session --target <instance-id>",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "sg-open-rdp": {
        "severity": "CRITICAL", "id_field": "GroupId",
        "finding": "Security group allows RDP (port 3389) from 0.0.0.0/0",
        "recommendation": "Remove the 0.0.0.0/0 ingress rule on port 3389.\nRestrict access to a corporate IP range or use a VPN.",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "sg-all-ports-open": {
        "severity": "CRITICAL", "id_field": "GroupId",
        "finding": "Security group allows ALL traffic from 0.0.0.0/0",
        "recommendation": "Remove the 0.0.0.0/0 all-traffic rule immediately.\nReplace with specific port/source rules for each service.",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "sg-open-database-ports": {
        "severity": "CRITICAL", "id_field": "GroupId",
        "finding": "Security group exposes database port(s) to internet",
        "recommendation": "Remove public ingress rules for ports 3306/5432/1433/27017/6379.\nDatabases must only be accessible from within the VPC.",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "sg-unused": {
        "severity": "LOW", "id_field": "GroupId",
        "finding": "Orphaned security group not attached to any resource",
        "recommendation": "Review and delete if no longer needed:\n  aws ec2 delete-security-group --group-id <GroupId>",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "ec2-no-iam-role": {
        "severity": "HIGH", "id_field": "InstanceId",
        "finding": "EC2 instance running without an IAM instance profile",
        "recommendation": "Attach an IAM role with least-privilege permissions:\n  aws ec2 associate-iam-instance-profile --instance-id <id> --iam-instance-profile Name=<role>",
        "meta": ["InstanceType", "State.Name", "LaunchTime", "PublicIpAddress"],
    },
    "ec2-has-key-pair": {
        "severity": "MEDIUM", "id_field": "InstanceId",
        "finding": "EC2 instance launched with SSH key pair",
        "recommendation": "Migrate to SSM Session Manager (no key pair needed):\n  1. Attach AmazonSSMManagedInstanceCore policy to instance role\n  2. aws ssm start-session --target <instance-id>\n  3. Remove key pair from future launches",
        "meta": ["InstanceType", "KeyName", "State.Name", "LaunchTime"],
    },
    # EC2 Instances
    "ec2-underutilised-instances": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance underutilised — CPU < 10% for 14 days",
        "recommendation": "Rightsize or stop the instance:\n  aws ec2 stop-instances --instance-ids <InstanceId>\nOr resize to a smaller type via the console.",
        "meta": ["InstanceType", "State.Name", "LaunchTime", "Tags"],
    },
    "ec2-stopped-30d": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance stopped for 30+ days (still incurs EBS charges)",
        "recommendation": "Create AMI backup then terminate:\n  aws ec2 create-image --instance-id <id> --name backup-$(date +%F)\n  aws ec2 terminate-instances --instance-ids <id>",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "ec2-stopped-60d-mark-terminate": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance stopped 60+ days — marked for termination",
        "recommendation": "Instance will be auto-terminated in 14 days unless restarted.\nCreate AMI if needed:\n  aws ec2 create-image --instance-id <id> --name backup-$(date +%F)",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "ec2-missing-tags": {
        "severity": "MEDIUM", "id_field": "InstanceId",
        "finding": "EC2 instance missing required tags (Owner/Environment/Project)",
        "recommendation": "Add required tags:\n  aws ec2 create-tags --resources <id> \\\n    --tags Key=Owner,Value=team Key=Environment,Value=dev Key=Project,Value=name",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "ec2-old-generation-instance-type": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance using previous-generation instance type",
        "recommendation": "Upgrade to current generation for better price/performance:\n  m4 → m6i/m7i,  c4 → c6i,  r4 → r6i,  t2 → t3/t4g\n  Stop instance → Change instance type → Start",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "ec2-no-detailed-monitoring": {
        "severity": "LOW", "id_field": "InstanceId",
        "finding": "EC2 instance without detailed CloudWatch monitoring",
        "recommendation": "Enable 1-minute monitoring:\n  aws ec2 monitor-instances --instance-ids <InstanceId>",
        "meta": ["InstanceType", "Monitoring.State", "State.Name"],
    },
    "ec2-imdsv1-enabled": {
        "severity": "HIGH", "id_field": "InstanceId",
        "finding": "EC2 instance allows IMDSv1 — vulnerable to SSRF attacks",
        "recommendation": "Enforce IMDSv2 (token required):\n  aws ec2 modify-instance-metadata-options \\\n    --instance-id <id> --http-tokens required --http-endpoint enabled",
        "meta": ["InstanceType", "MetadataOptions.HttpTokens", "State.Name"],
    },
    "ec2-public-ip-check": {
        "severity": "WARNING", "id_field": "InstanceId",
        "finding": "EC2 instance has a public IP address",
        "recommendation": "Verify public access is intentional.\nIf not: move to private subnet or place behind a load balancer.",
        "meta": ["InstanceType", "PublicIpAddress", "VpcId", "SubnetId"],
    },
    "ec2-no-backup-tag": {
        "severity": "MEDIUM", "id_field": "InstanceId",
        "finding": "EC2 instance missing Backup tag — may not be in backup plan",
        "recommendation": "Add backup tag to include in AWS Backup plan:\n  aws ec2 create-tags --resources <id> --tags Key=Backup,Value=daily",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "ec2-long-running-no-ri": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance running 1+ year on-demand — no reservation",
        "recommendation": "Purchase Reserved Instance or Savings Plan for up to 72% savings:\n  aws ce get-reservation-purchase-recommendation --service EC2",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    # S3 Security
    "s3-public-access-check": {
        "severity": "CRITICAL", "id_field": "Name",
        "finding": "S3 bucket has public access enabled",
        "recommendation": "Block all public access:\n  aws s3api put-public-access-block --bucket <name> \\\n    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
        "meta": ["Name", "CreationDate", "Location"],
    },
    "s3-no-encryption": {
        "severity": "HIGH", "id_field": "Name",
        "finding": "S3 bucket missing server-side encryption",
        "recommendation": "Encryption has been auto-enabled (AES-256) by this policy.\nVerify: aws s3api get-bucket-encryption --bucket <name>",
        "meta": ["Name", "CreationDate"],
    },
    "s3-no-versioning": {
        "severity": "MEDIUM", "id_field": "Name",
        "finding": "S3 bucket versioning suspended or disabled",
        "recommendation": "Enable versioning to protect against accidental deletion:\n  aws s3api put-bucket-versioning --bucket <name> \\\n    --versioning-configuration Status=Enabled",
        "meta": ["Name", "CreationDate"],
    },
    "s3-no-access-logging": {
        "severity": "MEDIUM", "id_field": "Name",
        "finding": "S3 bucket missing server access logging",
        "recommendation": "Enable access logging for audit trail:\n  aws s3api put-bucket-logging --bucket <name> \\\n    --bucket-logging-status '{\"LoggingEnabled\":{\"TargetBucket\":\"<log-bucket>\",\"TargetPrefix\":\"<name>/\"}}'",
        "meta": ["Name", "CreationDate"],
    },
    "s3-no-mfa-delete": {
        "severity": "MEDIUM", "id_field": "Name",
        "finding": "S3 versioned bucket missing MFA delete protection",
        "recommendation": "Enable MFA delete (requires root account MFA):\n  aws s3api put-bucket-versioning --bucket <name> \\\n    --versioning-configuration Status=Enabled,MFADelete=Enabled \\\n    --mfa '<serial> <code>'",
        "meta": ["Name", "CreationDate"],
    },
    "s3-no-ssl-enforcement": {
        "severity": "HIGH", "id_field": "Name",
        "finding": "S3 bucket allows non-SSL (HTTP) access",
        "recommendation": "Add a bucket policy to deny HTTP access:\n  Condition: {Bool: {'aws:SecureTransport': 'false'}} → Effect: Deny",
        "meta": ["Name", "CreationDate"],
    },
    "s3-overly-permissive-policy": {
        "severity": "CRITICAL", "id_field": "Name",
        "finding": "S3 bucket policy grants access to Principal '*'",
        "recommendation": "Remove or restrict the wildcard principal from the bucket policy.\nReview: aws s3api get-bucket-policy --bucket <name>",
        "meta": ["Name", "CreationDate"],
    },
    "s3-empty-buckets": {
        "severity": "LOW", "id_field": "Name",
        "finding": "S3 bucket is empty — no objects in 7 days",
        "recommendation": "Delete if no longer needed:\n  aws s3 rb s3://<name> --force",
        "meta": ["Name", "CreationDate"],
    },
    "s3-untagged-buckets": {
        "severity": "LOW", "id_field": "Name",
        "finding": "S3 bucket missing required tags (Owner/Environment/Project)",
        "recommendation": "Add required tags:\n  aws s3api put-bucket-tagging --bucket <name> \\\n    --tagging 'TagSet=[{Key=Owner,Value=team},{Key=Environment,Value=dev}]'",
        "meta": ["Name", "CreationDate"],
    },
    "s3-replication-no-lifecycle": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 replicated bucket missing lifecycle policy — data accumulating",
        "recommendation": "Add a lifecycle rule to expire non-current versions on destination bucket.",
        "meta": ["Name", "CreationDate"],
    },
    # S3 Cost
    "s3-incomplete-multipart-uploads": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 bucket may have incomplete multipart uploads consuming storage",
        "recommendation": "Add lifecycle rule to abort incomplete multipart uploads:\n  AbortIncompleteMultipartUpload: {DaysAfterInitiation: 7}",
        "meta": ["Name", "CreationDate"],
    },
    "s3-versioned-no-noncurrent-expiration": {
        "severity": "COST", "id_field": "Name",
        "finding": "Versioned S3 bucket accumulating non-current versions without expiry",
        "recommendation": "Add lifecycle rule:\n  NoncurrentVersionExpiration: {NoncurrentDays: 90}",
        "meta": ["Name", "CreationDate"],
    },
    "s3-standard-storage-high-cost": {
        "severity": "COST", "id_field": "Name",
        "finding": "Large S3 bucket (>100GB) with low access — Standard storage costly",
        "recommendation": "Switch to Intelligent-Tiering:\n  aws s3api put-bucket-intelligent-tiering-configuration ...",
        "meta": ["Name", "CreationDate"],
    },
    "s3-transfer-acceleration-unused": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 transfer acceleration enabled but traffic is very low",
        "recommendation": "Disable transfer acceleration:\n  aws s3api put-bucket-accelerate-configuration --bucket <name> \\\n    --accelerate-configuration Status=Suspended",
        "meta": ["Name", "CreationDate"],
    },
    # S3 Lifecycle
    "s3-missing-lifecycle": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 bucket has no lifecycle rule — objects may stay in expensive tier",
        "recommendation": "Add lifecycle rule to transition to IA/Glacier after 30/90 days.",
        "meta": ["Name", "CreationDate"],
    },
    # EBS
    "ebs-unattached-volumes": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "EBS volume unattached — incurring storage cost with no use",
        "recommendation": "Create snapshot then delete:\n  aws ec2 create-snapshot --volume-id <id> --description backup\n  aws ec2 delete-volume --volume-id <id>",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone", "CreateTime"],
    },
    "ebs-unencrypted": {
        "severity": "HIGH", "id_field": "VolumeId",
        "finding": "EBS volume is not encrypted",
        "recommendation": "Create encrypted snapshot and replace volume:\n  aws ec2 copy-snapshot --source-snapshot-id <snap> --encrypted",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone"],
    },
    "ebs-gp2-upgrade-to-gp3": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "EBS volume using gp2 — gp3 is 20% cheaper with better performance",
        "recommendation": "Upgrade to gp3 (no downtime):\n  aws ec2 modify-volume --volume-id <id> --volume-type gp3",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone"],
    },
    "ebs-old-snapshots": {
        "severity": "COST", "id_field": "SnapshotId",
        "finding": "EBS snapshot older than 90 days — review for deletion",
        "recommendation": "Review and delete stale snapshots:\n  aws ec2 delete-snapshot --snapshot-id <SnapshotId>",
        "meta": ["SnapshotId", "VolumeId", "StartTime", "Description"],
    },
    # ENI / EIP
    "eni-unattached": {
        "severity": "COST", "id_field": "NetworkInterfaceId",
        "finding": "ENI unattached — idle network interface incurring cost",
        "recommendation": "Delete if not needed:\n  aws ec2 delete-network-interface --network-interface-id <id>",
        "meta": ["NetworkInterfaceId", "VpcId", "SubnetId", "AvailabilityZone"],
    },
    "eip-unattached": {
        "severity": "COST", "id_field": "PublicIp",
        "finding": "Elastic IP not associated — charged ~$3.60/month while idle",
        "recommendation": "Release if not needed:\n  aws ec2 release-address --allocation-id <AllocationId>",
        "meta": ["PublicIp", "AllocationId", "Domain"],
    },
    # AMI
    "ami-unused-detection": {
        "severity": "COST", "id_field": "ImageId",
        "finding": "AMI unused for 90+ days — no running instances use it",
        "recommendation": "Deregister AMI and delete associated snapshots:\n  aws ec2 deregister-image --image-id <ImageId>\n  aws ec2 delete-snapshot --snapshot-id <snap-id>",
        "meta": ["ImageId", "Name", "CreationDate", "State"],
    },
}

# Fallback for any policy not in the map above
_DEFAULT_META = {
    "severity": "INFO", "id_field": None,
    "finding": None, "recommendation": "Review this resource.",
    "meta": [],
}

# Group-level mapping: group name → file(s)
GROUP_MAP = {
    "s3-lifecycle":   ["s3-infrequent-access-lifecycle.yml"],
    "s3-security":    ["s3-security-compliance.yml"],
    "s3-cost":        ["s3-cost-optimization.yml"],
    "s3":             ["s3-infrequent-access-lifecycle.yml", "s3-security-compliance.yml", "s3-cost-optimization.yml"],
    "ebs":            ["ebs-unattached.yml"],
    "ebs-optimize":   ["ebs-optimization.yml"],
    "ec2":            ["ec2-instances.yml"],
    "ec2-security":   ["ec2-security.yml"],
    "eni":            ["eni-cleanup.yml"],
    "ami":            ["ami-unused-cleanup.yml"],
}


def _build_policy_index():
    """
    Scan all YAML files and build a map of:
      policy_name → { "file": "ec2-instances.yml", "policy": { ... } }
    Called once per Lambda cold start.
    """
    index = {}
    for filename in sorted(os.listdir(POLICY_DIR)):
        if not filename.endswith(".yml"):
            continue
        filepath = os.path.join(POLICY_DIR, filename)
        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)
            for pol in data.get("policies", []):
                index[pol["name"]] = {
                    "file": filename,
                    "policy": pol,
                }
        except Exception as e:
            logger.warning(f"Failed to parse {filename}: {e}")
    return index


# Built once on cold start
POLICY_INDEX = _build_policy_index()


def lambda_handler(event, context):
    """
    API Gateway event handler.

    Body params:
      policy   — group name, individual name, "all", or "list"
      policies — array of individual policy names (alternative to policy)
      dryrun   — "true" (default) | "false"
      region   — AWS region override (default: C7N_REGION env var)
      action_request — true → run action instead of scan
      action   — c7n action type (used with action_request)
      resource_ids — list of resource IDs to target (used with action_request)
    """
    params = _parse_event(event)

    # ── Action execution mode ──────────────────────────────
    if params.get("action_request"):
        policy_name  = params.get("policy")
        resource_ids = params.get("resource_ids", [])
        action_type  = params.get("action")
        region       = params.get("region") or REGION
        if not policy_name or not action_type:
            return _response(400, {"error": "policy and action are required"})
        result = _run_action_on_resources(policy_name, resource_ids, action_type, region)
        return _response(200, result)

    # ── Dynamic policy build & run ─────────────────────────
    if params.get("spec"):
        spec   = params["spec"]
        if not isinstance(spec, dict) or not spec.get("resource"):
            return _response(400, {"error": "spec.resource is required"})
        region = params.get("region") or REGION
        dryrun = str(params.get("dryrun", "true")).lower() == "true"
        result = _run_policy_from_spec(spec, dryrun, region)
        return _response(200, result)

    # ── Region override ────────────────────────────────────
    region = params.get("region") or REGION
    dryrun = str(params.get("dryrun", "true")).lower() == "true"

    # ── Resolve policies ───────────────────────────────────
    policies_list = params.get("policies")
    if isinstance(policies_list, list) and policies_list:
        resolved = []
        for name in policies_list:
            r = _resolve_policies(name, region)
            if r:
                resolved.extend(r)
        if not resolved:
            return _response(400, {"error": "No valid policies found in the provided list"})
        requested_label = f"{len(policies_list)} policies"
    else:
        policy_input = params.get("policy", "all")
        if policy_input == "list":
            return _response(200, _list_policies())
        resolved = _resolve_policies(policy_input, region)
        if resolved is None:
            return _response(400, {
                "error": f"Unknown policy or group: '{policy_input}'",
                "hint": 'Use {"policy": "list"} to see available policies',
            })
        requested_label = policy_input

    # ── Execute ────────────────────────────────────────────
    results = []
    for item in resolved:
        result = _run_policy(item["file"], item.get("filter_name"), dryrun, region)
        results.append(result)

    if OUTPUT_BUCKET:
        _upload_results(results)

    # Include account identity so the UI can show Account header
    try:
        identity = boto3.client("sts").get_caller_identity()
        account_info = {"account_id": identity["Account"], "arn": identity["Arn"], "region": region}
    except Exception:
        account_info = {"account_id": "unknown", "region": region}

    return _response(200, {
        "execution_time": _now().isoformat(),
        "dryrun": dryrun,
        "region": region,
        "account": account_info,
        "requested": requested_label,
        "policies_executed": len(results),
        "results": results,
    })


def _resolve_policies(policy_input, region=None):
    """
    Resolve input to a list of { file, filter_name }.
    Returns None if input is invalid.
    """
    # 1. "all" → every yml file, no filter
    if policy_input == "all":
        return [
            {"file": os.path.join(POLICY_DIR, f)}
            for f in sorted(os.listdir(POLICY_DIR))
            if f.endswith(".yml")
        ]

    # 2. Group name → one or more files, no filter
    if policy_input in GROUP_MAP:
        return [
            {"file": os.path.join(POLICY_DIR, f)}
            for f in GROUP_MAP[policy_input]
        ]

    # 3. Individual policy name → single file with filter
    if policy_input in POLICY_INDEX:
        entry = POLICY_INDEX[policy_input]
        return [{
            "file": os.path.join(POLICY_DIR, entry["file"]),
            "filter_name": policy_input,
        }]

    return None


def _run_policy(policy_file, filter_name=None, dryrun=True, region=None):
    """
    Execute a c7n policy file.
    If filter_name is set, extract only that one policy into a
    temp file and run it instead of the whole file.
    """
    run_region   = region or REGION
    display_name = filter_name or os.path.basename(policy_file)

    with tempfile.TemporaryDirectory() as output_dir:
        run_file = policy_file

        # If running a single policy, extract it to a temp file
        if filter_name:
            run_file = _extract_single_policy(policy_file, filter_name, output_dir)
            if run_file is None:
                return {
                    "policy": display_name,
                    "status": "error",
                    "error": f"Policy '{filter_name}' not found in {os.path.basename(policy_file)}",
                    "resources_found": {},
                }

        cmd = [
            "custodian", "run",
            "-s", output_dir,
            "--cache-period", "0",
            "--region", run_region,
        ]
        if dryrun:
            cmd.append("--dryrun")
        cmd.append(run_file)

        logger.info(f"Running: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # Read resources BEFORE the temp dir is cleaned up
            raw_resources = _load_raw_resources(output_dir)
            resources = _normalize_resources(display_name, raw_resources)

            # Pull policy description from YAML index
            pol_entry = POLICY_INDEX.get(display_name, {})
            description = pol_entry.get("policy", {}).get("description", "")

            return {
                "policy": display_name,
                "description": description,
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "resources_found": {display_name: len(resources)},
                "resources": resources,
                "stderr": proc.stderr[-500:] if proc.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {
                "policy": display_name,
                "status": "timeout",
                "resources_found": {},
                "resources": [],
            }
        except Exception as e:
            return {
                "policy": display_name,
                "status": "error",
                "error": str(e),
                "resources_found": {},
                "resources": [],
            }


def _extract_single_policy(policy_file, policy_name, output_dir):
    """
    Read a multi-policy YAML file, extract the one matching
    policy_name, write it to a temp file, and return the path.
    """
    try:
        with open(policy_file) as f:
            data = yaml.safe_load(f)

        for pol in data.get("policies", []):
            if pol["name"] == policy_name:
                temp_path = os.path.join(output_dir, f"{policy_name}.yml")
                with open(temp_path, "w") as out:
                    yaml.dump({"policies": [pol]}, out, default_flow_style=False)
                return temp_path
    except Exception as e:
        logger.error(f"Failed to extract policy {policy_name}: {e}")

    return None


def _list_policies():
    """Return structured list of all available groups and policies."""
    groups = {}
    for filename in sorted(os.listdir(POLICY_DIR)):
        if not filename.endswith(".yml"):
            continue
        filepath = os.path.join(POLICY_DIR, filename)
        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)
            policies = [p["name"] for p in data.get("policies", [])]
            groups[filename] = policies
        except Exception:
            groups[filename] = []

    # Find which group keys map to which files
    group_keys = {k: v for k, v in GROUP_MAP.items()}

    # Resolve AWS account identity (works via Lambda role or local creds)
    account_info = {}
    try:
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        account_info = {
            "account_id": identity["Account"],
            "arn": identity["Arn"],
            "region": REGION,
        }
    except Exception as e:
        account_info = {"account_id": "unknown", "region": REGION, "error": str(e)}

    return {
        "groups": group_keys,
        "individual_policies": {
            name: entry["file"]
            for name, entry in sorted(POLICY_INDEX.items())
        },
        "files": groups,
        "account": account_info,
        "usage": {
            "run_group": '{"policy": "ec2", "dryrun": "true"}',
            "run_single": '{"policy": "ec2-stopped-30d", "dryrun": "true"}',
            "run_all": '{"policy": "all", "dryrun": "true"}',
        },
    }


def _parse_event(event):
    """Extract parameters from API Gateway event."""
    params = {}
    if event.get("queryStringParameters"):
        params.update(event["queryStringParameters"])
    if event.get("body"):
        try:
            body = json.loads(event["body"])
            if isinstance(body, dict):
                params.update(body)
        except (json.JSONDecodeError, TypeError):
            pass
    return params


def _load_raw_resources(output_dir):
    """Load all resources.json files from c7n output directory."""
    all_resources = []
    for root, dirs, files in os.walk(output_dir):
        if "resources.json" in files:
            filepath = os.path.join(root, "resources.json")
            try:
                with open(filepath) as f:
                    resources = json.load(f)
                all_resources.extend(resources)
            except (json.JSONDecodeError, IOError):
                pass
    return all_resources


def _normalize_resources(policy_name, raw_resources):
    """
    Map raw AWS resource objects to the normalized UI format:
      { Severity, Finding, ResourceId, Recommendation, Description, ...metadata }
    """
    meta = POLICY_META.get(policy_name, _DEFAULT_META)
    normalized = []

    for r in raw_resources:
        # Extract resource ID
        id_field = meta.get("id_field")
        resource_id = _get_nested(r, id_field) if id_field else "-"

        # Build metadata dict from interesting fields
        detail = {}
        for field in meta.get("meta", []):
            val = _get_nested(r, field)
            if val is not None:
                detail[field] = val

        # Also include Tags as a flat string if present
        tags = r.get("Tags", [])
        if tags:
            tag_str = ", ".join(f"{t['Key']}={t['Value']}" for t in tags
                               if not t['Key'].startswith("c7n:"))
            if tag_str:
                detail["Tags"] = tag_str

        normalized.append({
            "Severity": meta["severity"],
            "Finding": meta.get("finding") or policy_name,
            "ResourceId": str(resource_id) if resource_id else "-",
            "Recommendation": meta.get("recommendation", ""),
            **detail,
        })

    return normalized


def _get_nested(obj, dotted_key):
    """Retrieve a value from a nested dict using dot notation. e.g. 'State.Name'"""
    if not dotted_key:
        return None
    keys = dotted_key.split(".")
    val = obj
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val


def _run_action_on_resources(policy_name, resource_ids, action_type, region=None):
    """
    Run a specific c7n action against targeted resource IDs.
    Builds a temp YAML: original policy filters + resource-ID filter + chosen action.
    Always runs LIVE (no --dryrun).
    """
    run_region = region or REGION
    entry = POLICY_INDEX.get(policy_name)
    if not entry:
        return {"status": "error", "error": f"Policy '{policy_name}' not found"}

    pol = copy.deepcopy(entry["policy"])
    meta = POLICY_META.get(policy_name, _DEFAULT_META)
    id_field = meta.get("id_field")

    # Add a filter to target only the selected resource IDs
    if id_field and resource_ids:
        pol.setdefault("filters", []).append({
            "type": "value",
            "key": id_field,
            "op": "in",
            "value": list(resource_ids),
        })

    action_config = _build_action_config(action_type, run_region)
    if action_config is None:
        return {"status": "error", "error": f"Unknown action: '{action_type}'"}
    pol["actions"] = [action_config]

    with tempfile.TemporaryDirectory() as output_dir:
        temp_yaml = os.path.join(output_dir, f"action-{policy_name}.yml")
        with open(temp_yaml, "w") as f:
            yaml.dump({"policies": [pol]}, f, default_flow_style=False)

        cmd = [
            "custodian", "run",
            "-s", output_dir,
            "--cache-period", "0",
            "--region", run_region,
            temp_yaml,          # NO --dryrun → runs live
        ]
        logger.info(f"Action run: {' '.join(cmd)}")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            raw  = _load_raw_resources(output_dir)
            return {
                "policy":             policy_name,
                "action":             action_type,
                "status":             "success" if proc.returncode == 0 else "error",
                "return_code":        proc.returncode,
                "resources_affected": len(raw),
                "stderr":             proc.stderr[-300:] if proc.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"policy": policy_name, "action": action_type, "status": "timeout", "resources_affected": 0}
        except Exception as e:
            return {"policy": policy_name, "action": action_type, "status": "error", "error": str(e), "resources_affected": 0}


def _build_action_config(action_type, region=None):
    """Return a c7n action dict for the given action_type string."""
    run_region = region or REGION
    if action_type == "tag":
        return {"type": "tag", "key": "c7n:manual-action",
                "value": _now().strftime("applied-%Y-%m-%d")}
    if action_type == "notify":
        try:
            account_id = boto3.client("sts").get_caller_identity()["Account"]
        except Exception:
            account_id = "000000000000"
        return {
            "type": "notify",
            "template": "default.html",
            "subject": "[c7n] Manual remediation triggered",
            "to": ["your-team@example.com"],
            "transport": {
                "type": "sqs",
                "queue": f"https://sqs.{run_region}.amazonaws.com/{account_id}/c7n-notifications",
            },
        }
    simple = {
        "stop":                  {"type": "stop"},
        "terminate":             {"type": "terminate"},
        "mark-for-op":           {"type": "mark-for-op", "tag": "c7n:marked-for-termination", "op": "terminate", "days": 14},
        "revoke":                {"type": "revoke"},
        "snapshot":              {"type": "snapshot"},
        "delete":                {"type": "delete"},
        "set-bucket-encryption": {"type": "set-bucket-encryption", "crypto": "AES256"},
        "toggle-versioning":     {"type": "toggle-versioning", "enabled": True},
        "deregister":            {"type": "deregister"},
        "release":               {"type": "release"},
    }
    return simple.get(action_type)


def _upload_results(results):
    """Upload execution results to S3 for audit trail."""
    s3 = boto3.client("s3")
    timestamp = _now().strftime("%Y/%m/%d/%H%M%S")
    key = f"c7n-results/{timestamp}/results.json"
    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=key,
        Body=json.dumps(results, indent=2),
        ContentType="application/json",
    )
    logger.info(f"Results uploaded to s3://{OUTPUT_BUCKET}/{key}")


# Common primary-key field per c7n resource type
_RESOURCE_ID_FIELDS = {
    "ec2":                    "InstanceId",
    "security-group":         "GroupId",
    "ebs":                    "VolumeId",
    "ebs-snapshot":           "SnapshotId",
    "ami":                    "ImageId",
    "eni":                    "NetworkInterfaceId",
    "eip-allocation":         "AllocationId",
    "s3":                     "Name",
    "rds":                    "DBInstanceIdentifier",
    "rds-snapshot":           "DBSnapshotIdentifier",
    "lambda":                 "FunctionName",
    "iam-user":               "UserName",
    "iam-role":               "RoleName",
    "iam-group":              "GroupName",
    "iam-policy":             "PolicyName",
    "cloudformation":         "StackName",
    "dynamodb-table":         "TableName",
    "sqs":                    "QueueUrl",
    "sns":                    "TopicArn",
    "eks":                    "name",
    "ecs-cluster":            "clusterName",
    "elasticache-cluster":    "CacheClusterId",
    "redshift":               "ClusterIdentifier",
    "elasticsearch":          "DomainName",
    "kms-key":                "KeyId",
    "vpc":                    "VpcId",
    "subnet":                 "SubnetId",
    "route-table":            "RouteTableId",
    "nat-gateway":            "NatGatewayId",
    "internet-gateway":       "InternetGatewayId",
    "elb":                    "LoadBalancerName",
    "app-elb":                "LoadBalancerArn",
    "app-elb-target-group":   "TargetGroupArn",
    "distribution":           "Id",
    "hostedzone":             "Id",
    "log-group":              "logGroupName",
    "ecr":                    "repositoryName",
    "codecommit":             "repositoryName",
    "codebuild":              "name",
    "codepipeline":           "name",
    "kinesis":                "StreamName",
    "firehose":               "DeliveryStreamName",
    "config-rule":            "ConfigRuleName",
    "guardduty":              "DetectorId",
    "acm-certificate":        "CertificateArn",
    "secrets-manager":        "ARN",
    "ssm-parameter":          "Name",
    "backup-vault":           "BackupVaultName",
    "backup-plan":            "BackupPlanId",
}


def _infer_id_field(resource_type, sample_resource):
    """
    Guess the primary-key field for a dynamic policy result.
    Priority: lookup table → key ending in 'Id' → 'ARN'/'Arn' → 'Name'.
    """
    if resource_type in _RESOURCE_ID_FIELDS:
        return _RESOURCE_ID_FIELDS[resource_type]
    if not sample_resource:
        return None
    keys = [k for k in sample_resource if not k.startswith("c7n:")]
    # Prefer keys ending in 'Id' (InstanceId, VolumeId, …)
    for k in keys:
        if k.endswith("Id"):
            return k
    # Then ARN / Arn
    for k in keys:
        if k in ("ARN", "Arn") or k.endswith("Arn") or k.endswith("ARN"):
            return k
    # Then Name
    for k in keys:
        if k == "Name" or k.endswith("Name"):
            return k
    return keys[0] if keys else None


def _spec_to_yaml(spec):
    """
    Convert a dynamic policy spec dict to a c7n YAML string.

    spec = {
        "name":        "my-dynamic-policy",   # optional, auto-generated if absent
        "resource":    "ec2",                  # required — c7n resource type
        "description": "...",                  # optional
        "filters":     [...],                  # list of c7n filter dicts
        "actions":     [...],                  # list of c7n action dicts
    }
    """
    resource = spec["resource"]
    if not resource.startswith("aws."):
        resource = f"aws.{resource}"

    policy = {
        "name":     spec.get("name") or f"dynamic-{spec['resource']}",
        "resource": resource,
        "filters":  spec.get("filters", []),
        "actions":  spec.get("actions", []),
    }
    if spec.get("description"):
        policy["description"] = spec["description"]

    return yaml.dump({"policies": [policy]}, default_flow_style=False, sort_keys=False)


def _run_policy_from_spec(spec, dryrun=True, region=None):
    """
    Build a temp YAML from a dynamic spec and execute it with custodian.
    Returns scan results plus the generated YAML so the UI can preview it.
    """
    run_region  = region or REGION
    policy_name = spec.get("name") or f"dynamic-{spec['resource']}"
    resource_type = spec["resource"].lstrip("aws.")

    yaml_str = _spec_to_yaml(spec)
    id_field_hint = spec.get("id_field") or _RESOURCE_ID_FIELDS.get(resource_type)

    with tempfile.TemporaryDirectory() as output_dir:
        temp_yaml = os.path.join(output_dir, f"{policy_name}.yml")
        with open(temp_yaml, "w") as f:
            f.write(yaml_str)

        cmd = [
            "custodian", "run",
            "-s", output_dir,
            "--cache-period", "0",
            "--region", run_region,
        ]
        if dryrun:
            cmd.append("--dryrun")
        cmd.append(temp_yaml)

        logger.info(f"Dynamic policy run: {' '.join(cmd)}")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            raw_resources = _load_raw_resources(output_dir)

            # Infer ID field from actual data if hint not available
            id_field = id_field_hint or _infer_id_field(resource_type, raw_resources[0] if raw_resources else None)

            # Normalize without POLICY_META — use inferred id_field
            normalized = []
            for r in raw_resources:
                rid = _get_nested(r, id_field) if id_field else "-"
                tags = r.get("Tags", [])
                tag_str = ", ".join(
                    f"{t['Key']}={t['Value']}" for t in tags
                    if not t["Key"].startswith("c7n:")
                ) if isinstance(tags, list) else ""
                entry = {
                    "Severity":       "INFO",
                    "Finding":        policy_name,
                    "ResourceId":     str(rid) if rid is not None else "-",
                    "Recommendation": spec.get("description", "Review this resource."),
                }
                if tag_str:
                    entry["Tags"] = tag_str
                normalized.append(entry)

            return {
                "policy":          policy_name,
                "status":          "success" if proc.returncode == 0 else "error",
                "return_code":     proc.returncode,
                "resources_found": {policy_name: len(normalized)},
                "resources":       normalized,
                "generated_yaml":  yaml_str,
                "stderr":          proc.stderr[-500:] if proc.stderr else "",
            }

        except subprocess.TimeoutExpired:
            return {
                "policy":         policy_name,
                "status":         "timeout",
                "resources_found": {},
                "resources":       [],
                "generated_yaml":  yaml_str,
            }
        except Exception as e:
            return {
                "policy":         policy_name,
                "status":         "error",
                "error":          str(e),
                "resources_found": {},
                "resources":       [],
                "generated_yaml":  yaml_str,
            }


def _response(status_code, body):
    """Format API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, indent=2, default=str),
    }
