import { AWS_ICON_IDS } from "./aws-icon-sprite";

/**
 * AWS service icons, inline.
 *
 * Not fetched: AWS's official Architecture Icons pack sits behind a browser
 * download with terms acceptance, and the `diagrams` package ships class names
 * with no image files. Inline SVG also inherits `currentColor`, so one glyph
 * works on both themes at any size - which downloaded PNGs would not.
 *
 * Colours follow AWS's own category palette. The container is a light tint and
 * the icon is full strength, so the icon is the only saturated thing in a node
 * and a reader sees compute-or-storage before reading a single label.
 */

export const CATEGORY: Record<string, string> = {
  compute: "rgb(237 113 0)", // #ED7100
  storage: "rgb(122 161 22)", // #7AA116
  network: "rgb(140 79 255)", // #8C4FFF
  security: "rgb(221 52 76)", // #DD344C
  integration: "rgb(231 21 123)", // #E7157B
  database: "rgb(201 37 209)", // #C925D1
  ml: "rgb(1 168 141)", // #01A88D
  neutral: "rgb(100 116 139)",
};

/** resource_key → [icon id, category]. Falls back to the service segment. */
const MAP: Record<string, [string, string]> = {
  "ec2.instance": ["ec2", "compute"],
  "ec2.volume": ["ebs", "compute"],
  "ec2.network_interface": ["eni", "compute"],
  "ec2.vpc": ["vpc", "network"],
  "ec2.subnet": ["subnet", "network"],
  "ec2.security_group": ["sg", "security"],
  "ec2.network_acl": ["nacl", "network"],
  "ec2.route_table": ["rt", "network"],
  "ec2.internet_gateway": ["igw", "network"],
  "ec2.nat_gateway": ["nat", "network"],
  "ec2.vpc_endpoint": ["endpoint", "network"],
  "ec2.transit_gateway": ["tgw", "network"],
  "ec2.image": ["ami", "compute"],
  "ec2.snapshot": ["ebs", "storage"],
  "ec2.elastic_ip": ["eip", "network"],
  "s3.bucket": ["s3", "storage"],
  "lambda.function": ["lambda", "compute"],
  "ecs.cluster": ["ecs", "compute"],
  "eks.cluster": ["ecs", "compute"],
  "rds.db_instance": ["rds", "database"],
  "dynamodb.table": ["ddb", "database"],
  "kms.key": ["kms", "security"],
  "iam.role": ["role", "security"],
  "iam.policy": ["iam", "security"],
  "iam.user": ["iam", "security"],
  "iam.instance_profile": ["role", "security"],
  "secretsmanager.secret": ["kms", "security"],
  "acm.certificate": ["acm", "security"],
  "sns.topic": ["sns", "integration"],
  "sqs.queue": ["sqs", "integration"],
  "elbv2.load_balancer": ["elb", "network"],
  "elb.load_balancer": ["elb", "network"],
  "elbv2.target_group": ["tg", "network"],
  "cloudfront.distribution": ["cf", "integration"],
  "route53.hosted_zone": ["r53", "integration"],
  "ram.resource_share": ["share", "security"],
  "directconnect.connection": ["dx", "network"],
};

const BY_SERVICE: Record<string, [string, string]> = {
  ec2: ["ec2", "compute"],
  s3: ["s3", "storage"],
  lambda: ["lambda", "compute"],
  iam: ["iam", "security"],
  kms: ["kms", "security"],
  rds: ["rds", "database"],
  dynamodb: ["ddb", "database"],
  sns: ["sns", "integration"],
  sqs: ["sqs", "integration"],
  elbv2: ["elb", "network"],
  elb: ["elb", "network"],
  cloudfront: ["cf", "integration"],
  route53: ["r53", "integration"],
  ecs: ["ecs", "compute"],
  eks: ["ecs", "compute"],
  // Services the wider sweep surfaced. No bespoke glyph yet, but the category
  // is known, so they read as networking or storage rather than as unknowns.
  logs: ["logs", "integration"],
  events: ["events", "integration"],
  scheduler: ["events", "integration"],
  mediaconvert: ["sqs", "integration"],
  "pinpoint-sms-voice-v2": ["sns", "integration"],
  route53resolver: ["r53", "network"],
  apigatewayv2: ["api", "network"],
  apigateway: ["api", "network"],
  docdb: ["rds", "database"],
  memorydb: ["ddb", "database"],
  elasticache: ["ddb", "database"],
  redshift: ["rds", "database"],
  ecr: ["ecr", "compute"],
  ssm: ["ssm", "security"],
  appconfig: ["ssm", "integration"],
  secretsmanager: ["kms", "security"],
  acm: ["acm", "security"],
  ram: ["iam", "security"],
};

export function iconFor(resourceKey = ""): [string, string] {
  const exact = MAP[resourceKey];
  if (exact) return exact;
  const service = resourceKey.split(".")[0] ?? "";
  return BY_SERVICE[service] ?? ["generic", "neutral"];
}

