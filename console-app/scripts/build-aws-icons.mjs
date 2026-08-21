/**
 * Turn AWS's official Architecture Icons into a sprite this app can inline.
 *
 *   node scripts/build-aws-icons.mjs <path-to-unzipped-icon-package>
 *
 * AWS publishes the pack quarterly and permits its use for architecture
 * diagrams, which is exactly what this page draws. We vendor only the ~50
 * icons the estate actually uses rather than all 3,629 - the full pack is
 * 14MB, and shipping it to a browser to draw fifty boxes would be absurd.
 *
 * Each official icon is a category-coloured tile with a white glyph. That IS
 * AWS's visual language, so we keep it intact rather than recolouring: a
 * reader who knows the AWS console recognises the tile before the label.
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const PACK = process.argv[2];
if (!PACK || !existsSync(PACK)) {
  console.error("usage: node scripts/build-aws-icons.mjs <unzipped-icon-package>");
  process.exit(1);
}

/* service segment of a resource_key -> official icon basename */
const SERVICE_ICON = {
  ec2: "Amazon-EC2",
  s3: "Amazon-Simple-Storage-Service",
  lambda: "AWS-Lambda",
  iam: "AWS-Identity-and-Access-Management",
  kms: "AWS-Key-Management-Service",
  rds: "Amazon-RDS",
  elbv2: "Elastic-Load-Balancing",
  elb: "Elastic-Load-Balancing",
  route53: "Amazon-Route-53",
  route53resolver: "Amazon-Route-53",
  cloudfront: "Amazon-CloudFront",
  secretsmanager: "AWS-Secrets-Manager",
  ecs: "Amazon-Elastic-Container-Service",
  ecr: "Amazon-Elastic-Container-Registry",
  efs: "Amazon-EFS",
  docdb: "Amazon-DocumentDB",
  neptune: "Amazon-Neptune",
  elasticache: "Amazon-ElastiCache",
  memorydb: "Amazon-MemoryDB",
  redshift: "Amazon-Redshift",
  sns: "Amazon-Simple-Notification-Service",
  sqs: "Amazon-Simple-Queue-Service",
  events: "Amazon-EventBridge",
  scheduler: "Amazon-EventBridge",
  stepfunctions: "AWS-Step-Functions",
  cloudwatch: "Amazon-CloudWatch",
  logs: "Amazon-CloudWatch",
  cloudtrail: "AWS-CloudTrail",
  config: "AWS-Config",
  cloudformation: "AWS-CloudFormation",
  ssm: "AWS-Systems-Manager",
  athena: "Amazon-Athena",
  sagemaker: "Amazon-SageMaker-AI",
  apigatewayv2: "Amazon-API-Gateway",
  apigateway: "Amazon-API-Gateway",
  apprunner: "AWS-App-Runner",
  appconfig: "AWS-AppConfig",
  acm: "AWS-Certificate-Manager",
  autoscaling: "Amazon-EC2-Auto-Scaling",
  "autoscaling-plans": "Amazon-EC2-Auto-Scaling",
  batch: "AWS-Batch",
  codeartifact: "AWS-CodeArtifact",
  gamelift: "Amazon-GameLift-Servers",
  greengrass: "AWS-IoT-Greengrass",
  mediaconvert: "AWS-Elemental-MediaConvert",
  organizations: "AWS-Organizations",
  servicecatalog: "AWS-Service-Catalog",
  snowball: "AWS-Snowball",
  "service-quotas": "AWS-Trusted-Advisor",
  "pinpoint-sms-voice-v2": "AWS-End-User-Messaging",
  eks: "Amazon-Elastic-Kubernetes-Service",
  dynamodb: "Amazon-DynamoDB",
  opensearch: "Amazon-OpenSearch-Service",
  bedrock: "Amazon-Bedrock",
  glue: "AWS-Glue",
  emr: "Amazon-EMR",
  backup: "AWS-Backup",
  guardduty: "Amazon-GuardDuty",
  securityhub: "AWS-Security-Hub",
  inspector2: "Amazon-Inspector",
  fsx: "Amazon-FSx",
  transfer: "AWS-Transfer-Family",
  dms: "AWS-Database-Migration-Service",
  directconnect: "AWS-Direct-Connect",
  vpc: "Amazon-Virtual-Private-Cloud",
};

/* resource_key -> official RESOURCE icon.
   This layer matters more than it looks. Mapping by SERVICE alone gave an
   instance, a volume, an interface, an internet gateway and a route table the
   same orange EC2 tile, because every one of them is an `ec2.*` type - which
   is exactly the distinction the diagram exists to show. AWS publishes a
   per-resource icon for each; this is where they get used. */
