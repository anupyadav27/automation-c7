// Enrichment layer on top of the raw mock API shapes.
// Adds registry metadata (titles, rationale, remediation, AI fix prompts),
// audit columns (tenant / scan id / first+last seen) and derived table rows.

import {
  ASSETS,
  FINDINGS,
  RECOMMENDATIONS,
  RUNS,
  DRIFT,
  COST_RULE_ROWS,
  COMPLIANCE_POLICIES,
  type Asset,
  type Domain,
  type Finding,
  type Provider,
  type Recommendation,
  type Severity,
  type ActionTier,
  type FinopsCategory,
  type DriftKind,
} from "./mock-data";

export const TENANT = "acme-platform";

export const REGION_OPTIONS = [
  "ap-south-1",
  "us-east-1",
  "us-west-2",
  "eu-west-1",
  "eu-central-1",
  "ap-southeast-2",
];

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

/* ------------------------------ time helpers ----------------------------- */

const NOW = Date.UTC(2026, 7, 2, 5, 40, 0);

export function relTime(minutesAgo: number) {
  if (minutesAgo < 1) return "just now";
  if (minutesAgo < 60) return `${Math.round(minutesAgo)} m ago`;
  if (minutesAgo < 60 * 48) return `${Math.round(minutesAgo / 60)} h ago`;
  return `${Math.round(minutesAgo / 1440)} d ago`;
}

