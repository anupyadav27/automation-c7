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
    "ami-unused-90d-mark": {
        "severity": "COST", "id_field": "ImageId",
        "finding": "AMI unused for 90+ days — marked for deregistration in 14 days",
        "recommendation": "Review and confirm. Exempt by removing the c7n:marked-for-deregister tag if still needed.",
        "meta": ["ImageId", "Name", "CreationDate", "State"],
    },
    "ami-unused-deregister": {
        "severity": "COST", "id_field": "ImageId",
        "finding": "AMI grace period expired — deregistered and associated snapshots deleted",
        "recommendation": "Restore from a backup AMI if needed. Ensure future AMIs are tagged with an owner.",
        "meta": ["ImageId", "Name", "CreationDate", "State"],
    },
    "ami-not-in-launch-config": {
        "severity": "COST", "id_field": "ImageId",
        "finding": "AMI not referenced by any instance, Launch Template, or ASG config",
        "recommendation": "Deregister if confirmed unused:\n  aws ec2 deregister-image --image-id <ImageId>",
        "meta": ["ImageId", "Name", "CreationDate", "State"],
    },
    # EBS Optimization
    "ebs-overprovisioned-iops": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "io1/io2 EBS volume — IOPS utilization < 10% for 14 days (over-provisioned)",
        "recommendation": "Downgrade to gp3 or reduce provisioned IOPS to match actual usage:\n  aws ec2 modify-volume --volume-id <id> --volume-type gp3",
        "meta": ["VolumeId", "Size", "VolumeType", "Iops", "AvailabilityZone"],
    },
    "ebs-untagged": {
        "severity": "MEDIUM", "id_field": "VolumeId",
        "finding": "EBS volume missing Name tag — cannot be attributed in cost reports",
        "recommendation": "Add a Name tag:\n  aws ec2 create-tags --resources <VolumeId> --tags Key=Name,Value=<service-name>",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone"],
    },
    "ebs-orphaned-snapshots": {
        "severity": "COST", "id_field": "SnapshotId",
        "finding": "EBS snapshot whose source volume no longer exists — likely orphaned",
        "recommendation": "Delete if no longer needed:\n  aws ec2 delete-snapshot --snapshot-id <SnapshotId>",
        "meta": ["SnapshotId", "VolumeId", "StartTime", "Description"],
    },
    "ebs-large-low-throughput": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "EBS volume > 500 GB with very low read/write activity — likely over-sized",
        "recommendation": "Snapshot and resize to a smaller volume:\n  aws ec2 create-snapshot --volume-id <id> --description before-resize",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone"],
    },
    "ebs-unattached-30d-cleanup": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "EBS volume unattached for 30+ days — snapshot created and volume deleted",
        "recommendation": "Volume has been automatically cleaned up. Verify snapshot exists:\n  aws ec2 describe-snapshots --filters Name=volume-id,Values=<VolumeId>",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone", "CreateTime"],
    },
    "ebs-unattached-mark-for-deletion": {
        "severity": "COST", "id_field": "VolumeId",
        "finding": "Unattached EBS volume marked for deletion in 14 days",
        "recommendation": "Reattach or snapshot the volume before deletion:\n  aws ec2 create-snapshot --volume-id <id> --description manual-backup",
        "meta": ["VolumeId", "Size", "VolumeType", "AvailabilityZone", "CreateTime"],
    },
    # ENI action policies
    "eni-unattached-30d-cleanup": {
        "severity": "COST", "id_field": "NetworkInterfaceId",
        "finding": "ENI unattached for 30+ days — marked for deletion in 7 days",
        "recommendation": "Identify owner and delete if confirmed orphaned:\n  aws ec2 delete-network-interface --network-interface-id <id>",
        "meta": ["NetworkInterfaceId", "VpcId", "SubnetId", "AvailabilityZone"],
    },
    "eni-marked-delete": {
        "severity": "COST", "id_field": "NetworkInterfaceId",
        "finding": "ENI grace period expired — will be deleted",
        "recommendation": "Remove the c7n:marked-for-deletion tag to exempt this ENI if it is still needed.",
        "meta": ["NetworkInterfaceId", "VpcId", "SubnetId", "AvailabilityZone"],
    },
    "eni-untagged": {
        "severity": "LOW", "id_field": "NetworkInterfaceId",
        "finding": "ENI missing Name tag — owner and purpose cannot be determined",
        "recommendation": "Add a Name tag to identify the owning service:\n  aws ec2 create-tags --resources <id> --tags Key=Name,Value=<service>",
        "meta": ["NetworkInterfaceId", "VpcId", "SubnetId", "Description"],
    },
    "eip-unattached-release": {
        "severity": "COST", "id_field": "PublicIp",
        "finding": "Elastic IP unattached for 7+ days — released to stop charges",
        "recommendation": "Allocate a new EIP if needed:\n  aws ec2 allocate-address --domain vpc",
        "meta": ["PublicIp", "AllocationId", "Domain"],
    },
    # S3 Lifecycle (additional)
    "s3-low-access-suggest-lifecycle": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 bucket with < 100 GET requests in 14 days — candidate for IA/Glacier transition",
        "recommendation": "Add lifecycle rule to transition to S3-IA after 30 days, Glacier after 90 days.",
        "meta": ["Name", "CreationDate"],
    },
    "s3-large-bucket-low-access": {
        "severity": "COST", "id_field": "Name",
        "finding": "S3 bucket > 50 GB with fewer than 500 GET requests in 14 days — high cost, low use",
        "recommendation": "Enable S3 Intelligent-Tiering:\n  aws s3api put-bucket-intelligent-tiering-configuration --bucket <name> ...",
        "meta": ["Name", "CreationDate"],
    },
    # ── finops/cost_anomaly.yaml ──
    "ec2-not-ebs-optimized": {
        "severity": "COST", "id_field": "InstanceId",
        "finding": "EC2 instance running without EBS optimization — I/O contention possible",
        "recommendation": "Enable EBS optimization via the console or:\n  aws ec2 modify-instance-attribute --instance-id <id> --ebs-optimized '{\"Value\":true}'",
        "meta": ["InstanceType", "State.Name", "LaunchTime"],
    },
    "lambda-not-invoked-30d": {
        "severity": "COST", "id_field": "FunctionName",
        "finding": "Lambda function has zero invocations in the past 30 days — may be unused",
        "recommendation": "Review and delete if no longer needed:\n  aws lambda delete-function --function-name <FunctionName>",
        "meta": ["FunctionName", "Runtime", "LastModified", "CodeSize"],
    },
    # ── finops/idle_resources.yaml ──
    "rds-idle-instance": {
        "severity": "COST", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance with 0 database connections for 14 days — idle and billing",
        "recommendation": "Stop or delete the instance:\n  aws rds stop-db-instance --db-instance-identifier <id>\n  or snapshot and delete for permanent removal.",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "DBInstanceStatus"],
    },
    "rds-stopped-7d": {
        "severity": "COST", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance stopped — AWS auto-restarts after 7 days resuming billing",
        "recommendation": "Snapshot and delete if not needed:\n  aws rds create-db-snapshot --db-instance-identifier <id> --db-snapshot-identifier <snap>\n  aws rds delete-db-instance --db-instance-identifier <id> --skip-final-snapshot",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "DBInstanceStatus"],
    },
    # ── finops/rightsizing.yaml ──
    "rds-oversized-instance": {
        "severity": "COST", "id_field": "DBInstanceIdentifier",
        "finding": "RDS memory-optimised instance (r5/r6g/x1) with fewer than 10 connections — oversized",
        "recommendation": "Downsize to db.m6i or db.t3 family based on actual workload:\n  aws rds modify-db-instance --db-instance-identifier <id> --db-instance-class db.m6i.large --apply-immediately",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "MultiAZ"],
    },
    "rds-no-reserved-instance": {
        "severity": "COST", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance running on-demand for 90+ days — no Reserved Instance",
        "recommendation": "Purchase Reserved Instance for up to 72% savings:\n  aws rds describe-reserved-db-instances-offerings",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "MultiAZ"],
    },
    # ── finops/tagging_compliance.yaml ──
    "lambda-missing-tags": {
        "severity": "MEDIUM", "id_field": "FunctionName",
        "finding": "Lambda function missing required tags (Owner/Environment/Project)",
        "recommendation": "Add required tags:\n  aws lambda tag-resource --resource <arn> --tags Owner=team,Environment=dev,Project=name",
        "meta": ["FunctionName", "Runtime", "LastModified"],
    },
    "rds-missing-tags": {
        "severity": "MEDIUM", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance missing required tags (Owner/Environment/Project)",
        "recommendation": "Add required tags:\n  aws rds add-tags-to-resource --resource-name <arn> \\\n    --tags Key=Owner,Value=team Key=Environment,Value=dev",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine"],
    },
    # ── security/encryption_at_rest.yaml ──
    "rds-snapshot-unencrypted": {
        "severity": "HIGH", "id_field": "DBSnapshotIdentifier",
        "finding": "RDS snapshot is not encrypted — sensitive data at rest unprotected",
        "recommendation": "Copy snapshot with encryption enabled:\n  aws rds copy-db-snapshot --source-db-snapshot-identifier <snap> \\\n    --target-db-snapshot-identifier <snap>-enc --kms-key-id <key-arn>",
        "meta": ["DBSnapshotIdentifier", "DBInstanceIdentifier", "SnapshotCreateTime", "Encrypted"],
    },
    "rds-no-auto-minor-upgrade": {
        "severity": "MEDIUM", "id_field": "DBInstanceIdentifier",
        "finding": "RDS auto minor version upgrade disabled — security patches not applied",
        "recommendation": "Enable auto minor version upgrade:\n  aws rds modify-db-instance --db-instance-identifier <id> \\\n    --auto-minor-version-upgrade --apply-immediately",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "EngineVersion"],
    },
    # ── security/iam_least_privilege.yaml ──
    "iam-user-no-mfa": {
        "severity": "CRITICAL", "id_field": "UserName",
        "finding": "IAM user has console password but no MFA device enrolled",
        "recommendation": "Enforce MFA for all console users:\n  1. Go to IAM → Users → <user> → Security credentials → Assign MFA\n  2. Add SCP to deny non-MFA API calls",
        "meta": ["UserName", "CreateDate", "PasswordLastUsed"],
    },
    "iam-inactive-user": {
        "severity": "HIGH", "id_field": "UserName",
        "finding": "IAM user credentials (password or access keys) unused for 90+ days",
        "recommendation": "Disable or delete dormant credentials:\n  aws iam update-login-profile --user-name <user> --password-reset-required\n  aws iam update-access-key --access-key-id <key> --status Inactive --user-name <user>",
        "meta": ["UserName", "CreateDate", "PasswordLastUsed"],
    },
    # ── security/network_exposure.yaml ──
    "sg-high-rule-count": {
        "severity": "MEDIUM", "id_field": "GroupId",
        "finding": "Security group has many inbound rules open to 0.0.0.0/0 — audit needed",
        "recommendation": "Review and consolidate inbound rules. Remove stale entries:\n  aws ec2 describe-security-groups --group-ids <GroupId>",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    "vpc-default-sg-has-rules": {
        "severity": "HIGH", "id_field": "GroupId",
        "finding": "Default VPC security group has inbound/outbound rules — CIS Benchmark 4.3 violation",
        "recommendation": "Remove all rules from the default security group:\n  aws ec2 revoke-security-group-ingress --group-id <GroupId> ...",
        "meta": ["GroupName", "VpcId", "Description"],
    },
    # ── security/public_access.yaml ──
    "lambda-public-url-no-auth": {
        "severity": "CRITICAL", "id_field": "FunctionName",
        "finding": "Lambda function URL is public with AuthType NONE — unauthenticated invoke allowed",
        "recommendation": "Change AuthType to AWS_IAM or delete the function URL:\n  aws lambda update-function-url-config --function-name <name> --auth-type AWS_IAM",
        "meta": ["FunctionName", "Runtime", "LastModified"],
    },
    "lambda-public-invoke-policy": {
        "severity": "HIGH", "id_field": "FunctionName",
        "finding": "Lambda resource policy allows cross-account or public invocation",
        "recommendation": "Review and restrict the resource-based policy:\n  aws lambda get-policy --function-name <name>\n  Remove Principal: * statements.",
        "meta": ["FunctionName", "Runtime", "LastModified"],
    },
    # ── rds-security.yml ──
    "rds-public-access": {
        "severity": "CRITICAL", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance has PubliclyAccessible=true — reachable from the internet",
        "recommendation": "Disable public access:\n  aws rds modify-db-instance --db-instance-identifier <id> \\\n    --no-publicly-accessible --apply-immediately",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "Endpoint.Address"],
    },
    "rds-unencrypted": {
        "severity": "HIGH", "id_field": "DBInstanceIdentifier",
        "finding": "RDS instance storage is not encrypted — data at rest unprotected",
        "recommendation": "Encrypt via snapshot restore:\n  1. Create snapshot\n  2. Copy snapshot with --kms-key-id\n  3. Restore new instance from encrypted snapshot",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "StorageEncrypted"],
    },
    "rds-no-multi-az": {
        "severity": "MEDIUM", "id_field": "DBInstanceIdentifier",
        "finding": "RDS production instance running Single-AZ — no automatic failover",
        "recommendation": "Enable Multi-AZ (brief failover during conversion):\n  aws rds modify-db-instance --db-instance-identifier <id> --multi-az --apply-immediately",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "AvailabilityZone"],
    },
    "rds-no-backup": {
        "severity": "HIGH", "id_field": "DBInstanceIdentifier",
        "finding": "RDS backup retention period is less than 7 days",
        "recommendation": "Increase backup retention to at least 7 days:\n  aws rds modify-db-instance --db-instance-identifier <id> --backup-retention-period 7",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "BackupRetentionPeriod"],
    },
    "rds-old-snapshot": {
        "severity": "COST", "id_field": "DBSnapshotIdentifier",
        "finding": "Manual RDS snapshot older than 90 days — accumulating storage cost",
        "recommendation": "Delete if no longer needed for recovery or compliance:\n  aws rds delete-db-snapshot --db-snapshot-identifier <id>",
        "meta": ["DBSnapshotIdentifier", "DBInstanceIdentifier", "SnapshotCreateTime", "AllocatedStorage"],
    },
    "rds-no-deletion-protection": {
        "severity": "HIGH", "id_field": "DBInstanceIdentifier",
        "finding": "RDS production instance has deletion protection disabled",
        "recommendation": "Enable deletion protection:\n  aws rds modify-db-instance --db-instance-identifier <id> \\\n    --deletion-protection --apply-immediately",
        "meta": ["DBInstanceIdentifier", "DBInstanceClass", "Engine", "DeletionProtection"],
    },
    # ── iam-compliance.yml ──
    "iam-unused-access-key": {
        "severity": "HIGH", "id_field": "UserName",
        "finding": "IAM access key not rotated in 90+ days — long-lived credential risk",
        "recommendation": "Create new key, update applications, then deactivate old key:\n  aws iam create-access-key --user-name <user>\n  aws iam update-access-key --access-key-id <old-key> --status Inactive --user-name <user>",
        "meta": ["UserName", "CreateDate", "PasswordLastUsed"],
    },
    "iam-overly-broad-policy": {
        "severity": "CRITICAL", "id_field": "PolicyName",
        "finding": "IAM policy contains wildcard Action ('*') or Resource ('*') — violates least-privilege",
        "recommendation": "Replace wildcard statements with specific actions and resources.\n  Review: aws iam get-policy-version --policy-arn <arn> --version-id v1",
        "meta": ["PolicyName", "PolicyId", "CreateDate", "UpdateDate"],
    },
    "iam-unused-role": {
        "severity": "HIGH", "id_field": "RoleName",
        "finding": "IAM role not used in 90+ days — dormant permissions present risk",
        "recommendation": "Delete or disable if confirmed unused:\n  aws iam delete-role --role-name <RoleName>\n  (remove attached policies and instance profiles first)",
        "meta": ["RoleName", "CreateDate", "RoleLastUsed.LastUsedDate"],
    },
    "iam-user-inline-policy": {
        "severity": "MEDIUM", "id_field": "UserName",
        "finding": "IAM user has inline or directly-attached policies — should use groups",
        "recommendation": "Move permissions to an IAM group and add the user to the group:\n  aws iam attach-group-policy / aws iam add-user-to-group",
        "meta": ["UserName", "CreateDate"],
    },
    # ── cloudtrail-compliance.yml ──
    "cloudtrail-not-logging": {
        "severity": "CRITICAL", "id_field": "TrailARN",
        "finding": "CloudTrail trail exists but logging is disabled — API activity not recorded",
        "recommendation": "Enable logging immediately:\n  aws cloudtrail start-logging --name <trail-name>",
        "meta": ["Name", "HomeRegion", "IsMultiRegionTrail", "HasCustomEventSelectors"],
    },
    "cloudtrail-no-log-validation": {
        "severity": "HIGH", "id_field": "TrailARN",
        "finding": "CloudTrail log file validation disabled — logs may be tampered with undetected",
        "recommendation": "Enable log file validation:\n  aws cloudtrail update-trail --name <trail-name> --enable-log-file-validation",
        "meta": ["Name", "HomeRegion", "LogFileValidationEnabled"],
    },
    "cloudtrail-no-kms-encryption": {
        "severity": "MEDIUM", "id_field": "TrailARN",
        "finding": "CloudTrail logs not encrypted with KMS — S3 SSE-S3 only",
        "recommendation": "Encrypt trail logs with a KMS CMK:\n  aws cloudtrail update-trail --name <trail-name> --kms-key-id <key-arn>",
        "meta": ["Name", "HomeRegion", "KMSKeyId"],
    },
    "cloudtrail-no-cloudwatch-logs": {
        "severity": "MEDIUM", "id_field": "TrailARN",
        "finding": "CloudTrail not integrated with CloudWatch Logs — no real-time alerting",
        "recommendation": "Enable CloudWatch Logs integration for real-time security monitoring:\n  aws cloudtrail update-trail --name <trail-name> --cloud-watch-logs-log-group-arn <arn>",
        "meta": ["Name", "HomeRegion", "CloudWatchLogsLogGroupArn"],
    },
    # ── vpc-compliance.yml ──
    "vpc-no-flow-logs": {
        "severity": "HIGH", "id_field": "VpcId",
        "finding": "VPC has no flow logs enabled — network traffic not logged for security analysis",
        "recommendation": "Enable VPC flow logs:\n  aws ec2 create-flow-logs --resource-type VPC --resource-ids <VpcId> \\\n    --traffic-type ALL --log-destination-type cloud-watch-logs \\\n    --log-group-name /aws/vpc/flowlogs",
        "meta": ["VpcId", "CidrBlock", "State", "IsDefault"],
    },
    "vpc-default-in-use": {
        "severity": "MEDIUM", "id_field": "VpcId",
        "finding": "Default VPC contains EC2 instances — workloads should use custom VPCs",
        "recommendation": "Migrate workloads to a custom VPC with proper network segmentation.\n  The default VPC should have no running instances.",
        "meta": ["VpcId", "CidrBlock", "IsDefault"],
    },
    "subnet-auto-assign-public-ip": {
        "severity": "MEDIUM", "id_field": "SubnetId",
        "finding": "Subnet auto-assigns public IPs — instances launched here are internet-exposed",
        "recommendation": "Disable MapPublicIpOnLaunch:\n  aws ec2 modify-subnet-attribute --subnet-id <SubnetId> --no-map-public-ip-on-launch",
        "meta": ["SubnetId", "VpcId", "CidrBlock", "AvailabilityZone"],
    },
    "igw-attached-non-prod-vpc": {
        "severity": "MEDIUM", "id_field": "InternetGatewayId",
        "finding": "Internet Gateway attached to a non-production VPC — verify necessity",
        "recommendation": "For egress-only access, replace the IGW with a NAT Gateway.\n  For dev/staging, consider removing internet access entirely.",
        "meta": ["InternetGatewayId", "Attachments"],
    },
    # ── secretsmanager-compliance.yml ──
    "secret-not-rotated": {
        "severity": "HIGH", "id_field": "Name",
        "finding": "Secrets Manager secret not rotated in 90+ days",
        "recommendation": "Enable automatic rotation:\n  aws secretsmanager rotate-secret --secret-id <name>\n  Or configure rotation Lambda for custom rotation.",
        "meta": ["Name", "ARN", "LastRotatedDate", "RotationEnabled"],
    },
    "secret-rotation-disabled": {
        "severity": "MEDIUM", "id_field": "Name",
        "finding": "Secrets Manager secret has automatic rotation disabled",
        "recommendation": "Enable automatic rotation with a schedule:\n  aws secretsmanager rotate-secret --secret-id <name> \\\n    --rotation-rules AutomaticallyAfterDays=90",
        "meta": ["Name", "ARN", "RotationEnabled", "LastChangedDate"],
    },
    "secret-missing-tags": {
        "severity": "LOW", "id_field": "Name",
        "finding": "Secrets Manager secret missing Owner or Environment tag",
        "recommendation": "Add tags to identify secret ownership:\n  aws secretsmanager tag-resource --secret-id <name> \\\n    --tags Key=Owner,Value=team Key=Environment,Value=prod",
        "meta": ["Name", "ARN", "LastChangedDate"],
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
    "ebs":            ["ebs-unattached.yml", "ebs-optimization.yml"],
    "ebs-optimize":   ["ebs-optimization.yml"],
    "ec2":            ["ec2-instances.yml", "ec2-security.yml"],
    "ec2-security":   ["ec2-security.yml"],
    "eni":            ["eni-cleanup.yml"],
    "ami":            ["ami-unused-cleanup.yml"],
    "rds":            ["rds-security.yml"],
    "iam":            ["iam-compliance.yml"],
    "cloudtrail":     ["cloudtrail-compliance.yml"],
    "vpc":            ["vpc-compliance.yml"],
    "secretsmanager": ["secretsmanager-compliance.yml"],
    "security":       ["ec2-security.yml", "s3-security-compliance.yml", "ebs-optimization.yml",
                       "rds-security.yml", "iam-compliance.yml", "cloudtrail-compliance.yml",
                       "vpc-compliance.yml", "secretsmanager-compliance.yml"],
    "cost":           ["ebs-unattached.yml", "ebs-optimization.yml", "eni-cleanup.yml",
                       "ami-unused-cleanup.yml", "ec2-instances.yml",
                       "s3-cost-optimization.yml", "s3-infrequent-access-lifecycle.yml"],
    "all":            ["ec2-security.yml", "ec2-instances.yml",
                       "s3-security-compliance.yml", "s3-cost-optimization.yml", "s3-infrequent-access-lifecycle.yml",
                       "ebs-unattached.yml", "ebs-optimization.yml",
                       "eni-cleanup.yml", "ami-unused-cleanup.yml",
                       "rds-security.yml", "iam-compliance.yml",
                       "cloudtrail-compliance.yml", "vpc-compliance.yml", "secretsmanager-compliance.yml"],
}


