// Mock data layer for Cloud Estate Console.
// Shapes mirror the real REST API; swap these exports for fetches later.

export type Provider = "aws" | "azure" | "gcp" | "oci" | "ibm" | "k8s";
export type Severity = "critical" | "high" | "medium" | "low";
export type Domain = "compliance" | "governance" | "cost";
export type ActionTier = "notify" | "mark" | "tag" | "remediate" | "destroy";
export type FinopsCategory =
  "waste_elimination" | "rate_optimization" | "right_sizing" | "cost_visibility";

export interface Finding {
  policy: string;
  domain: Domain;
  severity: Severity;
  action_tier: ActionTier;
  automatable: "yes" | "no";
  resource_key: string;
  arn: string;
  resource_id: string;
  account_id: string;
  region: string;
  layer_id: string;
  name: string;
  /** Present on live findings, absent on the generated fixture. */
  title?: string;
  ai_fix_prompt?: string;
}

export interface Recommendation {
  recommendation_id: string;
  rule_name: string;
  resource_uid: string;
  severity: Severity;
  finops_category: FinopsCategory;
  estimated_savings: string;
  current_monthly_cost_usd: number;
  estimated_monthly_savings_usd: { min: number; max: number };
  savings_model: "percent_range" | "flat_monthly";
  description: string;
  conditions: string[];
}

export interface Asset {
  provider: Provider;
  account_id: string;
  region: string;
  resource_type: string;
  resource_id: string;
  resource_uid: string;
  name: string;
  tags: Record<string, string>;
  topology: {
    layer_id: string;
    layer_name: string;
    zone: string;
    container: string;
    uid_quality: "real" | "derived" | "synthetic";
  };
}

// deterministic PRNG so SSR and client agree
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
const rand = rng(20260801);
const pick = <T>(a: readonly T[]) => a[Math.floor(rand() * a.length)]!;
const hex = (n: number) =>
  Array.from({ length: n }, () => "0123456789abcdef"[Math.floor(rand() * 16)]).join("");

export const ACCOUNTS = ["123456789012", "402118845093", "917364552018", "230771449862"];
export const REGIONS = [
  "ap-south-1",
  "us-east-1",
  "us-west-2",
  "eu-west-1",
  "eu-central-1",
  "ap-southeast-2",
];
export const PROVIDERS: Provider[] = ["aws", "azure", "gcp", "oci", "ibm", "k8s"];

export const LAYERS = [
  { id: "G0", name: "global" },
  { id: "L1", name: "account" },
  { id: "L2", name: "vpc" },
  { id: "L3", name: "az" },
  { id: "L4", name: "subnet" },
  { id: "L5", name: "workload" },
];

const RESOURCE_TYPES = [
  { type: "ec2.instance", svc: "ec2", layer: "L5", prefix: "i-" },
  { type: "ec2.volume", svc: "ec2", layer: "L5", prefix: "vol-" },
  { type: "ec2.security_group", svc: "ec2", layer: "L2", prefix: "sg-" },
  { type: "ec2.elastic_ip", svc: "ec2", layer: "L2", prefix: "eipalloc-" },
  { type: "ec2.snapshot", svc: "ec2", layer: "L5", prefix: "snap-" },
  { type: "s3.bucket", svc: "s3", layer: "G0", prefix: "" },
  { type: "rds.instance", svc: "rds", layer: "L5", prefix: "" },
  { type: "lambda.function", svc: "lambda", layer: "L5", prefix: "" },
  { type: "iam.role", svc: "iam", layer: "G0", prefix: "" },
  { type: "iam.user", svc: "iam", layer: "G0", prefix: "" },
  { type: "vpc.network", svc: "vpc", layer: "L2", prefix: "vpc-" },
  { type: "vpc.subnet", svc: "vpc", layer: "L4", prefix: "subnet-" },
  { type: "elb.load_balancer", svc: "elb", layer: "L2", prefix: "" },
  { type: "eks.cluster", svc: "eks", layer: "L2", prefix: "" },
  { type: "cloudwatch.log_group", svc: "cloudwatch", layer: "G0", prefix: "" },
  { type: "kms.key", svc: "kms", layer: "G0", prefix: "" },
];

const NAME_STEMS = [
  "prod-web",
  "prod-api",
  "stg-worker",
  "dev-sandbox",
  "data-etl",
  "billing-svc",
  "auth-edge",
  "search-idx",
  "ml-train",
  "legacy-batch",
  "checkout-api",
  "media-cdn",
];
const ENVS = ["production", "staging", "development", "sandbox"];
const OWNERS = ["platform", "data-eng", "payments", "sre", "growth"];