export function absTime(minutesAgo: number) {
  return new Date(NOW - minutesAgo * 60000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

export interface Stamp {
  ago: number;
}
export const stamp = (m: number): Stamp => ({ ago: m });

/* ---------------------------- resource labels ---------------------------- */

export const RESOURCE_LABELS: Record<string, string> = {
  "ec2.instance": "EC2 Instance",
  "ec2.volume": "EBS Volume",
  "ec2.security_group": "Security Group",
  "ec2.elastic_ip": "Elastic IP",
  "ec2.snapshot": "EBS Snapshot",
  "s3.bucket": "S3 Bucket",
  "rds.instance": "RDS Instance",
  "lambda.function": "Lambda Function",
  "iam.role": "IAM Role",
  "iam.user": "IAM User",
  "vpc.network": "VPC Network",
  "vpc.subnet": "VPC Subnet",
  "elb.load_balancer": "Load Balancer",
  "eks.cluster": "EKS Cluster",
  "cloudwatch.log_group": "Log Group",
  "kms.key": "KMS Key",
};
export const resourceLabel = (t: string) => RESOURCE_LABELS[t] ?? t;
export const resourceTypeDisplay = (t: string) => `${resourceLabel(t)} · ${t}`;

/* ---------------------------- policy registry ---------------------------- */

export interface PolicyMeta {
  title: string;
  description: string;
  rationale: string;
  remediation: string;
  references: { label: string; url: string }[];
  exposure?: string;
  graph_check?: boolean;
}

const ref = (label: string, url: string) => ({ label, url });
const AWS_DOCS = "https://docs.aws.amazon.com/";

export const POLICY_META: Record<string, PolicyMeta> = {
  "sg-open-ssh": {
    title: "Security group allows SSH (port 22) from 0.0.0.0/0",
    description: "An ingress rule exposes TCP port 22 to the entire public internet.",
    rationale:
      "Internet-wide SSH exposure is the single most common initial access vector for credential brute-forcing and automated botnets.",
    remediation: "Remove the 0.0.0.0/0 ingress rule on port 22. Use SSM Session Manager instead.",
    references: [ref("CIS AWS 5.2", AWS_DOCS), ref("MITRE T1133", "https://attack.mitre.org/")],
    exposure: "internet-reachable",
    graph_check: true,
  },
  "sg-open-rdp": {
    title: "Security group allows RDP (port 3389) from 0.0.0.0/0",
    description: "An ingress rule exposes TCP port 3389 to the entire public internet.",
    rationale: "Publicly reachable RDP is continuously scanned and brute-forced.",
    remediation: "Restrict port 3389 to a bastion CIDR or migrate to SSM Session Manager.",
    references: [ref("CIS AWS 5.3", AWS_DOCS)],
    exposure: "internet-reachable",
    graph_check: true,
  },
  "sg-wide-egress": {
    title: "Security group permits unrestricted egress",
    description: "Egress rule allows all protocols and ports to 0.0.0.0/0.",
    rationale: "Unrestricted egress enables data exfiltration and command-and-control traffic.",
    remediation: "Scope egress to the specific destinations and ports the workload requires.",
    references: [ref("NIST SC-7", AWS_DOCS)],
  },
  "s3-public-acl": {
    title: "S3 bucket grants public read via ACL",
    description: "Bucket ACL includes AllUsers or AuthenticatedUsers grants.",
    rationale: "Public object listing is the leading cause of accidental data disclosure.",
    remediation: "Enable Block Public Access at bucket and account level and remove the ACL grant.",
    references: [ref("CIS AWS 2.1.5", AWS_DOCS)],
    exposure: "public-read",
    graph_check: true,
  },
  "s3-no-encryption": {
    title: "S3 bucket has no default encryption",
    description: "No SSE-S3 or SSE-KMS default encryption configuration is present.",
    rationale: "Objects written without encryption at rest fail most audit regimes.",
    remediation: "Apply a default encryption configuration using SSE-KMS with a customer key.",
    references: [ref("CIS AWS 2.1.1", AWS_DOCS)],
  },
  "s3-no-versioning": {
    title: "S3 bucket versioning disabled",
    description: "Object versioning is suspended or was never enabled.",
    rationale: "Without versioning, overwrite and ransomware events are unrecoverable.",
    remediation: "Enable versioning and pair it with a lifecycle rule for noncurrent versions.",
    references: [ref("AWS Well-Architected", AWS_DOCS)],
  },
  "s3-no-lifecycle": {
    title: "S3 bucket has no lifecycle policy",
    description: "No transition or expiration rules are configured on the bucket.",
    rationale: "Cold objects accumulate on standard storage and inflate monthly spend.",
    remediation: "Add lifecycle transitions to IA at 30 days and Glacier at 90 days.",
    references: [ref("FinOps Framework", "https://www.finops.org/")],
  },
  "ebs-unencrypted": {
    title: "EBS volume is not encrypted",
    description: "Volume was created without encryption at rest.",
    rationale: "Unencrypted block storage exposes data on snapshot sharing or media reuse.",
    remediation: "Snapshot the volume, copy the snapshot with encryption, and replace the volume.",
    references: [ref("CIS AWS 2.2.1", AWS_DOCS)],
  },
  "ebs-unattached": {
    title: "EBS volume is unattached",
    description: "Volume is in available state with no attachments.",
    rationale: "Detached volumes bill at full provisioned capacity while serving no workload.",
    remediation: "Snapshot for retention if needed, then delete the volume.",
    references: [ref("FinOps Framework", "https://www.finops.org/")],
  },
  "ec2-public-ip": {
    title: "EC2 instance has a public IP address",
    description: "Instance is directly addressable from the internet.",
    rationale: "Direct public addressing bypasses load balancer and WAF controls.",
    remediation: "Move the instance to a private subnet behind an ALB or NAT gateway.",
    references: [ref("NIST SC-7", AWS_DOCS)],
    exposure: "internet-reachable",
    graph_check: true,
  },
  "ec2-imdsv1-enabled": {
    title: "EC2 instance permits IMDSv1",
    description: "Instance metadata service is not restricted to token-based v2 requests.",
    rationale: "IMDSv1 allows SSRF chains to steal instance role credentials.",
    remediation: "Set HttpTokens=required on instance metadata options.",
    references: [ref("AWS IMDSv2", AWS_DOCS)],
  },
  "ec2-missing-owner-tag": {
    title: "EC2 instance is missing an Owner tag",
    description: "No Owner tag is present on the resource.",
    rationale: "Unowned compute cannot be triaged, budgeted, or safely decommissioned.",
    remediation: "Apply the Owner tag from the deploying team's Terraform default tags.",
    references: [ref("Tagging standard", AWS_DOCS)],
  },
  "ec2-untagged-environment": {
    title: "EC2 instance is missing an Environment tag",
    description: "No Environment tag is present on the resource.",
    rationale: "Environment tagging drives guardrail scope and budget separation.",
    remediation: "Add Environment=production|staging|development via default_tags.",
    references: [ref("Tagging standard", AWS_DOCS)],
  },
  "rds-public-access": {
    title: "RDS instance is publicly accessible",
    description: "PubliclyAccessible is true and the instance resolves to a public endpoint.",
    rationale: "Publicly reachable databases are routinely enumerated and attacked.",
    remediation: "Set PubliclyAccessible=false and reach the database through private subnets.",
    references: [ref("CIS AWS 2.3.3", AWS_DOCS)],
    exposure: "internet-reachable",
    graph_check: true,
  },
  "rds-no-backup-retention": {
    title: "RDS backup retention is zero",
    description: "Automated backups are disabled on the instance.",
    rationale: "Zero retention means no point-in-time recovery after corruption.",
    remediation: "Set BackupRetentionPeriod to at least 7 days.",
    references: [ref("AWS RDS backups", AWS_DOCS)],
  },
  "rds-single-az": {
    title: "RDS instance is single-AZ",
    description: "Multi-AZ failover is not enabled for a production-tagged database.",
    rationale: "Single-AZ databases incur full outage on zone failure.",
    remediation: "Enable Multi-AZ or convert to an Aurora cluster with a reader.",
    references: [ref("AWS Well-Architected", AWS_DOCS)],
  },
  "iam-user-no-mfa": {
    title: "IAM user has no MFA device",
    description: "Console-enabled user without a registered MFA device.",
    rationale: "Password-only console access is trivially phishable.",
    remediation: "Enforce MFA with an SCP and register a virtual MFA device for the user.",
    references: [ref("CIS AWS 1.10", AWS_DOCS)],
  },
  "iam-key-age-90d": {
    title: "IAM access key older than 90 days",
    description: "Active access key has not been rotated within the policy window.",
    rationale: "Long-lived static credentials widen the blast radius of any leak.",
    remediation: "Rotate the key, update consumers, then deactivate and delete the old key.",
    references: [ref("CIS AWS 1.14", AWS_DOCS)],
  },
  "iam-wildcard-policy": {
    title: "IAM role attaches a wildcard policy",
    description: "Inline or managed policy grants Action:* or Resource:*.",
    rationale: "Wildcard grants defeat least privilege and enable lateral movement.",
    remediation: "Replace the wildcard with the specific actions observed in Access Analyzer.",
    references: [ref("IAM best practices", AWS_DOCS)],
    graph_check: true,
  },
  "iam-unused-role-60d": {
    title: "IAM role unused for 60 days",
    description: "No recorded principal has assumed the role in the observation window.",
    rationale: "Dormant roles are unmonitored persistence opportunities.",
    remediation: "Confirm with the owning team, then delete the role and its trust policy.",
    references: [ref("IAM best practices", AWS_DOCS)],
  },
  "lambda-deprecated-runtime": {
    title: "Lambda function uses a deprecated runtime",
    description: "Runtime is past its AWS end-of-support date.",
    rationale: "Deprecated runtimes stop receiving security patches.",
    remediation: "Upgrade the function to a supported runtime and redeploy.",
    references: [ref("Lambda runtimes", AWS_DOCS)],
  },
  "lambda-no-dlq": {
    title: "Lambda function has no dead-letter queue",
    description: "Asynchronous invocation failures are discarded.",
    rationale: "Silent event loss makes incident reconstruction impossible.",
    remediation: "Configure an SQS dead-letter queue on the function's async config.",
    references: [ref("Lambda DLQ", AWS_DOCS)],
  },
  "kms-rotation-disabled": {
    title: "KMS key rotation is disabled",
    description: "Automatic annual key rotation is turned off for a customer-managed key.",
    rationale: "Unrotated keys extend the useful lifetime of any compromised material.",
    remediation: "Enable automatic key rotation on the customer-managed key.",
    references: [ref("CIS AWS 3.8", AWS_DOCS)],
  },
  "log-group-no-retention": {
    title: "CloudWatch log group has no retention",
    description: "Retention is set to Never Expire.",
    rationale: "Unbounded retention grows cost and conflicts with data-minimisation policy.",
    remediation: "Set retention_in_days to 90 for application logs, 365 for audit logs.",
    references: [ref("CloudWatch Logs", AWS_DOCS)],
  },
  "elb-no-tls-1-2": {
    title: "Load balancer accepts TLS below 1.2",
    description: "Listener uses a legacy security policy allowing TLS 1.0/1.1.",
    rationale: "Legacy TLS versions are deprecated and fail PCI DSS assessment.",
    remediation: "Attach the ELBSecurityPolicy-TLS13-1-2-2021-06 policy to the HTTPS listener.",
    references: [ref("ELB security policies", AWS_DOCS)],
    exposure: "internet-reachable",
  },
  "eip-unassociated": {
    title: "Elastic IP is not associated",
    description: "Allocated address has no association id.",
    rationale: "Idle Elastic IPs bill hourly and squat on address space.",
    remediation: "Release the Elastic IP allocation.",
    references: [ref("EC2 pricing", AWS_DOCS)],
  },
  "snapshot-orphaned": {
    title: "EBS snapshot is orphaned",
    description: "Source volume no longer exists and no AMI references the snapshot.",
    rationale: "Orphaned snapshots accumulate indefinitely at per-GB rates.",
    remediation: "Delete the snapshot after confirming no AMI or DR runbook references it.",
    references: [ref("EBS snapshots", AWS_DOCS)],
  },
  "vpc-flow-logs-disabled": {
    title: "VPC flow logs are disabled",
    description: "No flow log configuration is attached to the VPC.",
    rationale: "Without flow logs there is no network forensic trail for incidents.",
    remediation: "Create a flow log to CloudWatch Logs or S3 with ALL traffic capture.",
    references: [ref("CIS AWS 3.9", AWS_DOCS)],
  },
  "subnet-auto-assign-public-ip": {
    title: "Subnet auto-assigns public IPs",
    description: "MapPublicIpOnLaunch is enabled on the subnet.",
    rationale: "Workloads land on the internet by default rather than by decision.",
    remediation: "Disable map_public_ip_on_launch and place public workloads behind an ALB.",
    references: [ref("VPC subnets", AWS_DOCS)],
    exposure: "internet-reachable",
  },
  "eks-public-endpoint": {
    title: "EKS cluster API endpoint is public",
    description: "Kubernetes API server is reachable from 0.0.0.0/0.",
    rationale: "A public control plane endpoint widens the cluster's attack surface.",
    remediation: "Set endpoint_public_access=false or restrict public access CIDRs.",
    references: [ref("EKS endpoint access", AWS_DOCS)],
    exposure: "internet-reachable",
    graph_check: true,
  },
};

const FALLBACK_META: PolicyMeta = {
  title: "Policy violation detected",
  description: "The scanner matched this resource against the policy definition.",
  rationale: "See the policy definition for rationale.",
  remediation: "Review the policy definition and apply the documented remediation.",
  references: [],
};
export const policyMeta = (id: string) => POLICY_META[id] ?? FALLBACK_META;

/* ----------------------------- cost registry ----------------------------- */

export const RULE_TITLES: Record<string, string> = {
  aws_unattached_ebs_volume: "Delete unattached EBS volume",
  aws_idle_ec2_instance: "Stop or terminate idle EC2 instance",
  aws_oversized_ec2_instance: "Right-size oversized EC2 instance",
  aws_unassociated_elastic_ip: "Release unassociated Elastic IP",
  aws_orphaned_snapshot: "Delete orphaned EBS snapshot",
  aws_gp2_to_gp3_migration: "Migrate gp2 volume to gp3",
  aws_ec2_savings_plan_candidate: "Cover steady EC2 usage with a savings plan",
  aws_rds_reserved_instance_candidate: "Purchase RDS reserved instance",
  aws_rds_idle_instance: "Retire idle RDS instance",
  aws_s3_no_lifecycle_policy: "Add S3 lifecycle transitions",
  aws_s3_intelligent_tiering: "Enable S3 intelligent tiering",
  aws_log_group_no_retention: "Set log group retention",
  aws_idle_load_balancer: "Delete idle load balancer",
  aws_lambda_overprovisioned_memory: "Reduce Lambda memory allocation",
  aws_untagged_cost_allocation: "Add cost-allocation tags",
  aws_missing_environment_tag: "Add Environment tag for budget split",
};
export const ruleTitle = (r: string) => RULE_TITLES[r] ?? r;
export const ruleId = (r: string) => `aws.${r.replace(/^aws_/, "").replace(/_/g, "-")}`;

export const RULE_FIX: Record<string, string> = {
  aws_unattached_ebs_volume: "Snapshot the volume for retention, then delete it.",
  aws_idle_ec2_instance: "Stop the instance and schedule termination after a 14-day soak.",
  aws_oversized_ec2_instance: "Change the instance type to the next smaller size in the family.",
  aws_unassociated_elastic_ip: "Release the Elastic IP allocation.",
  aws_orphaned_snapshot: "Delete the snapshot.",
  aws_gp2_to_gp3_migration: "Modify the volume type from gp2 to gp3.",
  aws_ec2_savings_plan_candidate: "Commit to a 1-year no-upfront compute savings plan.",
  aws_rds_reserved_instance_candidate: "Purchase a 1-year reserved instance for this class.",
  aws_rds_idle_instance: "Take a final snapshot and delete the database instance.",
  aws_s3_no_lifecycle_policy: "Add lifecycle rules transitioning objects to IA and Glacier.",
  aws_s3_intelligent_tiering: "Set the default storage class to intelligent tiering.",
  aws_log_group_no_retention: "Set retention_in_days on the log group.",
  aws_idle_load_balancer: "Delete the load balancer and its listeners.",
  aws_lambda_overprovisioned_memory: "Lower the memory_size to just above observed peak.",
  aws_untagged_cost_allocation: "Add CostCenter and Owner tags via default_tags.",
  aws_missing_environment_tag: "Add the Environment tag to the bucket.",
};

/* ------------------------------- scan ids -------------------------------- */

export const runScanId = (runId: string) => `scan_${runId.slice(-6).toLowerCase()}`;
export const SCAN_IDS = RUNS.map((r) => runScanId(r.run_id));
export const LATEST_SCAN = SCAN_IDS[0]!;

/* ------------------------------- asset rows ------------------------------ */

export interface AssetRow extends Asset {
  id: string;
  type_display: string;
  cost_monthly: number | null;
  findings: { critical: number; high: number; medium: number; low: number; total: number };
  first_seen: number;
  last_seen: number;
  scan_id: string;
  tenant: string;
}

const costFor = (a: Asset) => {
  const rec = RECOMMENDATIONS.find((r) => r.resource_uid === a.resource_uid);
  if (rec) return rec.current_monthly_cost_usd || null;
  const h = hash(a.resource_uid);
  if (h < 0.28) return null;
  return +(h * 460).toFixed(2);
};

export const ASSET_ROWS: AssetRow[] = ASSETS.map((a) => {
  const fs = FINDINGS.filter((f) => f.arn === a.resource_uid);
  const h = hash(a.resource_id);
  return {
    ...a,
    id: a.resource_uid,
    type_display: resourceTypeDisplay(a.resource_type),
    cost_monthly: costFor(a),
    findings: {
      critical: fs.filter((f) => f.severity === "critical").length,
      high: fs.filter((f) => f.severity === "high").length,
      medium: fs.filter((f) => f.severity === "medium").length,
      low: fs.filter((f) => f.severity === "low").length,
      total: fs.length,
    },
    first_seen: 1440 * (3 + Math.floor(h * 180)),
    last_seen: Math.floor(12 + h * 90),
    scan_id: LATEST_SCAN,
    tenant: TENANT,
  };
});

export const assetByUid = new Map(ASSET_ROWS.map((a) => [a.resource_uid, a]));

/* ------------------------------ finding rows ----------------------------- */

export interface FindingRow extends Finding {
  id: string;
  title: string;
  description: string;
  rationale: string;
  remediation: string;
  references: { label: string; url: string }[];
  exposure?: string | undefined;
  resource_type: string;
  type_display: string;
  provider: Provider;
  evidence: Record<string, unknown>;
  detected: number;
  first_seen: number;
  last_seen: number;
  scan_id: string;
  tenant: string;
  occurrences: { scan_id: string; at: number; status: "open" | "new" | "resolved" }[];
}

export const FINDING_ROWS: FindingRow[] = FINDINGS.map((f) => {
  const meta = policyMeta(f.policy);
  const asset = assetByUid.get(f.arn);
  const h = hash(f.policy + f.resource_id);
  const detected = Math.floor(15 + h * 4000);
  const scanIdx = Math.min(SCAN_IDS.length - 1, Math.floor(h * 4));
  return {
    ...f,
    id: `${f.policy}::${f.resource_id}`,
    title: meta.title,
    description: meta.description,
    rationale: meta.rationale,
    remediation: meta.remediation,
    references: meta.references,
    exposure: meta.exposure,
    resource_type: f.resource_key,
    type_display: resourceTypeDisplay(f.resource_key),
    provider: asset?.provider ?? "aws",
    evidence: {
      policy_id: f.policy,
      resource_id: f.resource_id,
      matched_at: absTime(detected),
      condition: `${f.resource_key} matched ${f.policy}`,
      attributes:
        f.resource_key === "ec2.security_group"
          ? { ingress: [{ protocol: "tcp", from_port: 22, to_port: 22, cidr: "0.0.0.0/0" }] }
          : { compliant: false, evaluated_keys: Object.keys(asset?.tags ?? {}) },
    },
    detected,
    first_seen: detected + Math.floor(h * 20000),
    last_seen: Math.max(12, Math.floor(h * 200)),
    scan_id: SCAN_IDS[0]!,
    tenant: TENANT,
    occurrences: SCAN_IDS.slice(0, 3 + scanIdx).map((s, i) => ({
      scan_id: s,
      at: 12 + i * 240,
      status: i === 0 ? "open" : ("open" as const),
    })),
  };
});

export const findingsForUid = (uid: string) => FINDING_ROWS.filter((f) => f.arn === uid);

/* --------------------------- recommendation rows -------------------------- */

const RULE_BY_NAME = new Map(COST_RULE_ROWS.map((r) => [r.rule_name, r]));

export interface RecRow extends Recommendation {
  id: string;
  title: string;
  rule_id: string;
  fix: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  provider: Provider;
  account_id: string;
  region: string;
  confidence: "list price" | "usage-based" | "estimate";
  detected: number;
  first_seen: number;
  last_seen: number;
  scan_id: string;
  tenant: string;
  evaluated: { metric: string; actual: string; threshold: string; pass: boolean }[];
}

function evaluated(conds: string[], seed: number) {
  return conds.map((c, i) => {
    const m = c.match(/^(\S+)\s*(<|>|==|<=|>=|in)\s*(.+)$/);
    const metric = m?.[1] ?? c;
    const op = m?.[2] ?? "==";
    const target = m?.[3] ?? "";
    const numeric = target.match(/^([\d.]+)/);
    let actual = target;
    if (numeric) {
      const base = parseFloat(numeric[1]!);
      const unit = target.replace(/^[\d.]+/, "");
      const v = op === "<" || op === "<=" ? base * (0.2 + seed * 0.5) : base * (1.2 + seed * 0.8);
      actual = `${v < 10 ? v.toFixed(1) : Math.round(v)}${unit}`;
    } else if (target === "available" || target === "null" || target === "false") {
      actual = target;
    } else {
      actual = target;
    }
    void i;
    return { metric, actual, threshold: `${op} ${target}`, pass: true };
  });
}

export const REC_ROWS: RecRow[] = RECOMMENDATIONS.map((r) => {
  const asset = assetByUid.get(r.resource_uid);
  const rule = RULE_BY_NAME.get(r.rule_name);
  const h = hash(r.recommendation_id);
  const detected = Math.floor(20 + h * 5200);
  return {
    ...r,
    id: r.recommendation_id,
    title: ruleTitle(r.rule_name),
    rule_id: ruleId(r.rule_name),
    fix: RULE_FIX[r.rule_name] ?? "Apply the documented remediation for this rule.",
    resource_id: asset?.resource_id ?? r.resource_uid,
    resource_name: asset?.name ?? r.resource_uid,
    resource_type: asset?.resource_type ?? rule?.resource_key ?? "unknown",
    provider: asset?.provider ?? "aws",
    account_id: asset?.account_id ?? "123456789012",
    region: asset?.region ?? "ap-south-1",
    confidence:
      r.savings_model === "flat_monthly"
        ? "list price"
        : h < 0.5
          ? "usage-based"
          : ("estimate" as const),
    detected,
    first_seen: detected + Math.floor(h * 30000),
    last_seen: Math.max(12, Math.floor(h * 240)),
    scan_id: SCAN_IDS[0]!,
    tenant: TENANT,
    evaluated: evaluated(r.conditions, h),
  };
});

export const recsForUid = (uid: string) => REC_ROWS.filter((r) => r.resource_uid === uid);

export const finopsSummary = {
  monthly_cost: REC_ROWS.reduce((s, r) => s + r.current_monthly_cost_usd, 0),
  min: REC_ROWS.reduce((s, r) => s + r.estimated_monthly_savings_usd.min, 0),
  max: REC_ROWS.reduce((s, r) => s + r.estimated_monthly_savings_usd.max, 0),
  priced: REC_ROWS.filter((r) => r.current_monthly_cost_usd > 0).length,
  unpriced: REC_ROWS.filter((r) => r.current_monthly_cost_usd === 0).length,
};

/* ------------------------------- policy rows ------------------------------ */

export interface PolicyRow {
  id: string;
  policy: string;
  title: string;
  description: string;
  domain: Domain;
  severity: Severity;
  action_tier: ActionTier;
  automatable: "yes" | "no";
  resource_key: string;
  type_display: string;
  findings_count: number;
  graph_check: boolean;
}

export const POLICY_ROWS: PolicyRow[] = COMPLIANCE_POLICIES.map((p) => {
  const meta = policyMeta(p.policy);
  return {
    id: p.policy,
    policy: p.policy,
    title: meta.title,
    description: meta.description,
    domain: p.domain,
    severity: p.severity,
    action_tier: p.action_tier,
    automatable: p.automatable,
    resource_key: p.resource_key,
    type_display: resourceTypeDisplay(p.resource_key),
    findings_count: FINDINGS.filter((f) => f.policy === p.policy).length,
    graph_check: meta.graph_check ?? false,
  };
});

export interface CostRuleRow {
  id: string;
  rule_name: string;
  rule_id: string;
  title: string;
  provider: Provider;
  resource_key: string;
  type_display: string;
  category: FinopsCategory;
  severity: Severity;
  thresholds: string[];
  savings_model: "percent_range" | "flat_monthly";
  matches: number;
}

export const COST_RULE_TABLE: CostRuleRow[] = COST_RULE_ROWS.map((r) => ({
  id: r.rule_name,
  rule_name: r.rule_name,
  rule_id: ruleId(r.rule_name),
  title: ruleTitle(r.rule_name),
  provider: r.provider,
  resource_key: r.resource_key,
  type_display: resourceTypeDisplay(r.resource_key),
  category: r.category,
  severity: r.severity,
  thresholds: r.thresholds,
  savings_model: r.savings_model,
  matches: RECOMMENDATIONS.filter((x) => x.rule_name === r.rule_name).length,
}));

export function policyYaml(p: PolicyRow) {
  return `id: ${p.policy}
title: "${p.title}"
domain: ${p.domain}
severity: ${p.severity}
resource_key: ${p.resource_key}
action_tier: ${p.action_tier}
automatable: ${p.automatable}
graph_check: ${p.graph_check}
match:
  all:
    - attribute: ${p.resource_key.split(".")[1]}.config
      operator: violates
      value: ${p.policy}
remediation:
  summary: "${policyMeta(p.policy).remediation}"`;
}

/* --------------------------------- runs ---------------------------------- */

export interface RunRow {
  id: string;
  run_id: string;
  scan_id: string;
  started_at: string;
  started_ago: number;
  trigger: "manual" | "scheduled";
  status: "success" | "partial" | "failed";
  duration: string;
  stages_completed: number;
  scope: string[];
  assets: number;
  assets_delta: number;
  findings: number;
  findings_delta: number;
  sev: { critical: number; high: number; medium: number; low: number };
  savings_min: number;
  savings_max: number;
  savings_delta: number;
  stages: {
    key: string;
    label: string;
    status: "ok" | "skipped" | "failed";
    duration: string;
    records: number;
  }[];
}

const STAGE_KEYS = [
  ["discover", "Discover"],
  ["assets", "Build assets"],
  ["architecture", "Build architecture"],
  ["compliance", "Compliance"],
  ["finops", "FinOps"],
] as const;

export const RUN_ROWS: RunRow[] = RUNS.map((r, i) => {
  const prev = RUNS[i + 1];
  const h = hash(r.run_id);
  const sevTotal = r.findings;
  return {
    id: r.run_id,
    run_id: r.run_id,
    scan_id: runScanId(r.run_id),
    started_at: r.started_at,
    started_ago: 508 + i * 240,
    trigger: r.trigger,
    status: r.status,
    duration: r.duration,
    stages_completed: r.stages_completed,
    scope: ["all accounts", i % 3 === 0 ? "all regions" : "ap-south-1"],
    assets: r.assets,
    assets_delta: prev ? r.assets - prev.assets : 0,
    findings: r.findings,
    findings_delta: prev ? r.findings - prev.findings : 0,
    sev: {
      critical: Math.round(sevTotal * 0.18),
      high: Math.round(sevTotal * 0.31),
      medium: Math.round(sevTotal * 0.33),
      low:
        sevTotal -
        Math.round(sevTotal * 0.18) -
        Math.round(sevTotal * 0.31) -
        Math.round(sevTotal * 0.33),
    },
    savings_min: r.recommendations ? Math.round(3600 + h * 800) : 0,
    savings_max: r.recommendations ? Math.round(6100 + h * 900) : 0,
    savings_delta: r.recommendations ? Math.round((h - 0.5) * 400) : 0,
    stages: STAGE_KEYS.map(([key, label], si) => ({
      key,
      label,
      status:
        si < r.stages_completed
          ? "ok"
          : si === r.stages_completed && r.status === "failed"
            ? "failed"
            : "skipped",
      duration: si < r.stages_completed ? `${(12 + hash(r.run_id + key) * 90).toFixed(0)}s` : "—",
      records:
        si < r.stages_completed
          ? [r.assets, r.assets, Math.round(r.assets * 0.31), r.findings, r.recommendations][si]!
          : 0,
    })),
  };
});

export const runById = new Map(RUN_ROWS.map((r) => [r.run_id, r]));
export const runByScan = new Map(RUN_ROWS.map((r) => [r.scan_id, r]));

/* --------------------------------- drift --------------------------------- */

export type ChangeKind = "added" | "removed" | "changed";

export interface DriftRow {
  id: string;
  kind: DriftKind;
  change: ChangeKind;
  is_edge: boolean;
  label: string;
  resource_uid: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  type_display: string;
  what: string;
  account_id: string;
  region: string;
  from_scan: string;
  to_scan: string;
  detected: number;
  diff: { field: string; before: string; after: string }[];
}

export const DRIFT_ROWS: DriftRow[] = DRIFT.map((d, i) => {
  const asset = assetByUid.get(d.resource_uid);
  const isEdge = d.kind.startsWith("EDGE");
  const change: ChangeKind = d.kind.endsWith("ADDED")
    ? "added"
    : d.kind.endsWith("REMOVED")
      ? "removed"
      : "changed";
  const runIdx = RUN_ROWS.findIndex((r) => r.run_id === d.run_id);
  const to = RUN_ROWS[runIdx >= 0 ? runIdx : 0]!;
  const from = RUN_ROWS[(runIdx >= 0 ? runIdx : 0) + 1] ?? to;
  const diff = d.diff ?? [];
  const idPart = d.resource_uid.split(/[/:]/).pop() ?? d.resource_uid;
  return {
    id: d.id,
    kind: d.kind,
    change,
    is_edge: isEdge,
    label: isEdge ? `rel:${change}` : change,
    resource_uid: d.resource_uid,
    resource_id: asset?.resource_id ?? idPart,
    resource_name: asset?.name ?? idPart,
    resource_type: d.resource_type,
    type_display: isEdge
      ? `Relationship · ${d.resource_type}`
      : resourceTypeDisplay(d.resource_type),
    what: diff.length
      ? `${diff.length} field${diff.length > 1 ? "s" : ""}: ${diff.map((x) => x.field).join(", ")}`
      : change === "added"
        ? isEdge
          ? "new relationship observed"
          : "resource appeared in inventory"
        : isEdge
          ? "relationship no longer observed"
          : "resource absent from inventory",
    account_id: asset?.account_id ?? "123456789012",
    region: asset?.region ?? "ap-south-1",
    from_scan: from.scan_id,
    to_scan: to.scan_id,
    detected: 508 + i * 47,
    diff,
  };
});

/* ------------------------------ AI fix prompts ---------------------------- */

export function findingFixPrompt(f: FindingRow) {
  return `You are an infrastructure engineer working in this repository. A cloud governance scan raised this finding:

Finding: ${f.title}
Resource: ${f.resource_id} (${f.resource_type.split(".")[1]}) in account ${f.account_id}, region ${f.region}
Evidence from the scanner: ${JSON.stringify(f.evidence)}

Task: locate where this resource is defined — Terraform, CloudFormation, CDK, Pulumi... implement this remediation: ${f.remediation}

Constraints: change only what the fix requires, show the diff with a short risk note before applying.`;
}

export function recFixPrompt(r: RecRow) {
  return `You are an infrastructure engineer working in this repository. A cloud cost scan raised this recommendation:

Recommendation: ${r.title} (${r.rule_id})
Resource: ${r.resource_id} (${r.resource_type.split(".")[1]}) in account ${r.account_id}, region ${r.region}
Evidence from the scanner: ${JSON.stringify({ conditions: r.conditions, current_monthly_cost_usd: r.current_monthly_cost_usd, estimated_monthly_savings_usd: r.estimated_monthly_savings_usd })}

Task: locate where this resource is defined — Terraform, CloudFormation, CDK, Pulumi... implement this change: ${r.fix}

Constraints: change only what the fix requires, show the diff with a short risk note before applying.`;
}

export function policyFixTemplate(p: PolicyRow) {
  return `You are an infrastructure engineer working in this repository. A cloud governance scan raised this finding:

Finding: ${p.title}
Resource: {{resource_id}} ({{resource_type}}) in account {{account_id}}, region {{region}}
Evidence from the scanner: {{evidence_json}}

Task: locate where this resource is defined — Terraform, CloudFormation, CDK, Pulumi... implement this remediation: ${policyMeta(p.policy).remediation}

Constraints: change only what the fix requires, show the diff with a short risk note before applying.`;
}

export const AI_FIX_CAPTION = "works with any local AI assistant — Copilot, Cursor, Claude Code…";

export const savingsRange = (min: number, max: number) =>
  min === max ? `$${min.toFixed(2)}` : `$${min.toFixed(2)}–${max.toFixed(max >= 100 ? 0 : 2)}`;