const RESOURCE_ICON = {
  "ec2.instance": "Amazon-EC2_Instance",
  "ec2.spot_instance_request": "Amazon-EC2_Spot-Instance",
  "ec2.eip": "Amazon-EC2_Elastic-IP-Address",
  "ec2.ami": "Amazon-EC2_AMI",
  "ec2.image": "Amazon-EC2_AMI",
  "ec2.volume": "Amazon-Elastic-Block-Store_Volume",
  "ec2.ebs_snapshot": "Amazon-Elastic-Block-Store_Snapshot",
  "ec2.snapshot": "Amazon-Elastic-Block-Store_Snapshot",
  "ec2.network_interface": "Amazon-VPC_Elastic-Network-Interface",
  "ec2.internet_gateway": "Amazon-VPC_Internet-Gateway",
  "ec2.egress_only_internet_gateway": "Amazon-VPC_Internet-Gateway",
  "ec2.nat_gateway": "Amazon-VPC_NAT-Gateway",
  "ec2.vpc_endpoint": "Amazon-VPC_Endpoints",
  "ec2.network_acl": "Amazon-VPC_Network-Access-Control-List",
  "ec2.route_table": "Amazon-VPC_Router",
  "ec2.vpc_peering_connection": "Amazon-VPC_Peering-Connection",
  "ec2.vpn_gateway": "Amazon-VPC_VPN-Gateway",
  "ec2.vpn_connection": "Amazon-VPC_VPN-Connection",
  "ec2.customer_gateway": "Amazon-VPC_Customer-Gateway",
  "ec2.flow_log": "Amazon-VPC_Flow-Logs",
  "ec2.vpc": "Amazon-VPC_Virtual-private-cloud-VPC",
  "ec2.transit_gateway": "AWS-Transit-Gateway_Attachment",
  "ec2.transit_gateway_attachment": "AWS-Transit-Gateway_Attachment",
  "s3.bucket": "Amazon-Simple-Storage-Service_Bucket",
  "lambda.function": "AWS-Lambda_Lambda-Function",
  "dynamodb.table": "Amazon-DynamoDB_Table",
  "sqs.queue": "Amazon-Simple-Queue-Service_Queue",
  "sns.topic": "Amazon-Simple-Notification-Service_Topic",
  "iam.role": "AWS-Identity-Access-Management_Role",
  "iam.instance_profile": "AWS-Identity-Access-Management_Role",
  "route53.hosted_zone": "Amazon-Route-53_Route-Table",
  "route53resolver.resolver_endpoint": "Amazon-Route-53_Resolver",
};

/* containers use AWS's own GROUP icons, which are what an architect draws
   the boxes with - not a service glyph shrunk down. */
const GROUP_ICON = {
  account: "AWS-Account",
  region: "Region",
  vpc: "Virtual-private-cloud-VPC",
  // AWS ships no Availability Zone icon on purpose - the convention is a
  // dashed box with a label, not a tile. We follow that rather than invent one.
  subnet: "Private-subnet",
  "subnet-public": "Public-subnet",
  cloud: "AWS-Cloud",
  autoscaling_group: "Auto-Scaling-group",
  datacenter: "Corporate-data-center",
};

const svgFiles = new Map();
const walk = (dir) => {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name !== "__MACOSX") walk(p);
    } else if (e.name.endsWith(".svg")) svgFiles.set(e.name, p);
  }
};
walk(PACK);

/** Strip the XML preamble and title; keep the drawing. */
function body(file) {
  const raw = readFileSync(file, "utf8");
  const viewBox = /viewBox="([^"]+)"/.exec(raw)?.[1] ?? "0 0 64 64";
  const inner = raw
    .slice(raw.indexOf(">", raw.indexOf("<svg")) + 1, raw.lastIndexOf("</svg>"))
    .replace(/<title>[\s\S]*?<\/title>/g, "")
    .replace(/\s+id="[^"]*"/g, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return { viewBox, inner };
}

const symbols = [];
const missing = [];
const emit = (id, candidates) => {
  for (const name of candidates) {
    const file = svgFiles.get(name);
    if (!file) continue;
    const { viewBox, inner } = body(file);
    symbols.push(`  <symbol id="aws-${id}" viewBox="${viewBox}">${inner}</symbol>`);
    return true;
  }
  missing.push(id);
  return false;
};

for (const [key, icon] of Object.entries(RESOURCE_ICON)) {
  emit(`res-${key}`, [`Res_${icon}_48.svg`]);
}
for (const [svc, icon] of Object.entries(SERVICE_ICON)) {
  emit(svc, [`Arch_${icon}_48.svg`, `Arch_${icon}_64.svg`]);
}
for (const [key, icon] of Object.entries(GROUP_ICON)) {
  emit(`grp-${key}`, [`${icon}_32.svg`, `${icon}_48.svg`]);
}

const out = `/* GENERATED by scripts/build-aws-icons.mjs — do not edit by hand.
   Source: AWS Architecture Icons, official package. AWS permits these assets
   to be used for creating architecture diagrams, which is what this page is.
   Re-run the script against a newer quarterly pack to refresh. */

export const AWS_ICON_IDS = new Set([
${[...symbols.map((s) => `  "${/id="aws-([^"]+)"/.exec(s)[1]}",`)].join("\n")}
]);

export function AwsIconSprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs>
${symbols.join("\n")}
      </defs>
    </svg>
  );
}
`;
writeFileSync("src/components/console/aws-icon-sprite.tsx", out);
console.log(
  `wrote ${symbols.length} official icons` +
    (missing.length ? `; no match for: ${missing.join(", ")}` : ""),
);