function makeAsset(i: number): Asset {
  const rt = pick(RESOURCE_TYPES);
  const provider: Provider = rand() < 0.72 ? "aws" : pick(PROVIDERS);
  const account = pick(ACCOUNTS);
  const region = pick(REGIONS);
  const stem = pick(NAME_STEMS);
  const name =
    rt.type === "s3.bucket" ? `${stem}-${hex(6)}` : `${stem}-${String(i % 90).padStart(2, "0")}`;
  const rid = rt.prefix ? `${rt.prefix}${hex(17)}` : name;
  const uid =
    provider === "aws"
      ? `arn:aws:${rt.svc}:${rt.layer === "G0" ? "" : region}:${account}:${rt.type.split(".")[1]}/${rid}`
      : `${provider}://${account}/${region}/${rt.type}/${rid}`;
  const tagCount = Math.floor(rand() * 4);
  const tags: Record<string, string> = {};
  if (tagCount > 0) tags["Environment"] = pick(ENVS);
  if (tagCount > 1) tags["Owner"] = pick(OWNERS);
  if (tagCount > 2) tags["CostCenter"] = `cc-${1000 + Math.floor(rand() * 900)}`;
  const q = rand();
  return {
    provider,
    account_id: account,
    region,
    resource_type: rt.type,
    resource_id: rid,
    resource_uid: uid,
    name,
    tags,
    topology: {
      layer_id: rt.layer,
      layer_name: LAYERS.find((l) => l.id === rt.layer)!.name,
      zone: rt.layer === "G0" ? "global" : `${region}${pick(["a", "b", "c"])}`,
      container: rt.layer === "G0" ? "account" : `vpc-${hex(8)}`,
      uid_quality: q < 0.74 ? "real" : q < 0.92 ? "derived" : "synthetic",
    },
  };
}

import LIVE from "./live-data.json";

/* The console renders whatever the pipeline last produced. `live-data.json`
   is written by scripts/sync-live-data.mjs from the Cloud Estate API in these
   exact shapes; with no API reachable the generated fixtures below stand in,
   so the UI is never blocked by a dead backend. */
const live = LIVE as unknown as {
  assets?: Asset[];
  findings?: Finding[];
  recommendations?: Recommendation[];
  runs?: PipelineRun[];
};
export const IS_LIVE = (live.assets?.length ?? 0) > 0;

export const ASSETS: Asset[] = IS_LIVE
  ? (live.assets as Asset[])
  : Array.from({ length: 686 }, (_, i) => makeAsset(i));

export const TOTAL_ASSETS = ASSETS.length;

/* ------------------------------- findings ------------------------------- */

const POLICY_CATALOG: {
  policy: string;
  domain: Domain;
  severity: Severity;
  action_tier: ActionTier;
  automatable: "yes" | "no";
  resource_key: string;
}[] = [
  {
    policy: "sg-open-ssh",
    domain: "compliance",
    severity: "critical",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "ec2.security_group",
  },
  {
    policy: "sg-open-rdp",
    domain: "compliance",
    severity: "critical",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "ec2.security_group",
  },
  {
    policy: "sg-wide-egress",
    domain: "governance",
    severity: "medium",
    action_tier: "mark",
    automatable: "yes",
    resource_key: "ec2.security_group",
  },
  {
    policy: "s3-public-acl",
    domain: "compliance",
    severity: "critical",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "s3.bucket",
  },
  {
    policy: "s3-no-encryption",
    domain: "compliance",
    severity: "high",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "s3.bucket",
  },
  {
    policy: "s3-no-versioning",
    domain: "governance",
    severity: "low",
    action_tier: "notify",
    automatable: "yes",
    resource_key: "s3.bucket",
  },
  {
    policy: "s3-no-lifecycle",
    domain: "cost",
    severity: "medium",
    action_tier: "tag",
    automatable: "yes",
    resource_key: "s3.bucket",
  },
  {
    policy: "ebs-unencrypted",
    domain: "compliance",
    severity: "high",
    action_tier: "mark",
    automatable: "no",
    resource_key: "ec2.volume",
  },
  {
    policy: "ebs-unattached",
    domain: "cost",
    severity: "medium",
    action_tier: "destroy",
    automatable: "yes",
    resource_key: "ec2.volume",
  },
  {
    policy: "ec2-public-ip",
    domain: "compliance",
    severity: "high",
    action_tier: "notify",
    automatable: "no",
    resource_key: "ec2.instance",
  },
  {
    policy: "ec2-imdsv1-enabled",
    domain: "compliance",
    severity: "high",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "ec2.instance",
  },
  {
    policy: "ec2-missing-owner-tag",
    domain: "governance",
    severity: "low",
    action_tier: "tag",
    automatable: "yes",
    resource_key: "ec2.instance",
  },
  {
    policy: "ec2-untagged-environment",
    domain: "governance",
    severity: "low",
    action_tier: "tag",
    automatable: "yes",
    resource_key: "ec2.instance",
  },
  {
    policy: "rds-public-access",
    domain: "compliance",
    severity: "critical",
    action_tier: "remediate",
    automatable: "no",
    resource_key: "rds.instance",
  },
  {
    policy: "rds-no-backup-retention",
    domain: "governance",
    severity: "high",
    action_tier: "notify",
    automatable: "yes",
    resource_key: "rds.instance",
  },
  {
    policy: "rds-single-az",
    domain: "governance",
    severity: "medium",
    action_tier: "mark",
    automatable: "no",
    resource_key: "rds.instance",
  },
  {
    policy: "iam-user-no-mfa",
    domain: "compliance",
    severity: "critical",
    action_tier: "notify",
    automatable: "no",
    resource_key: "iam.user",
  },
  {
    policy: "iam-key-age-90d",
    domain: "compliance",
    severity: "high",
    action_tier: "notify",
    automatable: "yes",
    resource_key: "iam.user",
  },
  {
    policy: "iam-wildcard-policy",
    domain: "governance",
    severity: "high",
    action_tier: "mark",
    automatable: "no",
    resource_key: "iam.role",
  },
  {
    policy: "iam-unused-role-60d",
    domain: "governance",
    severity: "low",
    action_tier: "mark",
    automatable: "yes",
    resource_key: "iam.role",
  },
  {
    policy: "lambda-deprecated-runtime",
    domain: "governance",
    severity: "medium",
    action_tier: "notify",
    automatable: "no",
    resource_key: "lambda.function",
  },
  {
    policy: "lambda-no-dlq",
    domain: "governance",
    severity: "low",
    action_tier: "mark",
    automatable: "yes",
    resource_key: "lambda.function",
  },
  {
    policy: "kms-rotation-disabled",
    domain: "compliance",
    severity: "medium",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "kms.key",
  },
  {
    policy: "log-group-no-retention",
    domain: "governance",
    severity: "medium",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "cloudwatch.log_group",
  },
  {
    policy: "elb-no-tls-1-2",
    domain: "compliance",
    severity: "high",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "elb.load_balancer",
  },
  {
    policy: "eip-unassociated",
    domain: "cost",
    severity: "low",
    action_tier: "destroy",
    automatable: "yes",
    resource_key: "ec2.elastic_ip",
  },
  {
    policy: "snapshot-orphaned",
    domain: "cost",
    severity: "low",
    action_tier: "destroy",
    automatable: "yes",
    resource_key: "ec2.snapshot",
  },
  {
    policy: "vpc-flow-logs-disabled",
    domain: "compliance",
    severity: "medium",
    action_tier: "remediate",
    automatable: "yes",
    resource_key: "vpc.network",
  },
  {
    policy: "subnet-auto-assign-public-ip",
    domain: "governance",
    severity: "medium",
    action_tier: "mark",
    automatable: "yes",
    resource_key: "vpc.subnet",
  },
  {
    policy: "eks-public-endpoint",
    domain: "compliance",
    severity: "high",
    action_tier: "notify",
    automatable: "no",
    resource_key: "eks.cluster",
  },
];