def _iter_policy_files(base_dir):
    """Yield (relative_path, absolute_path) for every .yml/.yaml under base_dir."""
    for root, dirs, files in os.walk(base_dir):
        dirs.sort()
        for filename in sorted(files):
            if filename.endswith(".yml") or filename.endswith(".yaml"):
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, base_dir)
                yield rel_path, abs_path


def _build_policy_index():
    """
    Recursively scan all .yml/.yaml files under POLICY_DIR and build:
      policy_name → { "file": "subdir/file.yml", "policy": { ... } }
    Called once per Lambda cold start.
    """
    index = {}
    for rel_path, abs_path in _iter_policy_files(POLICY_DIR):
        try:
            with open(abs_path) as f:
                data = yaml.safe_load(f)
            for pol in data.get("policies", []):
                index[pol["name"]] = {
                    "file": rel_path,
                    "policy": pol,
                }
        except Exception as e:
            logger.warning(f"Failed to parse {rel_path}: {e}")
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
    # 1. "all" → every yml/yaml file recursively, no filter
    if policy_input == "all":
        return [
            {"file": abs_path}
            for _, abs_path in _iter_policy_files(POLICY_DIR)
        ]

    # 2. Group name → one or more files, no filter
    if policy_input in GROUP_MAP:
        return [
            {"file": os.path.join(POLICY_DIR, f)}
            for f in GROUP_MAP[policy_input]
            if os.path.exists(os.path.join(POLICY_DIR, f))
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
    for rel_path, abs_path in _iter_policy_files(POLICY_DIR):
        try:
            with open(abs_path) as f:
                data = yaml.safe_load(f)
            policies = [p["name"] for p in data.get("policies", [])]
            groups[rel_path] = policies
        except Exception:
            groups[rel_path] = []

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
        # EC2
        "stop":                  {"type": "stop"},
        "terminate":             {"type": "terminate"},
        "mark-for-op":           {"type": "mark-for-op", "tag": "c7n:marked-for-termination", "op": "terminate", "days": 14},
        "revoke":                {"type": "revoke"},
        # EBS / AMI
        "snapshot":              {"type": "snapshot"},
        "delete":                {"type": "delete"},
        "deregister":            {"type": "deregister"},
        # EIP
        "release":               {"type": "release"},
        # S3
        "set-bucket-encryption": {"type": "set-bucket-encryption", "crypto": "AES256"},
        "toggle-versioning":     {"type": "toggle-versioning", "enabled": True},
        "block-public-access":   {
            "type": "set-public-block",
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
        "enable-access-logging": {
            "type": "toggle-logging",
            "target_bucket": "access-logs",
            "target_prefix": "s3-access-logs/",
        },
        "enforce-ssl-policy": {
            "type": "set-statements",
            "statements": [{
                "Sid": "DenyNonSSL",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": ["arn:aws:s3:::{bucket_name}", "arn:aws:s3:::{bucket_name}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }],
        },
        # IAM
        "disable-login-profile":  {"type": "delete-login-profile"},
        "deactivate-access-keys": {"type": "deactivate-access-key"},
        "detach-policy":          {"type": "detach"},
        # CloudTrail
        "enable-trail-logging":   {"type": "enable"},
        "enable-log-validation":  {"type": "update-trail", "EnableLogFileValidation": True},
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