/** The category colour for a resource type — one source for every surface. */
export const colourFor = (resourceKey: string) =>
  CATEGORY[iconFor(resourceKey)[1]] ?? CATEGORY["neutral"]!;

/**
 * A resource glyph.
 *
 * Prefers AWS's OFFICIAL icon - a category-coloured tile with a white mark,
 * which is the visual language anyone who has used the AWS console already
 * reads. Falls back to the hand-drawn line set for the long tail the official
 * pack has no icon for, so nothing ever renders as a blank.
 */
export function Icon({
  resourceKey,
  size = 16,
  title,
}: {
  resourceKey: string;
  size?: number;
  title?: string;
}) {
  // Most specific first. A volume, an interface and an internet gateway are
  // all `ec2.*`, and the service tile makes them identical - which is the one
  // distinction the diagram exists to draw.
  const service = resourceKey.split(".")[0] ?? "";
  const official = AWS_ICON_IDS.has(`res-${resourceKey}`)
    ? `res-${resourceKey}`
    : AWS_ICON_IDS.has(service)
      ? service
      : null;
  if (official) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        className="shrink-0 rounded-[3px]"
        role="img"
        aria-label={title || resourceKey}
      >
        <use href={`#aws-${official}`} />
      </svg>
    );
  }
  const [id, category] = iconFor(resourceKey);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={{
        color: CATEGORY[category] ?? CATEGORY["neutral"],
        flex: "none",
        pointerEvents: "none",
      }}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={title || resourceKey}
    >
      <use href={`#awsi-${id}`} />
    </svg>
  );
}