export const POLICY_COUNT = 90;

function buildFindings(): Finding[] {
  const out: Finding[] = [];
  for (const p of POLICY_CATALOG) {
    const pool = ASSETS.filter((a) => a.resource_type === p.resource_key);
    const n = 1 + Math.floor(rand() * 4);
    for (let i = 0; i < n && i < pool.length; i++) {
      const a = pool[Math.floor(rand() * pool.length)]!;
      if (out.some((f) => f.policy === p.policy && f.resource_id === a.resource_id)) continue;
      out.push({
        ...p,
        arn: a.resource_uid,
        resource_id: a.resource_id,
        account_id: a.account_id,
        region: a.region,
        layer_id: a.topology.layer_id,
        name: a.name,
      });
    }
  }
  return out;
}

export const FINDINGS: Finding[] = live.findings?.length
  ? (live.findings as Finding[])
  : buildFindings();

export const findingsByDomain = {
  compliance: FINDINGS.filter((f) => f.domain === "compliance").length,
  governance: FINDINGS.filter((f) => f.domain === "governance").length,
  cost: FINDINGS.filter((f) => f.domain === "cost").length,
};

export const severityCounts = {
  critical: FINDINGS.filter((f) => f.severity === "critical").length,
  high: FINDINGS.filter((f) => f.severity === "high").length,
  medium: FINDINGS.filter((f) => f.severity === "medium").length,
  low: FINDINGS.filter((f) => f.severity === "low").length,
};

/* ---------------------------- recommendations ---------------------------- */

