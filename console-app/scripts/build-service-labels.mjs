/**
 * What to call each service on the diagram.
 *
 *   node scripts/build-service-labels.mjs
 *
 * A group of Lambda functions should be labelled "Lambda", not "functions".
 * The taxonomy stays generic so it holds for every cloud - `compute.serverless`
 * means the same thing on AWS, Azure and GCP - but a reader does not think in
 * taxonomies. They think in products, and the diagram should say the product.
 *
 * The names are not invented here. `cfn_types.csv` carries AWS's own
 * CloudFormation namespace for every resource - `AWS::Lambda::Function`,
 * `AWS::ElastiCache::CacheCluster` - and the middle segment IS the brand name,
 * already correctly cased. That covers 41 of the 48 services in this estate
 * without anyone typing a name.
 *
 * The override table below is for the rest: services CloudFormation names
 * differently from the console (`ApiGatewayV2` is called API Gateway), spells
 * without the space AWS writes (`AppRunner` is App Runner), or does not carry
 * at all. Short by design - every entry is a claim that AWS's own data is
 * wrong for display, so each one should be arguable.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSV = join(HERE, "..", "..", "providers", "aws", "catalog", "cfn_types.csv");
const CATALOG = join(HERE, "..", "..", "providers", "aws", "catalog", "resource_catalog.csv");
const OUT = join(HERE, "..", "src", "components", "console", "service-labels.ts");

/** Where the console name differs from the CloudFormation namespace. */
const OVERRIDE = {
  acm: "Certificate Manager",
  apigateway: "API Gateway",
  apigatewayv2: "API Gateway",
  appconfig: "AppConfig",
  apprunner: "App Runner",
  autoscaling: "EC2 Auto Scaling",
  "autoscaling-plans": "Auto Scaling Plans",
  docdb: "DocumentDB",
  elb: "ELB Classic",
  elbv2: "ELB",
  es: "OpenSearch",
  events: "EventBridge",
  greengrass: "IoT Greengrass",
  logs: "CloudWatch Logs",
  "pinpoint-sms-voice-v2": "Pinpoint SMS",
  route53: "Route 53",
  route53resolver: "Route 53 Resolver",
  scheduler: "EventBridge Scheduler",
  secretsmanager: "Secrets Manager",
  "service-quotas": "Service Quotas",
  servicecatalog: "Service Catalog",
  snowball: "Snowball",
  ssm: "Systems Manager",
  stepfunctions: "Step Functions",
  // Derived labels are readable but not right for the services carrying the
  // most types — a compound service id has no separator to split on, so
  // `s3control` derives as "S3control". These are the ones worth naming.
  s3control: "S3 Control",
  macie2: "Macie",
  devicefarm: "Device Farm",
  qconnect: "Q in Connect",
  qbusiness: "Q Business",
  workmail: "WorkMail",
  workdocs: "WorkDocs",
  workspaces: "WorkSpaces",
  "customer-profiles": "Customer Profiles",
  sesv2: "SES",
  cognitoidp: "Cognito",
  "cognito-idp": "Cognito",
  bedrockagentcore: "Bedrock AgentCore",
  "bedrock-agent": "Bedrock Agent",
  opensearchserverless: "OpenSearch Serverless",
  networkmanager: "Network Manager",
  lakeformation: "Lake Formation",
  cleanrooms: "Clean Rooms",
  healthlake: "HealthLake",
  medialive: "MediaLive",
  mediaconnect: "MediaConnect",
  mediapackage: "MediaPackage",
  mediatailor: "MediaTailor",
  mediastore: "MediaStore",
  iotsitewise: "IoT SiteWise",
  iotwireless: "IoT Wireless",
  iotfleetwise: "IoT FleetWise",
  iottwinmaker: "IoT TwinMaker",
  iotevents: "IoT Events",
  iotanalytics: "IoT Analytics",
};

/* A minimal CSV reader: these files are machine-written and quote only the
   description column, so full RFC-4180 parsing would be ceremony. */
function rows(text) {
  const lines = text.split("\n").filter(Boolean);
  const head = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cells = [];
    let cur = "";
    let quoted = false;
    for (const ch of line) {
      if (ch === '"') quoted = !quoted;
      else if (ch === "," && !quoted) {
        cells.push(cur);
        cur = "";
      } else cur += ch;
    }
    cells.push(cur);
    return Object.fromEntries(head.map((h, i) => [h, cells[i] ?? ""]));
  });
}

/**
 * Services CloudFormation never names — 213 of 496, because CFN only covers
 * what it can provision. Without one, a group falls back to the type's own
 * noun, so `s3control` renders as "access grants" and `macie2` as "allow
 * lists". Derived from the service id rather than hand-written: strip a
 * trailing version, split on hyphens, and title-case, which is what AWS's own
 * console does to the same ids.
 */
