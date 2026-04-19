"""
Local mock API server for UI development.
Returns realistic simulated resources with recommendations.

Usage: python mock-api.py
Runs on http://localhost:8080
"""

import json
import os
import random
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policies")

# ---------------------------------------------------------------------------
# Realistic mock data generators per resource type
# ---------------------------------------------------------------------------

MOCK_BUCKET_NAMES = [
    "prod-data-lake-raw", "staging-app-logs", "dev-ml-training-data",
    "analytics-reports-2024", "backup-database-daily", "media-assets-cdn",
    "compliance-audit-trail", "data-pipeline-temp", "legacy-app-exports",
    "customer-uploads-archive", "infra-cloudtrail-logs", "marketing-campaigns",
]

MOCK_INSTANCE_IDS = [f"i-0{random.randint(10000000,99999999):08x}" for _ in range(15)]
MOCK_VOLUME_IDS = [f"vol-0{random.randint(10000000,99999999):08x}" for _ in range(15)]
MOCK_ENI_IDS = [f"eni-0{random.randint(10000000,99999999):08x}" for _ in range(10)]
MOCK_AMI_IDS = [f"ami-0{random.randint(10000000,99999999):08x}" for _ in range(10)]
MOCK_SG_IDS = [f"sg-0{random.randint(10000000,99999999):08x}" for _ in range(10)]
MOCK_EIP_IDS = [f"eipalloc-0{random.randint(10000000,99999999):08x}" for _ in range(6)]
MOCK_SNAP_IDS = [f"snap-0{random.randint(10000000,99999999):08x}" for _ in range(10)]

INSTANCE_TYPES_OLD = ["m4.large", "m4.xlarge", "c4.2xlarge", "t2.medium", "r3.xlarge", "i2.xlarge"]
INSTANCE_TYPES_NEW = ["m6i.large", "c6i.xlarge", "t3.medium", "r6i.large"]

REGIONS = ["us-east-1a", "us-east-1b", "us-west-2a", "eu-west-1c"]

def _rand_date(days_back_min, days_back_max):
    d = datetime.utcnow() - timedelta(days=random.randint(days_back_min, days_back_max))
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")

def _rand_size():
    return random.choice([8, 20, 50, 100, 200, 500, 1000, 2000])

# -- Per-policy mock resource + recommendation generators --