const COST_RULES: {
  rule_name: string;
  category: FinopsCategory;
  severity: Severity;
  resource_key: string;
  savings: string;
  model: "percent_range" | "flat_monthly";
  cost: [number, number];
  ratio: [number, number];
  description: string;
  conditions: string[];
}[] = [
  {
    rule_name: "aws_unattached_ebs_volume",
    category: "waste_elimination",
    severity: "high",
    resource_key: "ec2.volume",
    savings: "40-100% of volume cost",
    model: "percent_range",
    cost: [4, 90],
    ratio: [0.4, 1],
    description:
      "EBS volumes in 'available' state accrue storage charges without serving a workload.",
    conditions: ["state == available", "attachments == 0", "age_days > 7"],
  },
  {
    rule_name: "aws_idle_ec2_instance",
    category: "right_sizing",
    severity: "high",
    resource_key: "ec2.instance",
    savings: "60-100% of instance cost",
    model: "percent_range",
    cost: [20, 420],
    ratio: [0.6, 1],
    description: "Instance shows sustained near-zero utilization across the observation window.",
    conditions: ["cpu_utilization < 5%", "network_in < 5MB/day", "window == 14d"],
  },
  {
    rule_name: "aws_oversized_ec2_instance",
    category: "right_sizing",
    severity: "medium",
    resource_key: "ec2.instance",
    savings: "25-50% of instance cost",
    model: "percent_range",
    cost: [30, 380],
    ratio: [0.25, 0.5],
    description: "Peak utilization fits comfortably in the next smaller instance size.",
    conditions: ["cpu_p95 < 35%", "mem_p95 < 40%", "window == 30d"],
  },
  {
    rule_name: "aws_unassociated_elastic_ip",
    category: "waste_elimination",
    severity: "low",
    resource_key: "ec2.elastic_ip",
    savings: "$3.60/mo flat",
    model: "flat_monthly",
    cost: [3.6, 3.6],
    ratio: [1, 1],
    description: "Elastic IPs not associated with a running instance are billed hourly.",
    conditions: ["association_id == null"],
  },
  {
    rule_name: "aws_orphaned_snapshot",
    category: "waste_elimination",
    severity: "low",
    resource_key: "ec2.snapshot",
    savings: "100% of snapshot cost",
    model: "percent_range",
    cost: [1, 40],
    ratio: [0.9, 1],
    description: "Snapshot's source volume no longer exists and no AMI references it.",
    conditions: ["source_volume_exists == false", "ami_refs == 0", "age_days > 90"],
  },
  {
    rule_name: "aws_gp2_to_gp3_migration",
    category: "rate_optimization",
    severity: "medium",
    resource_key: "ec2.volume",
    savings: "20% of volume cost",
    model: "percent_range",
    cost: [8, 140],
    ratio: [0.2, 0.2],
    description: "gp3 delivers equivalent baseline performance at a lower per-GB rate than gp2.",
    conditions: ["volume_type == gp2", "iops <= 3000"],
  },
  {
    rule_name: "aws_ec2_savings_plan_candidate",
    category: "rate_optimization",
    severity: "high",
    resource_key: "ec2.instance",
    savings: "27-40% of on-demand",
    model: "percent_range",
    cost: [60, 520],
    ratio: [0.27, 0.4],
    description: "Steady-state on-demand usage qualifies for a 1-year compute savings plan.",
    conditions: ["uptime_ratio > 0.9", "on_demand == true", "window == 60d"],
  },
  {
    rule_name: "aws_rds_reserved_instance_candidate",
    category: "rate_optimization",
    severity: "high",
    resource_key: "rds.instance",
    savings: "30-45% of on-demand",
    model: "percent_range",
    cost: [90, 640],
    ratio: [0.3, 0.45],
    description: "Continuously running database instance is a reserved-instance candidate.",
    conditions: ["uptime_ratio > 0.95", "engine in [postgres, mysql]"],
  },
  {
    rule_name: "aws_rds_idle_instance",
    category: "waste_elimination",
    severity: "high",
    resource_key: "rds.instance",
    savings: "80-100% of instance cost",
    model: "percent_range",
    cost: [60, 400],
    ratio: [0.8, 1],
    description: "Database has had no client connections over the observation window.",
    conditions: ["database_connections == 0", "window == 21d"],
  },
  {
    rule_name: "aws_s3_no_lifecycle_policy",
    category: "waste_elimination",
    severity: "medium",
    resource_key: "s3.bucket",
    savings: "15-60% of storage cost",
    model: "percent_range",
    cost: [12, 310],
    ratio: [0.15, 0.6],
    description: "Bucket has no lifecycle transitions; cold objects stay on standard storage.",
    conditions: ["lifecycle_rules == 0", "size_gb > 100"],
  },
  {
    rule_name: "aws_s3_intelligent_tiering",
    category: "rate_optimization",
    severity: "medium",
    resource_key: "s3.bucket",
    savings: "10-30% of storage cost",
    model: "percent_range",
    cost: [20, 280],
    ratio: [0.1, 0.3],
    description: "Access pattern is irregular; intelligent tiering avoids manual class management.",
    conditions: ["access_pattern == irregular", "size_gb > 50"],
  },
  {
    rule_name: "aws_log_group_no_retention",
    category: "waste_elimination",
    severity: "medium",
    resource_key: "cloudwatch.log_group",
    savings: "50-90% of ingest+storage",
    model: "percent_range",
    cost: [5, 120],
    ratio: [0.5, 0.9],
    description: "Log group retains events indefinitely, growing storage cost without bound.",
    conditions: ["retention_in_days == null", "stored_bytes > 1GB"],
  },
  {
    rule_name: "aws_idle_load_balancer",
    category: "waste_elimination",
    severity: "medium",
    resource_key: "elb.load_balancer",
    savings: "$16.20/mo flat",
    model: "flat_monthly",
    cost: [16.2, 16.2],
    ratio: [1, 1],
    description: "Load balancer has no healthy targets and near-zero request count.",
    conditions: ["healthy_target_count == 0", "request_count < 100/day"],
  },
  {
    rule_name: "aws_lambda_overprovisioned_memory",
    category: "right_sizing",
    severity: "low",
    resource_key: "lambda.function",
    savings: "20-45% of invoke cost",
    model: "percent_range",
    cost: [2, 60],
    ratio: [0.2, 0.45],
    description: "Configured memory greatly exceeds observed max memory used.",
    conditions: ["max_memory_used_ratio < 0.5", "invocations > 1000/mo"],
  },
  {
    rule_name: "aws_untagged_cost_allocation",
    category: "cost_visibility",
    severity: "low",
    resource_key: "ec2.instance",
    savings: "unallocated spend",
    model: "flat_monthly",
    cost: [0, 0],
    ratio: [0, 0],
    description: "Resource lacks cost-allocation tags, so spend cannot be attributed to an owner.",
    conditions: ["tags.CostCenter == null", "tags.Owner == null"],
  },
  {
    rule_name: "aws_missing_environment_tag",
    category: "cost_visibility",
    severity: "low",
    resource_key: "s3.bucket",
    savings: "unallocated spend",
    model: "flat_monthly",
    cost: [0, 0],
    ratio: [0, 0],
    description: "Bucket spend cannot be split between production and non-production budgets.",
    conditions: ["tags.Environment == null"],
  },
];