function fromServiceId(id) {
  return id
    .replace(/v\d+$/, "")
    .split("-")
    .filter(Boolean)
    .map((w) => (w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ");
}

/** Every service the catalog knows, whether CloudFormation names it or not. */
function allServiceIds() {
  const out = new Set();
  for (const r of rows(readFileSync(CATALOG, "utf8"))) {
    const key = r.key || "";
    if (key.includes(".")) out.add(key.slice(0, key.indexOf(".")));
  }
  return out;
}

const votes = new Map();
for (const r of rows(readFileSync(CSV, "utf8"))) {
  const slug = r.slug || "";
  const ns = r.cfn_namespace || "";
  if (!slug.includes(".") || !ns) continue;
  const service = slug.slice(0, slug.indexOf("."));
  const tally = votes.get(service) ?? new Map();
  tally.set(ns, (tally.get(ns) ?? 0) + 1);
  votes.set(service, tally);
}

const labels = {};
for (const [service, tally] of votes) {
  // A service can appear under two namespaces when AWS renamed one; the
  // namespace that names the most resource types is the current one.
  const [best] = [...tally.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  labels[service] = best[0];
}
// Anything CloudFormation does not name gets a derived label rather than
// nothing, so no group ever falls back to a raw type noun.
for (const id of allServiceIds()) {
  if (!labels[id]) labels[id] = fromServiceId(id);
}
Object.assign(labels, OVERRIDE);

const entries = Object.entries(labels).sort(([a], [b]) => a.localeCompare(b));
const fromCfn = entries.length - Object.keys(OVERRIDE).length;

writeFileSync(
  OUT,
  `/* GENERATED by scripts/build-service-labels.mjs — do not edit.
 *
 * ${entries.length} services: ${fromCfn} named by AWS's own CloudFormation
 * namespace, ${Object.keys(OVERRIDE).length} overridden where the console
 * name differs. Re-run after changing cfn_types.csv or the override table.
 */
export const SERVICE_LABEL: Record<string, string> = {
${entries.map(([k, v]) => `  ${/^[a-z][a-z0-9]*$/.test(k) ? k : JSON.stringify(k)}: ${JSON.stringify(v)},`).join("\n")}
};
`,
);

/**
 * Which services are one product.
 *
 * A family is the longest service id that is ITSELF a service: `bedrock-agent`
 * folds into `bedrock` because `bedrock` exists, while `application-autoscaling`
 * stays itself because `application` does not. 496 ids collapse to 424
 * families with no false positives, and nothing is authored — the answer is
 * already in the service names.
 *
 * Only families with more than one member are emitted.
 *
 * Two guards, both learned the hard way. A prefix that is a common WORD rather
 * than a product absorbs unrelated services - `service` is a catalog id, so
 * `service-quotas` folded into "service". And a longer id is not always a
 * sub-product: VPC Lattice is its own thing, not part of VPC. Both are listed
 * below rather than inferred, because there is no signal in the name that
 * separates them from the real cases.
 *
 * Used for LABELS and FILTERING only. Drawing a family as a box on the canvas
 * was built and reverted: it rendered in zero cases against the one estate
 * available to test it, which is not a feature, it is a guess.
 */
const NOT_A_FAMILY = new Set(["service", "vpc", "application", "compute", "data"]);
const ids = [...allServiceIds()].sort();
const familyOf = (id) => {
  const parts = id.split("-");
  for (let i = parts.length - 1; i > 0; i -= 1) {
    const candidate = parts.slice(0, i).join("-");
    if (ids.includes(candidate) && !NOT_A_FAMILY.has(candidate)) return candidate;
  }
  return id;
};
const families = {};
for (const id of ids) {
  const f = familyOf(id);
  if (f !== id) families[id] = f;
}
const grouped = new Set(Object.values(families));

writeFileSync(
  join(HERE, "..", "src", "components", "console", "service-families.ts"),
  `/* GENERATED by scripts/build-service-labels.mjs — do not edit.
 *
 * ${Object.keys(families).length} services belong to ${grouped.size} families.
 * A family is the longest service id that is itself a service, so nothing here
 * is authored — see the generator.
 */
export const SERVICE_FAMILY: Record<string, string> = {
${Object.entries(families)
  .sort()
  .map(([k, v]) => `  ${JSON.stringify(k)}: ${JSON.stringify(v)},`)
  .join("\n")}
};
`,
);

console.log(`${OUT}: ${entries.length} services (${fromCfn} from CloudFormation)`);
console.log(
  `service-families.ts: ${Object.keys(families).length} services in ${grouped.size} families`,
);