/** Rendered once near the root; every <Icon> references it. */
export function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs>
        <symbol id="awsi-ec2" viewBox="0 0 24 24">
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <rect x="8" y="8" width="8" height="8" rx="1" />
          <path d="M10 2v2M14 2v2M10 20v2M14 20v2M2 10h2M2 14h2M20 10h2M20 14h2" />
        </symbol>
        <symbol id="awsi-ebs" viewBox="0 0 24 24">
          <rect x="4" y="6" width="16" height="12" rx="2" />
          <circle cx="8" cy="12" r="1.4" />
          <path d="M12 12h5" />
        </symbol>
        <symbol id="awsi-eni" viewBox="0 0 24 24">
          <rect x="3" y="9" width="18" height="6" rx="1.5" />
          <path d="M7 9V5M12 9V5M17 9V5" />
        </symbol>
        <symbol id="awsi-vpc" viewBox="0 0 24 24">
          <rect x="2" y="4" width="20" height="16" rx="2" strokeDasharray="3 2" />
          <circle cx="8" cy="12" r="2" />
          <circle cx="16" cy="12" r="2" />
          <path d="M10 12h4" />
        </symbol>
        <symbol id="awsi-subnet" viewBox="0 0 24 24">
          <rect x="3" y="6" width="18" height="12" rx="2" />
          <path d="M3 12h18" />
        </symbol>
        <symbol id="awsi-sg" viewBox="0 0 24 24">
          <path d="M12 3l7 3v6c0 4-3 7.5-7 9-4-1.5-7-5-7-9V6z" />
        </symbol>
        <symbol id="awsi-nacl" viewBox="0 0 24 24">
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <path d="M8 9h8M8 12h8M8 15h5" />
        </symbol>
        <symbol id="awsi-rt" viewBox="0 0 24 24">
          <circle cx="5" cy="12" r="2" />
          <circle cx="19" cy="6" r="2" />
          <circle cx="19" cy="18" r="2" />
          <path d="M7 12h5l5-6M12 12l5 6" />
        </symbol>
        <symbol id="awsi-igw" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" />
          <path d="M4 12h16M12 4c2.5 2.6 2.5 12.4 0 16M12 4c-2.5 2.6-2.5 12.4 0 16" />
        </symbol>
        <symbol id="awsi-nat" viewBox="0 0 24 24">
          <rect x="3" y="8" width="18" height="8" rx="2" />
          <path d="M7 12h10M14 9l3 3-3 3" />
        </symbol>
        <symbol id="awsi-endpoint" viewBox="0 0 24 24">
          <circle cx="6" cy="12" r="3" />
          <circle cx="18" cy="12" r="3" />
          <path d="M9 12h6" strokeDasharray="2 2" />
        </symbol>
        <symbol id="awsi-tgw" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v6M12 15v6M3 12h6M15 12h6" />
        </symbol>
        <symbol id="awsi-eip" viewBox="0 0 24 24">
          <circle cx="12" cy="9" r="4" />
          <path d="M12 13v8M9 18h6" />
        </symbol>
        <symbol id="awsi-ami" viewBox="0 0 24 24">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M3 15l5-4 4 3 3-2 6 4" />
          <circle cx="8.5" cy="9.5" r="1.3" />
        </symbol>
        <symbol id="awsi-s3" viewBox="0 0 24 24">
          <ellipse cx="12" cy="6" rx="8" ry="3" />
          <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
          <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
        </symbol>
        <symbol id="awsi-lambda" viewBox="0 0 24 24">
          <path d="M6 20 13 4h3l5 16" />
          <path d="M4 20h5" />
        </symbol>
        <symbol id="awsi-ecs" viewBox="0 0 24 24">
          <rect x="3" y="4" width="7" height="7" rx="1" />
          <rect x="14" y="4" width="7" height="7" rx="1" />
          <rect x="3" y="13" width="7" height="7" rx="1" />
          <rect x="14" y="13" width="7" height="7" rx="1" />
        </symbol>
        <symbol id="awsi-rds" viewBox="0 0 24 24">
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
        </symbol>
        <symbol id="awsi-ddb" viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 9h18M9 9v11" />
        </symbol>
        <symbol id="awsi-logs" viewBox="0 0 24 24">
          <path d="M5 4h9l5 5v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
          <path d="M14 4v5h5M8 13h7M8 16h5" />
        </symbol>
        <symbol id="awsi-events" viewBox="0 0 24 24">
          <path d="M13 2 4 14h7l-1 8 9-12h-7z" />
        </symbol>
        <symbol id="awsi-api" viewBox="0 0 24 24">
          <path d="M9 7 4 12l5 5M15 7l5 5-5 5M13 5l-2 14" />
        </symbol>
        <symbol id="awsi-ecr" viewBox="0 0 24 24">
          <path d="M3 8l9-4 9 4-9 4-9-4z" />
          <path d="M3 12l9 4 9-4M3 16l9 4 9-4" />
        </symbol>
        <symbol id="awsi-ssm" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
        </symbol>
        <symbol id="awsi-kms" viewBox="0 0 24 24">
          <circle cx="8" cy="12" r="4" />
          <path d="M12 12h9M17 12v4M20 12v3" />
        </symbol>
        <symbol id="awsi-iam" viewBox="0 0 24 24">
          <circle cx="12" cy="8" r="3.5" />
          <path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7" />
        </symbol>
        <symbol id="awsi-role" viewBox="0 0 24 24">
          <path d="M12 3l7 3v6c0 4-3 7.5-7 9-4-1.5-7-5-7-9V6z" />
          <path d="M9 12l2 2 4-4" />
        </symbol>
        <symbol id="awsi-acm" viewBox="0 0 24 24">
          <rect x="3" y="5" width="18" height="12" rx="2" />
          <circle cx="12" cy="11" r="2.5" />
          <path d="M10 15l-1 5 3-2 3 2-1-5" />
        </symbol>
        <symbol id="awsi-sns" viewBox="0 0 24 24">
          <path d="M4 10v4h4l5 4V6l-5 4z" />
          <path d="M17 9a4 4 0 0 1 0 6" />
          <path d="M20 7a7 7 0 0 1 0 10" />
        </symbol>
        <symbol id="awsi-sqs" viewBox="0 0 24 24">
          <rect x="3" y="7" width="5" height="10" rx="1" />
          <rect x="10" y="7" width="5" height="10" rx="1" />
          <rect x="17" y="7" width="4" height="10" rx="1" />
        </symbol>
        <symbol id="awsi-elb" viewBox="0 0 24 24">
          <circle cx="12" cy="5" r="2.5" />
          <circle cx="5" cy="19" r="2.5" />
          <circle cx="19" cy="19" r="2.5" />
          <path d="M12 7.5v4M12 11.5H5v5M12 11.5h7v5" />
        </symbol>
        <symbol id="awsi-tg" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="4" />
          <circle cx="12" cy="12" r="1" />
        </symbol>
        <symbol id="awsi-cf" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" />
          <path d="M12 4v16M4 12h16M7 6c3 3 7 3 10 0M7 18c3-3 7-3 10 0" />
        </symbol>
        <symbol id="awsi-r53" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" />
          <path d="M12 4c-3 4-3 12 0 16M12 4c3 4 3 12 0 16M5 9h14M5 15h14" />
        </symbol>
        <symbol id="awsi-share" viewBox="0 0 24 24">
          <circle cx="18" cy="5" r="2.5" />
          <circle cx="6" cy="12" r="2.5" />
          <circle cx="18" cy="19" r="2.5" />
          <path d="M8.3 10.8l7.4-4.3M8.3 13.2l7.4 4.3" />
        </symbol>
        <symbol id="awsi-dx" viewBox="0 0 24 24">
          <rect x="3" y="8" width="7" height="8" rx="1" />
          <rect x="14" y="8" width="7" height="8" rx="1" />
          <path d="M10 12h4" />
        </symbol>
        <symbol id="awsi-generic" viewBox="0 0 24 24">
          <rect x="4" y="4" width="16" height="16" rx="2" />
        </symbol>
      </defs>
    </svg>
  );
}