export const COST_RULE_COUNT = 62;

function buildRecommendations(): Recommendation[] {
  const out: Recommendation[] = [];
  for (const r of COST_RULES) {
    const pool = ASSETS.filter((a) => a.resource_type === r.resource_key);
    const n = 2 + Math.floor(rand() * 4);
    for (let i = 0; i < n && i < pool.length; i++) {
      const a = pool[Math.floor(rand() * pool.length)]!;
      if (out.some((x) => x.rule_name === r.rule_name && x.resource_uid === a.resource_uid))
        continue;
      const cost = +(r.cost[0] + rand() * (r.cost[1] - r.cost[0])).toFixed(2);
      out.push({
        recommendation_id: `${r.rule_name}::${a.resource_uid}`,
        rule_name: r.rule_name,
        resource_uid: a.resource_uid,
        severity: r.severity,
        finops_category: r.category,
        estimated_savings: r.savings,
        current_monthly_cost_usd: cost,
        estimated_monthly_savings_usd: {
          min: +(cost * r.ratio[0]).toFixed(2),
          max: +(cost * r.ratio[1]).toFixed(2),
        },
        savings_model: r.model,
        description: r.description,
        conditions: r.conditions,
      });
    }
  }
  return out;
}

export const RECOMMENDATIONS: Recommendation[] = live.recommendations?.length
  ? (live.recommendations as Recommendation[])
  : buildRecommendations();

export const finopsCategoryCounts = {
  waste_elimination: 25,
  rate_optimization: 15,
  right_sizing: 13,
  cost_visibility: 9,
};

export const savingsTotals = {
  monthly_cost: 48312.44,
  min: 4120,
  max: 6890,
  priced_resources: 431,
};

export const topSavings = RECOMMENDATIONS.slice()
  .sort((a, b) => b.estimated_monthly_savings_usd.max - a.estimated_monthly_savings_usd.max)
  .slice(0, 5);

/* --------------------------------- runs --------------------------------- */

export const PIPELINE_STAGES = [
  { key: "discover", label: "Discover", records: 686, last_run: "12m ago", fresh: true },
  { key: "assets", label: "Assets", records: 686, last_run: "12m ago", fresh: true },
  { key: "architecture", label: "Architecture", records: 214, last_run: "12m ago", fresh: true },
  {
    key: "compliance",
    label: "Compliance",
    records: FINDINGS.length,
    last_run: "12m ago",
    fresh: true,
  },
  {
    key: "finops",
    label: "FinOps",
    records: RECOMMENDATIONS.length,
    last_run: "4h ago",
    fresh: false,
  },
];

export interface PipelineRun {
  run_id: string;
  started_at: string;
  stages_completed: number;
  assets: number;
  findings: number;
  recommendations: number;
  duration: string;
  trigger: "manual" | "scheduled";
  status: "success" | "partial" | "failed";
}

const FIXTURE_RUNS: PipelineRun[] = [
  {
    run_id: "run_01JQ8F3K2A",
    started_at: "2026-08-01 17:12 UTC",
    stages_completed: 5,
    assets: 686,
    findings: 67,
    recommendations: 62,
    duration: "3m 41s",
    trigger: "scheduled",
    status: "success",
  },
  {
    run_id: "run_01JQ7W9M4C",
    started_at: "2026-08-01 13:12 UTC",
    stages_completed: 5,
    assets: 684,
    findings: 64,
    recommendations: 61,
    duration: "3m 28s",
    trigger: "scheduled",
    status: "success",
  },
  {
    run_id: "run_01JQ7B1X8D",
    started_at: "2026-08-01 09:12 UTC",
    stages_completed: 4,
    assets: 684,
    findings: 64,
    recommendations: 0,
    duration: "2m 09s",
    trigger: "scheduled",
    status: "partial",
  },
  {
    run_id: "run_01JQ6Z5R7P",
    started_at: "2026-08-01 05:12 UTC",
    stages_completed: 5,
    assets: 679,
    findings: 61,
    recommendations: 58,
    duration: "3m 52s",
    trigger: "scheduled",
    status: "success",
  },
  {
    run_id: "run_01JQ6H2T3V",
    started_at: "2026-07-31 22:44 UTC",
    stages_completed: 5,
    assets: 679,
    findings: 61,
    recommendations: 58,
    duration: "4m 07s",
    trigger: "manual",
    status: "success",
  },
  {
    run_id: "run_01JQ5Y8N1B",
    started_at: "2026-07-31 17:12 UTC",
    stages_completed: 2,
    assets: 671,
    findings: 0,
    recommendations: 0,
    duration: "0m 51s",
    trigger: "scheduled",
    status: "failed",
  },
  {
    run_id: "run_01JQ5C4L9K",
    started_at: "2026-07-31 13:12 UTC",
    stages_completed: 5,
    assets: 671,
    findings: 59,
    recommendations: 55,
    duration: "3m 33s",
    trigger: "scheduled",
    status: "success",
  },
  {
    run_id: "run_01JQ4Q7J6H",
    started_at: "2026-07-31 09:12 UTC",
    stages_completed: 5,
    assets: 668,
    findings: 58,
    recommendations: 55,
    duration: "3m 19s",
    trigger: "scheduled",
    status: "success",
  },
];