POLICY_MOCKS = {
    # === S3 LIFECYCLE ===
    "s3-low-access-suggest-lifecycle": lambda: _s3_mock(
        "LOW ACCESS — Lifecycle Policy Recommended",
        "This bucket has fewer than 100 GET requests in the last 14 days but has no lifecycle policy.",
        "Add a lifecycle rule to transition objects to S3 Infrequent Access after 30 days, "
        "and to S3 Glacier after 90 days. Estimated savings: 40-60% on storage costs.",
        [("GetRequests (14d)", lambda: str(random.randint(2, 95))),
         ("BucketSizeBytes", lambda: f"{random.randint(5, 500)} GB"),
         ("StorageClass", lambda: "STANDARD")],
    ),
    "s3-zero-access-30d-deep-archive": lambda: _s3_mock(
        "ZERO ACCESS 30 DAYS — Deep Archive Candidate",
        "This bucket has had absolutely zero read requests in the past 30 days.",
        "Transition all objects to S3 Glacier Deep Archive. This is the cheapest storage class "
        "at $0.00099/GB/month (vs $0.023/GB for Standard). Add a lifecycle rule:\n"
        "  - Transition to DEEP_ARCHIVE after 1 day\n"
        "  - Or if data may be needed occasionally, use GLACIER (retrieval in 3-5 hours)",
        [("GetRequests (30d)", lambda: "0"),
         ("BucketSizeBytes", lambda: f"{random.randint(10, 2000)} GB"),
         ("EstimatedMonthlySavings", lambda: f"${random.randint(5, 200)}")],
    ),
    "s3-ia-missing-glacier-transition": lambda: _s3_mock(
        "HAS IA BUT NO GLACIER — Add Deeper Tier",
        "Bucket has lifecycle transitioning to STANDARD_IA but does not transition to Glacier.",
        "Add a Glacier transition rule after 90-180 days from object creation. Objects rarely "
        "accessed after IA transition are strong candidates for Glacier ($0.004/GB vs $0.0125/GB for IA).",
        [("CurrentLifecycle", lambda: "STANDARD -> STANDARD_IA @ 30 days"),
         ("SuggestedAddition", lambda: "STANDARD_IA -> GLACIER @ 90 days")],
    ),
    "s3-missing-lifecycle": lambda: _s3_mock(
        "NO LIFECYCLE RULE — Objects Never Transition to IA/Glacier",
        "Bucket has no lifecycle policy. All objects remain in S3 Standard storage indefinitely.",
        "Add a lifecycle rule to transition objects to cheaper storage classes:\n"
        "  Standard → Standard-IA after 30 days\n"
        "  Standard-IA → Glacier after 90 days\n"
        "  Glacier → Deep Archive after 180 days\n\n"
        "aws s3api put-bucket-lifecycle-configuration --bucket BUCKET --lifecycle-configuration file://lifecycle.json",
        [("LifecycleRules", lambda: "None"), ("BucketAge", lambda: f"{random.randint(90, 730)} days")],
    ),
    "s3-large-bucket-low-access": lambda: _s3_mock(
        "LARGE BUCKET, LOW ACCESS — Storage Class Optimization Needed",
        "Bucket exceeds 50 GB but has fewer than 500 GET requests in 14 days.",
        "Enable S3 Intelligent-Tiering to automatically move objects between access tiers. "
        "Or add manual lifecycle rules:\n"
        "  - STANDARD -> STANDARD_IA after 30 days\n"
        "  - STANDARD_IA -> GLACIER after 90 days\n"
        "  - GLACIER -> DEEP_ARCHIVE after 180 days",
        [("BucketSizeBytes", lambda: f"{random.randint(50, 5000)} GB"),
         ("GetRequests (14d)", lambda: str(random.randint(10, 490))),
         ("EstimatedMonthlySavings", lambda: f"${random.randint(20, 500)}")],
    ),
    "s3-enable-request-metrics": lambda: _s3_mock(
        "REQUEST METRICS NOT ENABLED",
        "CloudWatch request metrics are not enabled on this bucket.",
        "Enable S3 request metrics to measure access frequency. Without metrics, we cannot "
        "determine if this bucket is a lifecycle optimization candidate.\n\n"
        "Run: aws s3api put-bucket-metrics-configuration --bucket BUCKET_NAME "
        "--id EntireBucket --metrics-configuration '{\"Id\": \"EntireBucket\"}'",
        [("MetricsStatus", lambda: "Not Configured")],
    ),

    # === S3 SECURITY ===
    "s3-public-access-check": lambda: _s3_mock(
        "PUBLIC ACCESS ENABLED — SECURITY RISK",
        "Public access block is not fully enabled. Bucket or objects may be publicly accessible.",
        "Enable all four public access block settings immediately:\n"
        "  aws s3api put-public-access-block --bucket BUCKET --public-access-block-configuration "
        "'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'",
        [("BlockPublicAcls", lambda: random.choice(["false", "true"])),
         ("BlockPublicPolicy", lambda: "false"),
         ("Severity", lambda: "CRITICAL")],
    ),
    "s3-no-encryption": lambda: _s3_mock(
        "NO DEFAULT ENCRYPTION — Auto-Enabled AES-256",
        "Bucket did not have default server-side encryption. AES-256 has been auto-applied.",
        "Encryption at rest is now enabled with AES-256. For sensitive data, consider upgrading "
        "to AWS KMS (SSE-KMS) for key rotation and audit trail via CloudTrail.",
        [("EncryptionBefore", lambda: "None"),
         ("EncryptionAfter", lambda: "AES-256 (auto-applied)"),
         ("Severity", lambda: "HIGH")],
    ),
    "s3-no-versioning": lambda: _s3_mock(
        "VERSIONING DISABLED — Data Loss Risk",
        "Bucket versioning is not enabled. Accidental deletions or overwrites are permanent.",
        "Enable versioning: aws s3api put-bucket-versioning --bucket BUCKET "
        "--versioning-configuration Status=Enabled\n\n"
        "Also add a lifecycle rule to expire non-current versions after 30-90 days to control costs.",
        [("Versioning", lambda: "Disabled"), ("Severity", lambda: "MEDIUM")],
    ),
    "s3-no-access-logging": lambda: _s3_mock(
        "ACCESS LOGGING DISABLED",
        "Server access logging is not enabled. No audit trail for bucket access.",
        "Enable access logging to a dedicated log bucket:\n"
        "  aws s3api put-bucket-logging --bucket BUCKET --bucket-logging-status "
        "'{\"LoggingEnabled\":{\"TargetBucket\":\"your-log-bucket\",\"TargetPrefix\":\"s3-logs/\"}}'",
        [("Logging", lambda: "Disabled"), ("Severity", lambda: "MEDIUM")],
    ),
    "s3-no-mfa-delete": lambda: _s3_mock(
        "MFA DELETE NOT ENABLED",
        "Bucket is versioned but MFA delete is not required. Compromised credentials could delete versions.",
        "Enable MFA delete for critical data buckets. Requires root account credentials.",
        [("Versioning", lambda: "Enabled"), ("MFADelete", lambda: "Disabled"), ("Severity", lambda: "LOW")],
    ),
    "s3-no-ssl-enforcement": lambda: _s3_mock(
        "SSL NOT ENFORCED — HTTP ACCESS ALLOWED",
        "Bucket policy does not deny non-SSL (HTTP) requests. Data in transit may be unencrypted.",
        "Add a bucket policy to deny all non-HTTPS requests:\n"
        '  {"Effect":"Deny","Principal":"*","Action":"s3:*",'
        '"Resource":"arn:aws:s3:::BUCKET/*",'
        '"Condition":{"Bool":{"aws:SecureTransport":"false"}}}',
        [("SSLEnforced", lambda: "No"), ("Severity", lambda: "HIGH")],
    ),
    "s3-overly-permissive-policy": lambda: _s3_mock(
        "OVERLY PERMISSIVE — Principal: * in Policy",
        "Bucket policy grants access to all AWS accounts (Principal: *).",
        "Review and restrict the bucket policy. Replace Principal: * with specific account IDs "
        "or IAM roles. If cross-account access is needed, use explicit account ARNs with conditions.",
        [("Principal", lambda: "*"), ("Effect", lambda: "Allow"), ("Severity", lambda: "CRITICAL")],
    ),
    "s3-empty-buckets": lambda: _s3_mock(
        "EMPTY BUCKET — Consider Deletion",
        "Bucket has zero objects. It may be a leftover from a decommissioned project.",
        "Verify this bucket is no longer needed. If safe, delete it to reduce clutter:\n"
        "  aws s3 rb s3://BUCKET_NAME\n\nCheck CloudTrail for recent access before deleting.",
        [("ObjectCount", lambda: "0"), ("LastAccessed", lambda: _rand_date(60, 365))],
    ),
    "s3-untagged-buckets": lambda: _s3_mock(
        "MISSING REQUIRED TAGS",
        "Bucket is missing Owner, Environment, and/or Project tags needed for cost allocation.",
        "Add required tags for governance:\n"
        "  aws s3api put-bucket-tagging --bucket BUCKET --tagging "
        "'TagSet=[{Key=Owner,Value=team-name},{Key=Environment,Value=prod},{Key=Project,Value=project-name}]'",
        [("MissingTags", lambda: random.choice(["Owner, Environment", "Owner, Project", "All three"]))],
    ),
    "s3-replication-no-lifecycle": lambda: _s3_mock(
        "REPLICATION WITHOUT LIFECYCLE",
        "Cross-region replication is enabled but no lifecycle policy exists. Replicated data accumulates forever.",
        "Add lifecycle rules to both source and destination buckets to expire or transition old data.",
        [("Replication", lambda: "Enabled"), ("Lifecycle", lambda: "None"), ("Severity", lambda: "MEDIUM")],
    ),

    # === S3 COST ===
    "s3-incomplete-multipart-uploads": lambda: _s3_mock(
        "ORPHANED MULTIPART UPLOADS POSSIBLE",
        "No lifecycle rule to abort incomplete multipart uploads. These consume hidden storage.",
        "Add a lifecycle rule to abort incomplete multipart uploads after 7 days:\n"
        '  {"Rules":[{"ID":"abort-multipart","Status":"Enabled",'
        '"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}',
        [("MultipartCleanupRule", lambda: "Missing"),
         ("EstimatedWaste", lambda: f"{random.randint(1, 50)} GB potentially")],
    ),
    "s3-versioned-no-noncurrent-expiration": lambda: _s3_mock(
        "NON-CURRENT VERSIONS ACCUMULATING",
        "Versioned bucket without a lifecycle rule to expire old versions. Storage cost grows silently.",
        "Add lifecycle rule to expire non-current versions after 30 days:\n"
        '  {"Rules":[{"ID":"expire-old-versions","Status":"Enabled",'
        '"NoncurrentVersionExpiration":{"NoncurrentDays":30}}]}',
        [("Versioning", lambda: "Enabled"),
         ("NoncurrentExpiration", lambda: "Not configured"),
         ("EstimatedWaste", lambda: f"{random.randint(5, 200)} GB of old versions")],
    ),
    "s3-standard-storage-high-cost": lambda: _s3_mock(
        "HIGH COST — USE INTELLIGENT TIERING",
        "Over 100 GB in Standard storage with under 1000 reads/month.",
        "Switch to S3 Intelligent-Tiering ($0.0025/1000 objects monitoring fee) to automatically "
        "optimize. Or add manual lifecycle transitions.",
        [("BucketSize", lambda: f"{random.randint(100, 5000)} GB"),
         ("MonthlyGETRequests", lambda: str(random.randint(50, 990))),
         ("EstimatedMonthlySavings", lambda: f"${random.randint(30, 400)}")],
    ),
    "s3-transfer-acceleration-unused": lambda: _s3_mock(
        "TRANSFER ACCELERATION ENABLED BUT UNUSED",
        "Transfer acceleration is active but the bucket has very low transfer volume.",
        "Disable transfer acceleration to avoid the per-GB surcharge:\n"
        "  aws s3api put-bucket-accelerate-configuration --bucket BUCKET "
        "--accelerate-configuration Status=Suspended",
        [("AccelerationStatus", lambda: "Enabled"),
         ("TransferVolume (30d)", lambda: f"{random.randint(0, 5)} GB")],
    ),

    # === EC2 INSTANCES ===
    "ec2-underutilised-instances": lambda: _ec2_mock(
        "UNDERUTILISED — Rightsize or Stop",
        "Average CPU below 10% for 14 days. This instance is likely oversized for its workload.",
        "Options:\n"
        "  1. Rightsize: Change from {type} to a smaller type (e.g., {smaller})\n"
        "  2. Stop if non-production during off-hours (use Instance Scheduler)\n"
        "  3. Use AWS Compute Optimizer for ML-based recommendations",
        [("AvgCPU (14d)", lambda: f"{random.uniform(0.5, 9.5):.1f}%"),
         ("InstanceType", lambda: random.choice(INSTANCE_TYPES_NEW)),
         ("EstimatedMonthlySavings", lambda: f"${random.randint(20, 300)}")],
    ),
    "ec2-stopped-30d": lambda: _ec2_mock(
        "STOPPED 30+ DAYS — Still Incurring EBS Charges",
        "Instance has been stopped for over 30 days but its EBS volumes still cost money.",
        "Create an AMI (snapshot) and terminate the instance:\n"
        "  aws ec2 create-image --instance-id INSTANCE_ID --name 'backup-before-terminate'\n"
        "  aws ec2 terminate-instances --instance-ids INSTANCE_ID\n\n"
        "EBS volumes attached to stopped instances cost ${ebs_cost}/month.",
        [("StoppedSince", lambda: _rand_date(30, 120)),
         ("AttachedEBSSize", lambda: f"{random.randint(20, 500)} GB"),
         ("MonthlyEBSCost", lambda: f"${random.randint(2, 50)}")],
    ),
    "ec2-stopped-60d-mark-terminate": lambda: _ec2_mock(
        "STOPPED 60+ DAYS — Marked for Termination (14-day grace)",
        "Instance has been stopped for over 60 days. It will be terminated in 14 days unless exempted.",
        "To keep this instance, remove the c7n:marked-for-termination tag.\n"
        "Otherwise, create an AMI backup now before the grace period expires.",
        [("StoppedSince", lambda: _rand_date(60, 200)),
         ("TerminationDate", lambda: (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")),
         ("Severity", lambda: "WARNING")],
    ),
    "ec2-missing-tags": lambda: _ec2_mock(
        "MISSING REQUIRED TAGS",
        "Instance is missing Owner, Environment, or Project tags.",
        "Add required tags for cost allocation and accountability:\n"
        "  aws ec2 create-tags --resources INSTANCE_ID --tags "
        "Key=Owner,Value=team Key=Environment,Value=prod Key=Project,Value=name",
        [("MissingTags", lambda: random.choice(["Owner", "Environment, Project", "Owner, Environment, Project"]))],
    ),
    "ec2-old-generation-instance-type": lambda: _ec2_mock(
        "OLD-GEN INSTANCE TYPE — Upgrade Available",
        "Running on previous-generation hardware. Newer generations offer 20-40% better price/performance.",
        "Upgrade path:\n"
        "  m4 -> m6i/m7i  |  c4 -> c6i/c7i  |  t2 -> t3/t3a\n"
        "  r3 -> r6i/r7i  |  i2 -> i3/i3en\n\n"
        "Stop instance, change type, start. Or use AWS Compute Optimizer.",
        [("CurrentType", lambda: random.choice(INSTANCE_TYPES_OLD)),
         ("RecommendedType", lambda: random.choice(INSTANCE_TYPES_NEW)),
         ("EstimatedSavings", lambda: f"{random.randint(15, 40)}%")],
    ),
    "ec2-no-detailed-monitoring": lambda: _ec2_mock(
        "BASIC MONITORING ONLY (5-min intervals)",
        "Detailed monitoring (1-min) is not enabled. Short CPU spikes may go undetected.",
        "Enable detailed monitoring ($3.50/instance/month):\n"
        "  aws ec2 monitor-instances --instance-ids INSTANCE_ID",
        [("MonitoringState", lambda: "basic (5-min)"),
         ("Recommendation", lambda: "Enable 1-min detailed monitoring")],
    ),
    "ec2-imdsv1-enabled": lambda: _ec2_mock(
        "SECURITY: IMDSv1 ALLOWED — SSRF Risk",
        "Instance Metadata Service v1 is enabled. This is vulnerable to Server-Side Request Forgery.",
        "Enforce IMDSv2 (HttpTokens=required):\n"
        "  aws ec2 modify-instance-metadata-options --instance-id INSTANCE_ID "
        "--http-tokens required --http-endpoint enabled",
        [("HttpTokens", lambda: "optional (IMDSv1 allowed)"),
         ("Severity", lambda: "HIGH"),
         ("Recommendation", lambda: "Set HttpTokens=required")],
    ),
    "ec2-public-ip-check": lambda: _ec2_mock(
        "PUBLIC IP ASSIGNED — Verify Intention",
        "Instance has a public IP address. Verify this is intentional and not an exposure risk.",
        "If the instance should be private:\n"
        "  1. Move to a private subnet behind an ALB\n"
        "  2. Use NAT Gateway for outbound access\n"
        "  3. Use VPN or AWS PrivateLink for inbound",
        [("PublicIP", lambda: f"{random.randint(3,54)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"),
         ("Severity", lambda: "MEDIUM")],
    ),
    "ec2-no-backup-tag": lambda: _ec2_mock(
        "NO BACKUP TAG — May Not Be in Backup Plan",
        "Instance does not have a Backup tag. AWS Backup plans typically select resources by tag.",
        "Add a Backup tag:\n"
        "  aws ec2 create-tags --resources INSTANCE_ID --tags Key=Backup,Value=daily",
        [("BackupTag", lambda: "absent"), ("Severity", lambda: "MEDIUM")],
    ),
    "ec2-long-running-no-ri": lambda: _ec2_mock(
        "RUNNING 1+ YEAR ON-DEMAND — Consider Reserved/Savings",
        "This instance has been running for over a year on on-demand pricing.",
        "Savings options:\n"
        "  - Reserved Instance (1yr no-upfront): save ~36%\n"
        "  - Reserved Instance (3yr all-upfront): save ~60%\n"
        "  - Compute Savings Plan: save ~30% with flexibility\n\n"
        "Check AWS Cost Explorer > Savings Plans recommendations.",
        [("RunningDays", lambda: str(random.randint(365, 1200))),
         ("InstanceType", lambda: random.choice(INSTANCE_TYPES_NEW)),
         ("EstimatedAnnualSavings", lambda: f"${random.randint(500, 5000)}")],
    ),

    # === EC2 SECURITY ===
    "sg-open-ssh": lambda: _sg_mock("CRITICAL: SSH (22) OPEN TO INTERNET",
        "Remove 0.0.0.0/0 from port 22. Use SSM Session Manager or restrict to office/VPN CIDR.",
        "22", "SSH"),
    "sg-open-rdp": lambda: _sg_mock("CRITICAL: RDP (3389) OPEN TO INTERNET",
        "Remove 0.0.0.0/0 from port 3389. Use a bastion host or AWS SSM.",
        "3389", "RDP"),
    "sg-all-ports-open": lambda: _sg_mock("CRITICAL: ALL PORTS OPEN TO INTERNET",
        "Security group allows all traffic from 0.0.0.0/0. Restrict to specific ports and CIDRs.",
        "0-65535", "ALL"),
    "sg-unused": lambda: ({
        "ResourceId": random.choice(MOCK_SG_IDS),
        "GroupName": random.choice(["launch-wizard-1", "old-ecs-task-sg", "temp-debug-sg", "legacy-app-sg"]),
        "Severity": "LOW",
        "Finding": "UNUSED SECURITY GROUP",
        "Description": "This security group is not attached to any EC2, ENI, RDS, or Lambda resource.",
        "Recommendation": "Delete to reduce clutter and audit complexity:\n"
                          "  aws ec2 delete-security-group --group-id SG_ID",
    }),
    "sg-open-database-ports": lambda: _sg_mock("CRITICAL: DATABASE PORTS OPEN TO INTERNET",
        "Database ports should never be exposed to 0.0.0.0/0. Restrict to application security groups only.",
        random.choice(["3306", "5432", "27017", "6379"]),
        random.choice(["MySQL", "PostgreSQL", "MongoDB", "Redis"])),
    "ec2-no-iam-role": lambda: _ec2_mock(
        "NO IAM ROLE — Using Access Keys?",
        "Instance has no IAM instance profile. It may be using hardcoded access keys (security anti-pattern).",
        "Create an IAM role with least-privilege permissions and attach it:\n"
        "  aws ec2 associate-iam-instance-profile --instance-id INSTANCE_ID "
        "--iam-instance-profile Name=your-role",
        [("IamProfile", lambda: "None"), ("Severity", lambda: "HIGH")],
    ),
    "ec2-has-key-pair": lambda: _ec2_mock(
        "SSH KEY PAIR — Consider SSM Session Manager",
        "Instance was launched with an SSH key pair. SSM Session Manager is more secure (no open ports).",
        "Migrate to SSM:\n"
        "  1. Attach AmazonSSMManagedInstanceCore IAM policy\n"
        "  2. Install SSM Agent (pre-installed on Amazon Linux 2/2023)\n"
        "  3. Remove port 22 from security group\n"
        "  4. Connect: aws ssm start-session --target INSTANCE_ID",
        [("KeyName", lambda: random.choice(["prod-key", "dev-team-key", "legacy-ssh-key"])),
         ("Severity", lambda: "LOW")],
    ),

    # === EBS ===
    "ebs-unattached-volumes": lambda: _ebs_mock(
        "UNATTACHED VOLUME — Wasting Money",
        "EBS volume is in 'available' state, not attached to any instance.",
        "Review if still needed. If not, snapshot and delete:\n"
        "  aws ec2 create-snapshot --volume-id VOL_ID --description 'backup before delete'\n"
        "  aws ec2 delete-volume --volume-id VOL_ID",
    ),
    "ebs-unattached-30d-cleanup": lambda: _ebs_mock(
        "UNATTACHED 30+ DAYS — Snapshot Created, Volume Deleted",
        "Volume was unattached for over 30 days. A snapshot was created and the volume was removed.",
        "No action needed. Snapshot is available for restore if needed.",
    ),
    "ebs-unattached-mark-for-deletion": lambda: _ebs_mock(
        "UNATTACHED — Marked for Deletion in 14 Days",
        "Volume is unattached and has been marked. It will be deleted in 14 days unless the tag is removed.",
        "To keep: remove tag c7n:marked-for-deletion\nTo delete now: aws ec2 delete-volume --volume-id VOL_ID",
    ),
    "ebs-gp2-upgrade-to-gp3": lambda: ({
        "ResourceId": random.choice(MOCK_VOLUME_IDS),
        "VolumeType": "gp2",
        "Size": f"{random.choice([20, 50, 100, 200, 500])} GB",
        "AZ": random.choice(REGIONS),
        "Severity": "COST",
        "Finding": "GP2 VOLUME — Upgrade to GP3 for 20% Savings",
        "Description": "gp3 offers 3000 IOPS and 125 MB/s baseline (vs gp2's burst-dependent performance) at 20% lower cost.",
        "Recommendation": f"Modify volume type (no downtime, no detach needed):\n"
                          f"  aws ec2 modify-volume --volume-id VOL_ID --volume-type gp3\n\n"
                          f"Estimated savings: ${random.randint(2, 30)}/month for this volume.",
    }),
    "ebs-overprovisioned-iops": lambda: ({
        "ResourceId": random.choice(MOCK_VOLUME_IDS),
        "VolumeType": random.choice(["io1", "io2"]),
        "ProvisionedIOPS": random.randint(3000, 16000),
        "ActualUsage": f"{random.randint(50, 500)} IOPS avg",
        "Severity": "COST",
        "Finding": "OVER-PROVISIONED IOPS — Downgrade to GP3",
        "Description": "Provisioned IOPS volume is using less than 10% of its IOPS capacity.",
        "Recommendation": "Downgrade to gp3 (3000 IOPS baseline free) or reduce provisioned IOPS.\n"
                          f"Estimated savings: ${random.randint(50, 500)}/month",
    }),
    "ebs-unencrypted": lambda: _ebs_mock(
        "UNENCRYPTED VOLUME — Security Risk",
        "EBS volume is not encrypted at rest. Enable default encryption at account level.",
        "Cannot encrypt existing volume in-place. Create encrypted snapshot and new volume:\n"
        "  aws ec2 create-snapshot --volume-id VOL_ID\n"
        "  aws ec2 copy-snapshot --encrypted --source-snapshot-id SNAP_ID\n\n"
        "Enable default encryption: aws ec2 enable-ebs-encryption-by-default",
    ),
    "ebs-untagged": lambda: _ebs_mock(
        "MISSING NAME TAG",
        "Volume has no Name tag, making it impossible to identify owner or purpose.",
        "Add a Name tag: aws ec2 create-tags --resources VOL_ID --tags Key=Name,Value=description",
    ),
    "ebs-old-snapshots": lambda: ({
        "ResourceId": random.choice(MOCK_SNAP_IDS),
        "Age": f"{random.randint(180, 730)} days",
        "Size": f"{random.choice([8, 20, 50, 100, 500])} GB",
        "Severity": "COST",
        "Finding": "SNAPSHOT OLDER THAN 180 DAYS",
        "Description": "Old snapshots accumulate storage costs. Review if still needed.",
        "Recommendation": "Delete if no longer needed:\n  aws ec2 delete-snapshot --snapshot-id SNAP_ID\n\n"
                          f"Estimated cost: ${random.randint(1, 25)}/month",
    }),
    "ebs-orphaned-snapshots": lambda: ({
        "ResourceId": random.choice(MOCK_SNAP_IDS),
        "SourceVolume": f"vol-{random.randint(10000000,99999999):08x} (DELETED)",
        "Severity": "COST",
        "Finding": "ORPHANED SNAPSHOT — Source Volume Deleted",
        "Description": "The source volume for this snapshot no longer exists. Snapshot is likely safe to delete.",
        "Recommendation": "Verify no AMIs depend on this snapshot, then delete:\n"
                          "  aws ec2 describe-images --filters Name=block-device-mapping.snapshot-id,Values=SNAP_ID\n"
                          "  aws ec2 delete-snapshot --snapshot-id SNAP_ID",
    }),
    "ebs-large-low-throughput": lambda: _ebs_mock(
        "LARGE VOLUME, LOW THROUGHPUT — Consider Resizing",
        "Volume exceeds 500 GB but has less than 1 GB of writes in 14 days.",
        "This volume may be significantly oversized. Resize to match actual data usage:\n"
        "  1. Check actual disk usage on the instance (df -h)\n"
        "  2. Create snapshot\n"
        "  3. Create smaller volume from snapshot\n"
        "  4. Swap volumes",
    ),

    # === ENI / EIP ===
    "eni-unattached": lambda: ({
        "ResourceId": random.choice(MOCK_ENI_IDS),
        "Status": "available",
        "AZ": random.choice(REGIONS),
        "Severity": "COST",
        "Finding": "UNATTACHED ENI",
        "Description": "Network interface is not attached to any instance. Likely orphaned from terminated instance or failed deployment.",
        "Recommendation": "Delete if not needed:\n  aws ec2 delete-network-interface --network-interface-id ENI_ID",
    }),
    "eni-unattached-30d-cleanup": lambda: ({
        "ResourceId": random.choice(MOCK_ENI_IDS),
        "Status": "available",
        "Severity": "COST",
        "Finding": "UNATTACHED ENI — Marked for Deletion (7-day grace)",
        "Description": "ENI has been unattached for over 30 days. Marked for auto-deletion.",
        "Recommendation": "Remove tag c7n:marked-for-deletion to keep. Otherwise it will be deleted in 7 days.",
    }),
    "eni-marked-delete": lambda: ({
        "ResourceId": random.choice(MOCK_ENI_IDS),
        "Severity": "INFO",
        "Finding": "ENI DELETED",
        "Description": "Orphaned ENI was deleted after grace period expired.",
        "Recommendation": "No action needed.",
    }),
    "eni-untagged": lambda: ({
        "ResourceId": random.choice(MOCK_ENI_IDS),
        "Severity": "LOW",
        "Finding": "UNTAGGED ENI — Cannot Identify Owner",
        "Description": "ENI has no Name tag. Impossible to determine which team or service created it.",
        "Recommendation": "Add a Name tag or delete if orphaned.",
    }),
    "eip-unattached": lambda: ({
        "ResourceId": random.choice(MOCK_EIP_IDS),
        "PublicIP": f"{random.randint(3,54)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
        "Severity": "COST",
        "Finding": "UNATTACHED ELASTIC IP — $3.65/month Waste",
        "Description": "Elastic IP is not associated with any running instance. AWS charges $0.005/hr for unattached EIPs.",
        "Recommendation": "Release if not needed:\n  aws ec2 release-address --allocation-id ALLOC_ID\n\n"
                          "Or attach to an instance to stop the charge.",
    }),
    "eip-unattached-release": lambda: ({
        "ResourceId": random.choice(MOCK_EIP_IDS),
        "Severity": "INFO",
        "Finding": "ELASTIC IP RELEASED",
        "Description": "Unattached EIP was released after grace period.",
        "Recommendation": "No action needed. $3.65/month saved.",
    }),

    # === AMI ===
    "ami-unused-detection": lambda: ({
        "ResourceId": random.choice(MOCK_AMI_IDS),
        "Name": random.choice(["web-server-v2.3", "api-golden-image-old", "ml-worker-base-2023", "legacy-app-v1.8"]),
        "CreatedDate": _rand_date(90, 500),
        "Severity": "COST",
        "Finding": "UNUSED AMI — Not Referenced by Any Instance",
        "Description": "No running or stopped EC2 instance uses this AMI. It may be from an old deployment.",
        "Recommendation": "Deregister if no longer needed. This also frees the associated EBS snapshots:\n"
                          "  aws ec2 deregister-image --image-id AMI_ID",
    }),
    "ami-unused-90d-mark": lambda: ({
        "ResourceId": random.choice(MOCK_AMI_IDS),
        "Name": random.choice(["old-base-image", "deprecated-app-v1", "test-ami-jan2024"]),
        "Age": f"{random.randint(90, 500)} days",
        "Severity": "WARNING",
        "Finding": "UNUSED AMI 90+ DAYS — Marked for Deregistration (14-day grace)",
        "Description": "AMI has been unused for over 90 days. It will be deregistered in 14 days.",
        "Recommendation": "Remove tag c7n:marked-for-deregister to keep.\n"
                          "Otherwise, ensure no launch templates reference this AMI.",
    }),
    "ami-unused-deregister": lambda: ({
        "ResourceId": random.choice(MOCK_AMI_IDS),
        "Severity": "INFO",
        "Finding": "AMI DEREGISTERED — Snapshots Deleted",
        "Description": "Unused AMI was deregistered and associated EBS snapshots were removed.",
        "Recommendation": "No action needed.",
    }),
    "ami-not-in-launch-config": lambda: ({
        "ResourceId": random.choice(MOCK_AMI_IDS),
        "Name": random.choice(["orphaned-packer-build", "manual-ami-backup", "ci-build-artifact"]),
        "Severity": "COST",
        "Finding": "AMI NOT IN ANY LAUNCH TEMPLATE OR ASG",
        "Description": "AMI is not referenced by any instance, launch template, or auto-scaling group.",
        "Recommendation": "Safe to deregister unless kept as a manual backup. Check with the team before deleting.",
    }),
}


def _s3_mock(finding, description, recommendation, extra_fields=None):
    bucket = random.choice(MOCK_BUCKET_NAMES)
    result = {
        "ResourceId": bucket,
        "BucketName": bucket,
        "Region": random.choice(["us-east-1", "us-west-2", "eu-west-1"]),
        "Severity": "MEDIUM",
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }
    if extra_fields:
        for key, val_fn in extra_fields:
            result[key] = val_fn()
    return result


def _ec2_mock(finding, description, recommendation, extra_fields=None):
    iid = random.choice(MOCK_INSTANCE_IDS)
    result = {
        "ResourceId": iid,
        "InstanceId": iid,
        "InstanceType": random.choice(INSTANCE_TYPES_NEW + INSTANCE_TYPES_OLD),
        "AZ": random.choice(REGIONS),
        "LaunchTime": _rand_date(1, 400),
        "Severity": "MEDIUM",
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }
    if extra_fields:
        for key, val_fn in extra_fields:
            result[key] = val_fn()
    return result


def _ebs_mock(finding, description, recommendation):
    vid = random.choice(MOCK_VOLUME_IDS)
    return {
        "ResourceId": vid,
        "VolumeId": vid,
        "VolumeType": random.choice(["gp2", "gp3", "io1"]),
        "Size": f"{_rand_size()} GB",
        "State": random.choice(["available", "in-use"]),
        "AZ": random.choice(REGIONS),
        "Severity": "COST",
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


def _sg_mock(finding, recommendation, port, service):
    sgid = random.choice(MOCK_SG_IDS)
    return {
        "ResourceId": sgid,
        "GroupName": random.choice(["default", "web-server-sg", "legacy-app-sg", "dev-open-sg"]),
        "Port": port,
        "Service": service,
        "Source": "0.0.0.0/0",
        "Severity": "CRITICAL",
        "Finding": finding,
        "Description": f"Security group allows {service} (port {port}) from 0.0.0.0/0 (entire internet).",
        "Recommendation": recommendation,
    }


MOCK_RDS_IDS    = [f"mydb-{random.randint(1000,9999)}" for _ in range(8)]
MOCK_TRAIL_ARNS = [f"arn:aws:cloudtrail:ap-south-1:123456789012:trail/trail-{i}" for i in range(4)]
MOCK_VPC_IDS    = [f"vpc-0{random.randint(10000000,99999999):08x}" for _ in range(6)]
MOCK_SUBNET_IDS = [f"subnet-0{random.randint(10000000,99999999):08x}" for _ in range(6)]
MOCK_IGW_IDS    = [f"igw-0{random.randint(10000000,99999999):08x}" for _ in range(4)]
MOCK_SECRET_IDS = [f"arn:aws:secretsmanager:ap-south-1:123456789012:secret:{n}" for n in
                   ["prod/db-password", "prod/api-key", "dev/service-token", "staging/smtp-creds"]]
MOCK_LAMBDA_IDS = [f"arn:aws:lambda:ap-south-1:123456789012:function:{n}" for n in
                   ["data-processor", "auth-service", "report-generator", "cleanup-job", "api-handler"]]
MOCK_IAM_USERS  = ["alice", "bob.dev", "svc-deploy", "admin-backup", "ci-runner", "legacy-tool"]
MOCK_IAM_ROLES  = [f"arn:aws:iam::123456789012:role/{n}" for n in
                   ["ec2-worker-role", "lambda-exec-role", "cross-account-role", "old-service-role"]]
MOCK_IAM_POLICIES = [f"arn:aws:iam::123456789012:policy/{n}" for n in
                     ["FullAdminAccess", "DevWildcardPolicy", "LegacySuperUser"]]
RDS_ENGINES = ["mysql", "postgres", "mariadb", "aurora-mysql"]
RDS_CLASSES  = ["db.r5.large", "db.r5.xlarge", "db.r6g.large", "db.m5.large", "db.t3.medium"]


def _rds_mock(finding, description, recommendation, severity="MEDIUM", extra_fields=None):
    rid = random.choice(MOCK_RDS_IDS)
    result = {
        "ResourceId": rid,
        "DBInstanceIdentifier": rid,
        "Engine": random.choice(RDS_ENGINES),
        "DBInstanceClass": random.choice(RDS_CLASSES),
        "MultiAZ": random.choice(["true", "false"]),
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }
    if extra_fields:
        for key, val_fn in extra_fields:
            result[key] = val_fn()
    return result


def _rds_snap_mock(finding, description, recommendation):
    sid = f"rds:mydb-{random.randint(1000,9999)}-{_rand_date(30,180)[:10]}"
    return {
        "ResourceId": sid,
        "DBSnapshotIdentifier": sid,
        "Engine": random.choice(RDS_ENGINES),
        "AllocatedStorage": f"{random.randint(20, 500)} GB",
        "Severity": "HIGH",
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


def _cloudtrail_mock(trail_name, finding, description, recommendation, severity="HIGH"):
    arn = f"arn:aws:cloudtrail:ap-south-1:123456789012:trail/{trail_name}"
    return {
        "ResourceId": arn,
        "TrailARN": arn,
        "Name": trail_name,
        "IsMultiRegionTrail": random.choice(["true", "false"]),
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


def _lambda_mock(finding, description, recommendation, severity="MEDIUM"):
    fname = random.choice(["data-processor", "auth-service", "report-generator", "cleanup-job", "api-handler"])
    arn   = f"arn:aws:lambda:ap-south-1:123456789012:function:{fname}"
    return {
        "ResourceId": arn,
        "FunctionName": fname,
        "Runtime": random.choice(["python3.9", "nodejs18.x", "java11"]),
        "LastModified": _rand_date(30, 400),
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


def _iam_user_mock(finding, description, recommendation, severity="HIGH", extra_fields=None):
    uname = random.choice(MOCK_IAM_USERS)
    result = {
        "ResourceId": uname,
        "UserName": uname,
        "CreateDate": _rand_date(180, 1000),
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }
    if extra_fields:
        for key, val_fn in extra_fields:
            result[key] = val_fn()
    return result


def _iam_role_mock(finding, description, recommendation, severity="HIGH", extra_fields=None):
    arn = random.choice(MOCK_IAM_ROLES)
    result = {
        "ResourceId": arn,
        "RoleName": arn.split("/")[-1],
        "CreateDate": _rand_date(180, 1000),
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }
    if extra_fields:
        for key, val_fn in extra_fields:
            result[key] = val_fn()
    return result


def _vpc_mock(finding, description, recommendation, severity="MEDIUM"):
    vid = random.choice(MOCK_VPC_IDS)
    return {
        "ResourceId": vid,
        "VpcId": vid,
        "CidrBlock": f"10.{random.randint(0,10)}.0.0/16",
        "IsDefault": "false",
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


def _secret_mock(finding, description, recommendation, severity="HIGH"):
    arn = random.choice(MOCK_SECRET_IDS)
    return {
        "ResourceId": arn,
        "Name": arn.split(":")[-1],
        "LastChangedDate": _rand_date(90, 400),
        "RotationEnabled": "false",
        "Severity": severity,
        "Finding": finding,
        "Description": description,
        "Recommendation": recommendation,
    }


# Additional mock entries for services missing from POLICY_MOCKS
POLICY_MOCKS_EXTRA = {
    # ── RDS ──
    "rds-public-access": lambda: _rds_mock(
        "RDS PUBLICLY ACCESSIBLE — CRITICAL SECURITY RISK",
        "PubliclyAccessible=true. This RDS instance can be reached directly from the internet.",
        "Set PubliclyAccessible=false immediately:\n  aws rds modify-db-instance --db-instance-identifier ID "
        "--no-publicly-accessible --apply-immediately",
        severity="CRITICAL",
    ),
    "rds-unencrypted": lambda: _rds_mock(
        "STORAGE NOT ENCRYPTED — Data At Rest Exposed",
        "RDS instance storage is not encrypted. Data-at-rest may be accessible if disk is compromised.",
        "Encryption cannot be enabled on existing instances. Snapshot + restore to new encrypted instance:\n"
        "  aws rds create-db-snapshot ...\n  aws rds restore-db-instance-from-db-snapshot --storage-encrypted",
        severity="HIGH",
    ),
    "rds-no-multi-az": lambda: _rds_mock(
        "SINGLE-AZ — No High Availability",
        "MultiAZ is disabled. An AZ outage will cause an unplanned downtime for this database.",
        "Enable Multi-AZ (incurs cost ~2x instance price, but eliminates single-AZ SPOF):\n"
        "  aws rds modify-db-instance --db-instance-identifier ID --multi-az --apply-immediately",
        severity="MEDIUM", extra_fields=[("MultiAZ", lambda: "false")],
    ),
    "rds-no-backup": lambda: _rds_mock(
        "BACKUP RETENTION < 7 DAYS — Data Loss Risk",
        "Automated backup retention period is less than 7 days. Point-in-time recovery window is too short.",
        "Set backup retention to at least 7 days:\n"
        "  aws rds modify-db-instance --db-instance-identifier ID --backup-retention-period 7",
        severity="HIGH", extra_fields=[("BackupRetentionPeriod", lambda: str(random.randint(0, 3)))],
    ),
    "rds-no-deletion-protection": lambda: _rds_mock(
        "DELETION PROTECTION DISABLED",
        "RDS instance can be deleted without any guard. A misconfigured script or mistake could destroy it.",
        "Enable deletion protection:\n"
        "  aws rds modify-db-instance --db-instance-identifier ID --deletion-protection --apply-immediately",
        severity="HIGH",
    ),
    "rds-old-snapshot": lambda: _rds_snap_mock(
        "MANUAL SNAPSHOT OLDER THAN 90 DAYS",
        "This manual RDS snapshot is older than 90 days. Old snapshots accumulate storage cost.",
        "Delete if no longer needed:\n  aws rds delete-db-snapshot --db-snapshot-identifier ID",
    ),
    "rds-snapshot-unencrypted": lambda: _rds_snap_mock(
        "SNAPSHOT NOT ENCRYPTED",
        "This RDS snapshot is stored unencrypted. Anyone with S3 access to the backup could read it.",
        "Copy the snapshot with encryption enabled:\n"
        "  aws rds copy-db-snapshot --source-db-snapshot-identifier ID "
        "--target-db-snapshot-identifier ID-encrypted --kms-key-id alias/aws/rds",
    ),
    "rds-idle-instance": lambda: _rds_mock(
        "ZERO DB CONNECTIONS FOR 14 DAYS — Likely Idle",
        "No database connections recorded in the past 14 days. Instance may be abandoned.",
        "Verify this instance is no longer in use, then stop or delete:\n"
        "  aws rds stop-db-instance --db-instance-identifier ID\n"
        "Or delete with final snapshot: aws rds delete-db-instance --final-db-snapshot-identifier ...",
        severity="COST",
    ),
    "rds-stopped-7d": lambda: _rds_mock(
        "STOPPED INSTANCE — AWS Will Auto-Restart in 7 Days",
        "AWS automatically restarts stopped RDS instances after 7 days. "
        "If this is intentional, you must stop it again or delete it.",
        "If no longer needed, delete with a final snapshot:\n"
        "  aws rds delete-db-instance --db-instance-identifier ID "
        "--final-db-snapshot-identifier final-backup",
        severity="COST",
    ),
    "rds-oversized-instance": lambda: _rds_mock(
        "MEMORY-OPTIMISED CLASS WITH LOW USAGE — Downsize",
        "Running on db.r5/r6 class but CPU and connections are consistently low.",
        "Downsize to db.t3.medium or db.m5.large and monitor. Estimated savings: 40-60%.\n"
        "  aws rds modify-db-instance --db-instance-identifier ID --db-instance-class db.t3.medium",
        severity="COST", extra_fields=[("AvgCPU (14d)", lambda: f"{random.uniform(0.5, 5.0):.1f}%")],
    ),
    "rds-no-reserved-instance": lambda: _rds_mock(
        "ON-DEMAND 90+ DAYS — No Reserved Instance",
        "This instance has been running on-demand for over 90 days. Reserved pricing saves 30-60%.",
        "Purchase a Reserved Instance for 1-year (36% savings) or 3-year (63% savings).\n"
        "Check AWS Cost Explorer > Reservations for recommendations.",
        severity="COST",
    ),
    "rds-missing-tags": lambda: _rds_mock(
        "MISSING REQUIRED TAGS",
        "RDS instance is missing Owner, Environment, or Project tags for cost allocation.",
        "Add tags:\n  aws rds add-tags-to-resource --resource-name ARN "
        "--tags Key=Owner,Value=team Key=Environment,Value=prod",
        severity="MEDIUM",
    ),
    "rds-no-auto-minor-upgrade": lambda: _rds_mock(
        "AUTO MINOR VERSION UPGRADE DISABLED",
        "Minor version patches (security fixes, bug fixes) will not be applied automatically.",
        "Enable auto minor version upgrade:\n"
        "  aws rds modify-db-instance --db-instance-identifier ID "
        "--auto-minor-version-upgrade --apply-immediately",
        severity="MEDIUM",
    ),

    # ── CloudTrail ──
    "cloudtrail-not-logging": lambda: _cloudtrail_mock(
        random.choice(["management-events-trail", "org-trail", "prod-audit-trail"]),
        "TRAIL LOGGING IS DISABLED — No Audit Trail",
        "CloudTrail is configured but logging is turned off. No API events are being recorded.",
        "Re-enable logging immediately:\n  aws cloudtrail start-logging --name TRAIL_NAME",
        severity="CRITICAL",
    ),
    "cloudtrail-no-log-validation": lambda: _cloudtrail_mock(
        random.choice(["management-events-trail", "prod-audit-trail"]),
        "LOG FILE VALIDATION DISABLED",
        "Without log file validation, tampered or deleted log files cannot be detected.",
        "Enable log file validation:\n"
        "  aws cloudtrail update-trail --name TRAIL_NAME --enable-log-file-validation",
        severity="HIGH",
    ),
    "cloudtrail-no-kms-encryption": lambda: _cloudtrail_mock(
        random.choice(["org-trail", "prod-audit-trail"]),
        "TRAIL LOGS NOT ENCRYPTED WITH KMS",
        "CloudTrail log files are stored in S3 without KMS encryption. "
        "Anyone with S3 read access can read raw API events.",
        "Encrypt with a KMS key:\n"
        "  aws cloudtrail update-trail --name TRAIL_NAME --kms-key-id alias/cloudtrail-key",
        severity="MEDIUM",
    ),
    "cloudtrail-no-cloudwatch-logs": lambda: _cloudtrail_mock(
        random.choice(["management-events-trail", "org-trail"]),
        "NOT STREAMING TO CLOUDWATCH LOGS",
        "Trail is not configured to send events to CloudWatch Logs. "
        "Real-time alerting on suspicious API calls is not possible.",
        "Configure CloudWatch Logs integration:\n"
        "  aws cloudtrail update-trail --name TRAIL_NAME "
        "--cloud-watch-logs-log-group-arn ARN --cloud-watch-logs-role-arn ROLE_ARN",
        severity="MEDIUM",
    ),

    # ── IAM ──
    "iam-user-no-mfa": lambda: _iam_user_mock(
        "CONSOLE ACCESS WITHOUT MFA — Critical Risk",
        "This IAM user has a console login profile but no MFA device enrolled. "
        "A stolen password is all an attacker needs.",
        "Enforce MFA:\n  1. Add a virtual MFA device for the user in IAM Console\n"
        "  2. Add SCP/policy: Deny all actions if MFA is not present (aws:MultiFactorAuthPresent=false)",
        severity="CRITICAL",
    ),
    "iam-inactive-user": lambda: _iam_user_mock(
        "CREDENTIALS UNUSED FOR 90+ DAYS",
        "This IAM user has not logged in or used access keys in over 90 days.",
        "Disable or delete:\n  aws iam update-login-profile --user-name USER --password-reset-required\n"
        "  aws iam deactivate-mfa-device ...\n  aws iam delete-login-profile --user-name USER",
        severity="HIGH", extra_fields=[("LastActivity", lambda: _rand_date(90, 400))],
    ),
    "iam-unused-access-key": lambda: _iam_user_mock(
        "ACCESS KEY NOT ROTATED IN 90+ DAYS",
        "IAM access key has not been used or rotated in over 90 days. "
        "Long-lived keys increase the blast radius of a credential leak.",
        "Rotate the key:\n  aws iam create-access-key --user-name USER\n"
        "  Update apps/scripts with new key\n  aws iam delete-access-key --access-key-id OLD_KEY_ID",
        severity="HIGH", extra_fields=[("KeyAge", lambda: f"{random.randint(90, 365)} days")],
    ),
    "iam-overly-broad-policy": lambda: ({
        "ResourceId": random.choice(MOCK_IAM_POLICIES),
        "PolicyName": random.choice(["FullAdminAccess", "DevWildcardPolicy", "LegacySuperUser"]),
        "AttachedTo": f"{random.randint(1, 5)} principals",
        "Severity": "CRITICAL",
        "Finding": "WILDCARD ACTION OR RESOURCE IN POLICY",
        "Description": "Policy contains Action: * or Resource: * granting unrestricted permissions.",
        "Recommendation": "Replace wildcards with specific actions and resources following least-privilege:\n"
                          "  Review what the policy is used for and enumerate only required actions.\n"
                          "  Use IAM Access Analyzer to generate least-privilege policies from CloudTrail.",
    }),
    "iam-unused-role": lambda: _iam_role_mock(
        "IAM ROLE UNUSED FOR 90+ DAYS",
        "This role has had no API activity in over 90 days. It may be from a decommissioned service.",
        "Verify and delete if unused:\n  aws iam get-role --role-name ROLE_NAME\n"
        "  aws iam delete-role --role-name ROLE_NAME\n"
        "  (detach all policies first: aws iam detach-role-policy ...)",
        severity="HIGH", extra_fields=[("LastUsed", lambda: _rand_date(90, 400))],
    ),
    "iam-user-inline-policy": lambda: _iam_user_mock(
        "USER HAS INLINE POLICY — Use Groups Instead",
        "This IAM user has an inline policy attached directly. "
        "Inline policies cannot be reused and are harder to audit.",
        "Move permissions to a managed policy and attach via a group:\n"
        "  aws iam list-user-policies --user-name USER\n"
        "  aws iam delete-user-policy --user-name USER --policy-name POLICY_NAME\n"
        "  Create group → attach managed policy → add user to group",
        severity="MEDIUM",
    ),

    # ── Lambda ──
    "lambda-not-invoked-30d": lambda: _lambda_mock(
        "ZERO INVOCATIONS IN 30 DAYS — Possibly Orphaned",
        "This Lambda function has not been invoked in the past 30 days. "
        "It may be from a deprecated feature or old integration.",
        "Check triggers and event sources. If no longer needed, delete:\n"
        "  aws lambda delete-function --function-name FUNCTION_NAME",
        severity="COST",
    ),
    "lambda-missing-tags": lambda: _lambda_mock(
        "MISSING REQUIRED TAGS",
        "Lambda function is missing Owner, Environment, or Project tags.",
        "Add tags:\n  aws lambda tag-resource --resource ARN "
        "--tags Owner=team,Environment=prod,Project=name",
        severity="MEDIUM",
    ),
    "lambda-public-url-no-auth": lambda: _lambda_mock(
        "PUBLIC FUNCTION URL — NO AUTHENTICATION",
        "Lambda Function URL is enabled with AuthType=NONE. Anyone on the internet can invoke it.",
        "Either:\n  1. Set auth type to AWS_IAM:\n"
        "  aws lambda update-function-url-config --function-name NAME --auth-type AWS_IAM\n"
        "  2. Or delete the function URL if not needed:\n"
        "  aws lambda delete-function-url-config --function-name NAME",
        severity="CRITICAL",
    ),
    "lambda-public-invoke-policy": lambda: _lambda_mock(
        "RESOURCE POLICY ALLOWS CROSS-ACCOUNT INVOKE",
        "Lambda resource policy grants invoke permission to Principal: * or a broad account principal.",
        "Review and restrict resource-based policy:\n"
        "  aws lambda get-policy --function-name NAME\n"
        "  aws lambda remove-permission --function-name NAME --statement-id STMT_ID",
        severity="HIGH",
    ),

    # ── VPC / Networking ──
    "vpc-no-flow-logs": lambda: _vpc_mock(
        "VPC HAS NO FLOW LOGS — Blind to Network Traffic",
        "VPC Flow Logs are not enabled. Network-level threat detection and forensics are impossible.",
        "Enable flow logs (send to CloudWatch Logs or S3):\n"
        "  aws ec2 create-flow-logs --resource-type VPC --resource-ids VPC_ID "
        "--traffic-type ALL --log-destination-type cloud-watch-logs "
        "--log-group-name /aws/vpc/flowlogs --deliver-logs-permission-arn ARN",
        severity="HIGH",
    ),
    "vpc-default-in-use": lambda: _vpc_mock(
        "DEFAULT VPC HAS RUNNING INSTANCES",
        "The default VPC (auto-created by AWS) has running EC2 instances. "
        "Default VPCs have permissive default NACLs and no intentional design.",
        "Migrate instances to a purpose-built VPC with proper subnet segmentation and NACLs.\n"
        "Then delete the default VPC to reduce attack surface.",
        severity="MEDIUM",
    ),
    "vpc-default-sg-has-rules": lambda: ({
        "ResourceId": random.choice(MOCK_SG_IDS),
        "GroupName": "default",
        "VpcId": random.choice(MOCK_VPC_IDS),
        "InboundRuleCount": str(random.randint(1, 5)),
        "Severity": "HIGH",
        "Finding": "DEFAULT SG HAS INBOUND/OUTBOUND RULES — CIS 4.3",
        "Description": "CIS Benchmark 4.3: The default security group should restrict all traffic. "
                       "It currently has non-empty rules.",
        "Recommendation": "Remove all rules from the default SG. "
                          "Never use it for actual workloads:\n"
                          "  aws ec2 revoke-security-group-ingress --group-id SG_ID --protocol all --source-group SG_ID\n"
                          "  aws ec2 revoke-security-group-egress --group-id SG_ID --ip-permissions ...",
    }),
    "subnet-auto-assign-public-ip": lambda: ({
        "ResourceId": random.choice(MOCK_SUBNET_IDS),
        "SubnetId": random.choice(MOCK_SUBNET_IDS),
        "VpcId": random.choice(MOCK_VPC_IDS),
        "AvailabilityZone": random.choice(REGIONS),
        "Severity": "MEDIUM",
        "Finding": "SUBNET AUTO-ASSIGNS PUBLIC IPs",
        "Description": "MapPublicIpOnLaunch=true. New EC2 instances launched here get a public IP "
                       "automatically, even if not intended.",
        "Recommendation": "Disable auto-assign public IP:\n"
                          "  aws ec2 modify-subnet-attribute --subnet-id SUBNET_ID "
                          "--no-map-public-ip-on-launch",
    }),
    "igw-attached-non-prod-vpc": lambda: ({
        "ResourceId": random.choice(MOCK_IGW_IDS),
        "InternetGatewayId": random.choice(MOCK_IGW_IDS),
        "AttachedVpc": random.choice(MOCK_VPC_IDS),
        "Severity": "MEDIUM",
        "Finding": "INTERNET GATEWAY ATTACHED TO NON-PROD VPC",
        "Description": "An Internet Gateway is attached to a VPC tagged as dev/staging. "
                       "Non-prod environments generally should not have direct internet access.",
        "Recommendation": "Detach the IGW if outbound access is needed only for patching "
                          "(use NAT Gateway instead):\n"
                          "  aws ec2 detach-internet-gateway --internet-gateway-id IGW_ID --vpc-id VPC_ID",
    }),

    # ── Secrets Manager ──
    "secret-not-rotated": lambda: _secret_mock(
        "SECRET NOT ROTATED IN 90+ DAYS",
        "This secret has not been rotated in over 90 days. Stale credentials increase breach risk.",
        "Enable automatic rotation or rotate manually:\n"
        "  aws secretsmanager rotate-secret --secret-id SECRET_ID\n"
        "Or configure automatic rotation with a Lambda function.",
        severity="HIGH",
    ),
    "secret-rotation-disabled": lambda: _secret_mock(
        "AUTOMATIC ROTATION DISABLED",
        "Secret does not have automatic rotation configured. Manual rotation is error-prone and often skipped.",
        "Enable rotation:\n"
        "  aws secretsmanager rotate-secret --secret-id SECRET_ID "
        "--rotation-lambda-arn ARN --rotation-rules AutomaticallyAfterDays=30",
        severity="MEDIUM",
    ),
    "secret-missing-tags": lambda: _secret_mock(
        "MISSING OWNER / ENVIRONMENT TAG",
        "Secret has no Owner or Environment tag. Cannot determine which team owns this credential.",
        "Add tags:\n  aws secretsmanager tag-resource --secret-id SECRET_ID "
        "--tags Key=Owner,Value=team Key=Environment,Value=prod",
        severity="LOW",
    ),

    # ── EC2 (additional) ──
    "sg-high-rule-count": lambda: ({
        "ResourceId": random.choice(MOCK_SG_IDS),
        "GroupName": random.choice(["web-tier-sg", "app-sg", "legacy-monolith-sg"]),
        "InboundRuleCount": str(random.randint(40, 120)),
        "CidrsOpenToInternet": str(random.randint(5, 20)),
        "Severity": "MEDIUM",
        "Finding": "HIGH INBOUND RULE COUNT — Review Needed",
        "Description": "Security group has a large number of inbound rules, many open to 0.0.0.0/0. "
                       "Complex SGs are hard to audit and often contain stale rules.",
        "Recommendation": "Audit and consolidate rules. Replace individual CIDRs with security group references "
                          "where possible. Remove any rules that are no longer needed.",
    }),
    "ec2-not-ebs-optimized": lambda: _ec2_mock(
        "NOT EBS-OPTIMIZED — I/O Contention Risk",
        "Instance is not EBS-optimized. Network and EBS I/O share the same bandwidth path.",
        "Enable EBS optimization (free on most current-gen instance types):\n"
        "  aws ec2 modify-instance-attribute --instance-id INSTANCE_ID --ebs-optimized '{\"Value\": true}'",
        extra_fields=[("EbsOptimized", lambda: "false"), ("InstanceType", lambda: random.choice(INSTANCE_TYPES_OLD))],
    ),
}

# Merge extra mocks into main dict
POLICY_MOCKS.update(POLICY_MOCKS_EXTRA)


# ---------------------------------------------------------------------------

def load_policy_index():
    index = {}
    files = {}
    for filename in sorted(os.listdir(POLICY_DIR)):
        if not filename.endswith(".yml"):
            continue
        filepath = os.path.join(POLICY_DIR, filename)
        with open(filepath) as f:
            data = yaml.safe_load(f)
        policies = []
        for pol in data.get("policies", []):
            index[pol["name"]] = {
                "file": filename,
                "policy": pol,
                "description": pol.get("description", "").strip(),
            }
            policies.append(pol["name"])
        files[filename] = policies
    return index, files


POLICY_INDEX, FILE_MAP = load_policy_index()

GROUP_MAP = {
    "s3-lifecycle":  ["s3-infrequent-access-lifecycle.yml"],
    "s3-security":   ["s3-security-compliance.yml"],
    "s3-cost":       ["s3-cost-optimization.yml"],
    "s3":            ["s3-infrequent-access-lifecycle.yml", "s3-security-compliance.yml", "s3-cost-optimization.yml"],
    "ebs":           ["ebs-unattached.yml"],
    "ebs-optimize":  ["ebs-optimization.yml"],
    "ec2":           ["ec2-instances.yml"],
    "ec2-security":  ["ec2-security.yml"],
    "eni":           ["eni-cleanup.yml"],
    "ami":           ["ami-unused-cleanup.yml"],
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # ── /build endpoint — simulates PolicyBuilder dynamic policy run ──
        if self.path == "/build":
            spec   = body.get("spec", {})
            resource = spec.get("resource", "ec2")
            policy_name = spec.get("name") or f"dynamic-{resource}"
            dryrun = body.get("dryrun", "true") == "true"
            region = body.get("region", "ap-south-1")

            # Generate 0-4 mock resources based on resource type
            resource_type_map = {
                "ec2": "EC2 Instance", "s3": "S3 Bucket", "ebs": "EBS Volume",
                "security-group": "Security Group", "rds": "RDS Instance",
                "iam-user": "IAM User", "iam-role": "IAM Role", "lambda": "Lambda Function",
                "cloudtrail": "CloudTrail", "vpc": "VPC", "subnet": "Subnet",
                "secrets-manager": "Secret",
            }
            # Pick a plausible mock generator for the resource type
            mock_generators = {
                "ec2": lambda: _ec2_mock("CUSTOM POLICY MATCH", "Resource matched your custom policy filters.", "Review and apply the appropriate action.", extra_fields=[("State.Name", lambda: "stopped")]),
                "s3": lambda: _s3_mock("CUSTOM POLICY MATCH", "Bucket matched your custom policy filters.", "Review and apply the appropriate action."),
                "ebs": lambda: _ebs_mock("CUSTOM POLICY MATCH", "Volume matched your custom policy filters.", "Review and apply the appropriate action."),
                "security-group": lambda: {"ResourceId": random.choice(MOCK_SG_IDS), "GroupName": random.choice(["legacy-sg", "dev-sg"]), "Severity": "INFO", "Finding": "CUSTOM POLICY MATCH", "Description": "Resource matched your custom filters.", "Recommendation": "Review and take action."},
                "rds": lambda: _rds_mock("CUSTOM POLICY MATCH", "RDS instance matched your custom policy filters.", "Review and apply the appropriate action.", severity="INFO"),
                "lambda": lambda: _lambda_mock("CUSTOM POLICY MATCH", "Function matched your custom policy filters.", "Review and take action.", severity="INFO"),
                "cloudtrail": lambda: _cloudtrail_mock("custom-trail", "CUSTOM POLICY MATCH", "Trail matched your custom policy filters.", "Review and take action.", severity="INFO"),
                "vpc": lambda: _vpc_mock("CUSTOM POLICY MATCH", "VPC matched your custom policy filters.", "Review and take action.", severity="INFO"),
                "secrets-manager": lambda: _secret_mock("CUSTOM POLICY MATCH", "Secret matched your custom policy filters.", "Review and take action.", severity="INFO"),
                "iam-user": lambda: _iam_user_mock("CUSTOM POLICY MATCH", "IAM user matched your custom policy filters.", "Review and take action.", severity="INFO"),
            }
            gen = mock_generators.get(resource)
            count = random.randint(0, 4) if gen else 0
            resources = [gen() for _ in range(count)] if gen else []

            self._send(200, {
                "policy": policy_name,
                "resource": resource,
                "status": "success",
                "return_code": 0,
                "dryrun": dryrun,
                "account": {"account_id": "123456789012", "region": region},
                "generated_yaml": f"policies:\n  - name: {policy_name}\n    resource: aws.{resource}\n    filters: {spec.get('filters', [])}\n    actions: {spec.get('actions', [])}",
                "resources_found": {policy_name: count},
                "resources": resources,
            })
            return

        # ── /action endpoint — mock remediation ──
        if self.path == "/action":
            resource_ids = body.get("resource_ids", [])
            action = body.get("action", "tag")
            self._send(200, {
                "status": "success",
                "action": action,
                "resources_affected": len(resource_ids),
                "resource_ids": resource_ids,
                "dryrun": body.get("dryrun", "true") == "true",
            })
            return

        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return

        policy_input = body.get("policy", "all")
        dryrun = body.get("dryrun", "true") == "true"

        if policy_input == "list":
            self._send(200, {
                "account": {"account_id": "123456789012", "region": body.get("region", "ap-south-1")},
                "groups": GROUP_MAP,
                "individual_policies": {
                    name: {
                        "file": entry["file"],
                        "description": entry["description"],
                    }
                    for name, entry in sorted(POLICY_INDEX.items())
                },
                "files": FILE_MAP,
            })
            return

        # Support array form: {"policies": ["name1", "name2"]}
        policies_list = body.get("policies")
        if isinstance(policies_list, list) and policies_list:
            names = [n for n in policies_list if n in POLICY_INDEX or n in POLICY_MOCKS]
            if not names:
                self._send(400, {"error": "No valid policy names found in the list"})
                return
        # Single name / group form
        elif policy_input == "all":
            names = list(POLICY_INDEX.keys())
        elif policy_input in GROUP_MAP:
            names = []
            for f in GROUP_MAP[policy_input]:
                names.extend(FILE_MAP.get(f, []))
        elif policy_input in POLICY_INDEX or policy_input in POLICY_MOCKS:
            names = [policy_input]
        else:
            self._send(400, {"error": f"Unknown policy or group: '{policy_input}'"})
            return

        results = []
        for name in names:
            count = random.randint(0, 6)
            resources = []
            mock_fn = POLICY_MOCKS.get(name)
            for _ in range(count):
                if mock_fn:
                    resources.append(mock_fn())
                else:
                    resources.append({"ResourceId": f"unknown-{random.randint(1000,9999)}", "Finding": name})

            results.append({
                "policy": name,
                "description": POLICY_INDEX.get(name, {}).get("description", ""),
                "status": "success",
                "return_code": 0,
                "resources_found": {name: count},
                "resources": resources,
            })

        self._send(200, {
            "account": {"account_id": "123456789012", "region": body.get("region", "ap-south-1")},
            "execution_time": datetime.utcnow().isoformat(),
            "dryrun": dryrun,
            "requested": policy_input,
            "policies_executed": len(results),
            "results": results,
        })

    def do_GET(self):
        self.do_POST()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[mock-api] {args[0]}")


if __name__ == "__main__":
    port = 8080
    print(f"Mock API running on http://localhost:{port}")
    print(f"Loaded {len(POLICY_INDEX)} policies from {POLICY_DIR}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