export const RUNS: PipelineRun[] = live.runs?.length ? (live.runs as PipelineRun[]) : FIXTURE_RUNS;

export type DriftKind =
  "ASSET_ADDED" | "ASSET_REMOVED" | "ASSET_CHANGED" | "EDGE_ADDED" | "EDGE_REMOVED";

export interface DriftEvent {
  id: string;
  kind: DriftKind;
  at: string;
  run_id: string;
  resource_uid: string;
  resource_type: string;
  diff?: { field: string; before: string; after: string }[];
}

const FIXTURE_DRIFT: DriftEvent[] = [
  {
    id: "d1",
    kind: "ASSET_ADDED",
    at: "17:12:41",
    run_id: "run_01JQ8F3K2A",
    resource_uid: "arn:aws:ec2:ap-south-1:123456789012:instance/i-0a41c7d9e2b8f0c31",
    resource_type: "ec2.instance",
  },
  {
    id: "d2",
    kind: "ASSET_CHANGED",
    at: "17:12:39",
    run_id: "run_01JQ8F3K2A",
    resource_uid: "arn:aws:ec2:ap-south-1:123456789012:security-group/sg-051b8ad3f74c9e102",
    resource_type: "ec2.security_group",
    diff: [
      { field: "ingress[0].cidr", before: "10.0.0.0/8", after: "0.0.0.0/0" },
      { field: "ingress[0].port", before: "22", after: "22" },
    ],
  },
  {
    id: "d3",
    kind: "EDGE_ADDED",
    at: "17:12:36",
    run_id: "run_01JQ8F3K2A",
    resource_uid: "i-0a41c7d9e2b8f0c31 → sg-051b8ad3f74c9e102",
    resource_type: "attached_to",
  },
  {
    id: "d4",
    kind: "ASSET_CHANGED",
    at: "13:12:58",
    run_id: "run_01JQ7W9M4C",
    resource_uid: "arn:aws:rds:us-east-1:402118845093:db/billing-svc-11",
    resource_type: "rds.instance",
    diff: [
      { field: "instance_class", before: "db.r6g.large", after: "db.r6g.xlarge" },
      { field: "multi_az", before: "false", after: "true" },
    ],
  },
  {
    id: "d5",
    kind: "ASSET_REMOVED",
    at: "13:12:44",
    run_id: "run_01JQ7W9M4C",
    resource_uid: "arn:aws:ec2:eu-west-1:917364552018:volume/vol-0cd91f2a4b7e3d508",
    resource_type: "ec2.volume",
  },
  {
    id: "d6",
    kind: "EDGE_REMOVED",
    at: "09:12:21",
    run_id: "run_01JQ7B1X8D",
    resource_uid: "vol-0cd91f2a4b7e3d508 → i-07be2c4f1a9d3e650",
    resource_type: "attached_to",
  },
  {
    id: "d7",
    kind: "ASSET_CHANGED",
    at: "09:12:19",
    run_id: "run_01JQ7B1X8D",
    resource_uid: "arn:aws:s3:::media-cdn-4f2a91",
    resource_type: "s3.bucket",
    diff: [{ field: "encryption", before: "AES256", after: "none" }],
  },
  {
    id: "d8",
    kind: "ASSET_ADDED",
    at: "05:12:11",
    run_id: "run_01JQ6Z5R7P",
    resource_type: "lambda.function",
    resource_uid: "arn:aws:lambda:us-west-2:230771449862:function/auth-edge-22",
  },
  {
    id: "d9",
    kind: "ASSET_CHANGED",
    at: "05:12:08",
    run_id: "run_01JQ6Z5R7P",
    resource_uid: "arn:aws:iam::123456789012:role/legacy-batch-07",
    resource_type: "iam.role",
    diff: [{ field: "policy.Action", before: "s3:GetObject", after: "s3:*" }],
  },
  {
    id: "d10",
    kind: "ASSET_REMOVED",
    at: "22:44:52",
    run_id: "run_01JQ6H2T3V",
    resource_uid: "arn:aws:ec2:ap-south-1:123456789012:snapshot/snap-03f7e1b9c8a2d4056",
    resource_type: "ec2.snapshot",
  },
];

export const DRIFT: DriftEvent[] = (live as { drift?: DriftEvent[] }).drift?.length
  ? ((live as { drift?: DriftEvent[] }).drift as DriftEvent[])
  : IS_LIVE
    ? []
    : FIXTURE_DRIFT;

export const DRIFT_COUNT = IS_LIVE ? DRIFT.length : 23; // pipeline emits drift once two scans exist

/* ------------------------------- policies -------------------------------- */

export const COMPLIANCE_POLICIES = POLICY_CATALOG;

export const COST_RULE_ROWS = COST_RULES.map((r) => ({
  rule_name: r.rule_name,
  provider: "aws" as Provider,
  category: r.category,
  severity: r.severity,
  resource_key: r.resource_key,
  savings_model: r.model,
  thresholds: r.conditions,
}));

/* ------------------------------ architecture ----------------------------- */

export const ARCH = {
  account_id: "123456789012",
  region: "ap-south-1",
  vpc: "vpc-0a19b73cd45e6f281",
  azs: [
    {
      id: "ap-south-1a",
      subnets: [
        {
          id: "subnet-0be71c93a2df4508e",
          cidr: "10.0.1.0/24",
          tier: "public",
          nodes: [
            {
              id: "i-0a41c7d9e2b8f0c31",
              kind: "ec2",
              name: "prod-web-01",
              exposed: true,
              encrypted: true,
              sgs: ["sg-1", "sg-2"],
            },
            {
              id: "i-07be2c4f1a9d3e650",
              kind: "ec2",
              name: "prod-web-02",
              exposed: true,
              encrypted: true,
              sgs: ["sg-1"],
            },
            {
              id: "alb-prod-edge",
              kind: "elb",
              name: "prod-edge-alb",
              exposed: true,
              encrypted: true,
              sgs: ["sg-1"],
            },
          ],
        },
        {
          id: "subnet-04c8e1a7bd93f2065",
          cidr: "10.0.11.0/24",
          tier: "private",
          nodes: [
            {
              id: "db-billing-primary",
              kind: "rds",
              name: "billing-primary",
              exposed: false,
              encrypted: true,
              sgs: ["sg-3"],
            },
            {
              id: "fn-auth-edge-22",
              kind: "lambda",
              name: "auth-edge-22",
              exposed: false,
              encrypted: false,
              sgs: ["sg-4"],
            },
          ],
        },
      ],
    },
    {
      id: "ap-south-1b",
      subnets: [
        {
          id: "subnet-09d2f6b48ae15c730",
          cidr: "10.0.2.0/24",
          tier: "public",
          nodes: [
            {
              id: "i-0f52a8d31c7be9042",
              kind: "ec2",
              name: "search-idx-14",
              exposed: true,
              encrypted: false,
              sgs: ["sg-2"],
            },
          ],
        },
        {
          id: "subnet-02a6c94f7be08d135",
          cidr: "10.0.12.0/24",
          tier: "private",
          nodes: [
            {
              id: "db-billing-replica",
              kind: "rds",
              name: "billing-replica",
              exposed: false,
              encrypted: true,
              sgs: ["sg-3"],
            },
            {
              id: "i-06c1b93e2a8f4d075",
              kind: "ec2",
              name: "data-etl-31",
              exposed: false,
              encrypted: true,
              sgs: ["sg-4"],
            },
            {
              id: "fn-media-thumb",
              kind: "lambda",
              name: "media-thumbnailer",
              exposed: false,
              encrypted: true,
              sgs: ["sg-4"],
            },
          ],
        },
      ],
    },
  ],
  global_nodes: [
    {
      id: "media-cdn-4f2a91",
      kind: "s3",
      name: "media-cdn-4f2a91",
      exposed: true,
      encrypted: false,
      sgs: [],
    },
    {
      id: "role/platform-deploy",
      kind: "iam",
      name: "platform-deploy",
      exposed: false,
      encrypted: true,
      sgs: [],
    },
  ],
};

export const SG_DETAILS: Record<string, { id: string; name: string; rules: string[] }> = {
  "sg-1": {
    id: "sg-051b8ad3f74c9e102",
    name: "web-edge",
    rules: ["ingress tcp/443 0.0.0.0/0", "ingress tcp/22 0.0.0.0/0", "egress all 0.0.0.0/0"],
  },
  "sg-2": {
    id: "sg-0d73f92c1ab5e6470",
    name: "app-tier",
    rules: ["ingress tcp/8080 sg-1", "egress all 0.0.0.0/0"],
  },
  "sg-3": {
    id: "sg-08c2e51bd97a34f60",
    name: "db-tier",
    rules: ["ingress tcp/5432 sg-2", "egress none"],
  },
  "sg-4": {
    id: "sg-0917ae43c26b8f501",
    name: "internal-svc",
    rules: ["ingress tcp/443 10.0.0.0/16", "egress tcp/443 0.0.0.0/0"],
  },
};

export const ROUTE_TABLES: Record<string, string[]> = {
  public: ["10.0.0.0/16 → local", "0.0.0.0/0 → igw-0b7c31a9e"],
  private: ["10.0.0.0/16 → local", "0.0.0.0/0 → nat-05f19c8ad"],
};

export function assetFindings(uid: string) {
  return FINDINGS.filter((f) => f.arn === uid);
}
export function assetRecommendations(uid: string) {
  return RECOMMENDATIONS.filter((r) => r.resource_uid === uid);
}

export const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: n < 100 ? 2 : 0,
  });

/* ── the architecture scene ────────────────────────────────────────────
   The scene graph is the diagram: a containment tree plus, on every node,
   where it draws inside its container - band, lane, rank, anchor, span. It
   comes from `providers/common/topology/model.yaml` via the API, so the
   shape is provider-neutral and the renderer never needs to know which
   cloud produced it.

   `ARCH` above is the design-system fixture. Rather than keep two renderers
   in step, it is adapted into the same scene shape, so the page has exactly
   one code path whether the backend is live or absent.                     */

export type ScenePosition = {
  role: string;
  band: string | null;
  lane: string | null;
  rank: number;
  anchor: string;
  order: number;
  span?: string[];
  tier?: string;
  cluster?: string | null;
  entry?: boolean;
  assumed?: boolean;
  /* The ORDER of the taxonomy axes, not just their names. Without these the
     view sorts lanes and subcategories by the alphabet of whatever the first
     member happens to be called, which is what `taxonomy_ranks()` exists to
     prevent. */
  category?: string;
  subcategory?: string;
  sub_rank?: number;
  lane_rank?: number;
  /* Where along a border a door sits, and which END of it.
     `edge_rank` orders things ALONG an arm; `edge_align` says where the run
     begins, which every strip decided for itself (centre) until an account's
     top line needed two ends with different questions at each. */
  edge_rank?: number;
  edge_align?: string;
};

export type SceneNode = {
  key: string;
  type: string;
  id: string;
  name: string;
  arn?: string | null;
  layer: number | null;
  layer_name: string | null;
  overlay?: string | null;
  position?: ScenePosition;
  children: SceneNode[];
};

export type SceneEdge = {
  source_key: string;
  target_key: string;
  edge_type: string;
  external?: boolean;
  mechanism?: string;
  confidence?: string;
};

export type SceneDoc = {
  account: string;
  region: string;
  tree: SceneNode;
  counts?: Record<string, number>;
  /** Arrows the canvas draws — containment and attachment removed, since
      nesting already says them. */
  edges?: SceneEdge[];
  /** Every edge, unfiltered. Panels read this: a listener's own panel has to
      name the load balancer it is attached to, and the canvas list drops
      exactly those. */
  relations?: SceneEdge[];
  /* Overlay buckets are nodes ALREADY placed in the tree, grouped so a
     renderer can hide identity or encryption without disturbing layout. */
  overlays?: Record<string, SceneNode[]>;
  meta?: { assets?: number; edges?: number; account_name?: string };
};

const pos = (o: Partial<ScenePosition>): ScenePosition => ({
  role: "",
  band: null,
  lane: null,
  rank: 0,
  anchor: "in",
  order: 0,
  ...o,
});

/** The fixture, in scene shape — one renderer, live or not. */
function sceneFromFixture(): SceneDoc {
  const leaf = (n: { id: string; kind: string; name: string }, role: string): SceneNode => ({
    key: `${n.kind}:${n.id}`,
    type: n.kind,
    id: n.id,
    name: n.name,
    layer: 5,
    layer_name: "workload",
    children: [],
    position: pos({ role, band: "compute", rank: 20 }),
  });

  return {
    account: ARCH.account_id,
    region: ARCH.region,
    counts: {},
    tree: {
      key: `account:${ARCH.account_id}`,
      type: "account",
      id: ARCH.account_id,
      name: ARCH.account_id,
      layer: 0,
      layer_name: "account",
      position: pos({ role: "account", band: "account", rank: 10 }),
      children: [
        {
          key: `region:${ARCH.region}`,
          type: "region",
          id: ARCH.region,
          name: ARCH.region,
          layer: 1,
          layer_name: "region",
          position: pos({ role: "region", band: "region", rank: 20 }),
          children: [
            {
              key: `vpc:${ARCH.vpc}`,
              type: "vpc",
              id: ARCH.vpc,
              name: ARCH.vpc,
              layer: 2,
              layer_name: "vpc",
              position: pos({ role: "network", band: "network", rank: 20 }),
              children: ARCH.azs.map((az, i) => ({
                key: `az:${az.id}`,
                type: "az",
                id: az.id,
                name: az.id,
                layer: 3,
                layer_name: "az",
                position: pos({ role: "zone", band: "zones", rank: (i + 1) * 10 }),
                children: az.subnets.map((sn) => ({
                  key: `subnet:${sn.id}`,
                  type: "ec2.subnet",
                  id: sn.id,
                  name: sn.cidr,
                  layer: 4,
                  layer_name: "subnet",
                  position: pos({
                    role: "segment",
                    band: "segments",
                    tier: sn.tier,
                    rank: sn.tier === "public" ? 10 : sn.tier === "private" ? 20 : 30,
                  }),
                  children: sn.nodes.map((n) => leaf(n, "flow.compute")),
                })),
              })),
            },
            ...ARCH.global_nodes.map((n) => ({
              ...leaf(n, "datastore"),
              layer: 8,
              layer_name: "regional",
              position: pos({ role: "datastore", band: "services", lane: "datastore", rank: 50 }),
            })),
          ],
        },
      ],
    },
  };
}

const liveScene = (live as { scene?: SceneDoc | null }).scene ?? null;

export const SCENE: SceneDoc = liveScene ?? sceneFromFixture();
export const IS_LIVE_SCENE = liveScene !== null;

/** Security-group codes carried on a node, for the overlay badges. */
export const sgCodesFor = (n: SceneNode): string[] =>
  (n.children || []).filter((c) => c.type.endsWith("security_group")).map((c) => c.id);

/* The estate's shape, for the overview.
 *
 * Counted from the scene rather than the asset list, because the question is
 * "how is this shaped" and only the scene knows what contains what. Falls back
 * to zero rather than guessing when no scene has been built. */
function countRole(role: string): number {
  const seen = new Set<string>();
  const walk = (n: SceneNode) => {
    if ((n.position?.role ?? "") === role) seen.add(n.key);
    (n.children ?? []).forEach(walk);
  };
  if (SCENE?.tree) walk(SCENE.tree);
  return seen.size;
}

export const ACCOUNT_COUNT = Math.max(1, countRole("account"));
export const REGION_COUNT = Math.max(1, countRole("region"));
export const NETWORK_COUNT = countRole("network");
