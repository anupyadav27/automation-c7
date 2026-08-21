import * as React from "react";
import { AlertOctagon, AlertTriangle, Info, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Domain, FinopsCategory, Provider, Severity } from "@/lib/mock-data";

/* ---------------------------------------------------------------------------
 * THE CHIP FORMULA — one badge component for the whole product.
 * bg = color @12%, border = color @30%, text = color, radius 5, 11px/700,
 * padding 2px 8px 2px 6px, optional leading lucide icon at 11px/2.5 stroke.
 * ------------------------------------------------------------------------- */

export type BadgeTone =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "info"
  | "accent"
  | "green"
  | "aws"
  | "azure"
  | "gcp"
  | "k8s"
  | "oci"
  | "ibm"
  /* legacy aliases kept so every call site keeps working */
  | "slate"
  | "red"
  | "orange"
  | "amber"
  | "blue"
  | "violet"
  | "emerald";

const toneClass: Record<BadgeTone, string> = {
  critical: "chip-critical",
  high: "chip-high",
  medium: "chip-medium",
  low: "chip-low",
  info: "chip-info",
  accent: "chip-accent",
  green: "chip-green",
  aws: "chip-aws",
  azure: "chip-azure",
  gcp: "chip-gcp",
  k8s: "chip-k8s",
  oci: "chip-oci",
  ibm: "chip-ibm",
  slate: "chip-info",
  red: "chip-critical",
  orange: "chip-high",
  amber: "chip-medium",
  blue: "chip-accent",
  violet: "chip-info",
  emerald: "chip-green",
};

export function Badge({
  tone = "info",
  icon: Icon,
  children,
  className,
  title,
}: {
  tone?: BadgeTone;
  icon?: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  /** legacy prop, superseded by the icon spec */
  dot?: boolean;
  children: React.ReactNode;
  className?: string | undefined;
  title?: string | undefined;
}) {
  return (
    <span title={title} className={cn("chip", toneClass[tone], className)}>
      {Icon ? <Icon className="size-[11px] shrink-0" strokeWidth={2.5} /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

/* --------------------------- null / missing values ------------------------ */

export function EmDash({ className }: { className?: string }) {
  return <span className={cn("text-[11px] text-muted-foreground", className)}>—</span>;
}

/* --------------------------------- mono ---------------------------------- */

export function Mono({
  children,
  className,
  truncate,
}: {
  children: React.ReactNode;
  className?: string;
  truncate?: boolean;
}) {
  return <span className={cn("mono", truncate && "block truncate", className)}>{children}</span>;
}

/* ------------------------------- severity -------------------------------- */

const severityTone: Record<Severity, BadgeTone> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
};

const severityIcon: Record<
  Severity,
  React.ComponentType<{ className?: string; strokeWidth?: number }>
> = {
  critical: AlertOctagon,
  high: AlertTriangle,
  medium: AlertTriangle,
  low: Minus,
};

const severityLabel: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const severityToneOf = (s: Severity) => severityTone[s];
export const severityLabelOf = (s: Severity) => severityLabel[s];
export const severityVar = (s: Severity) => `var(--sev-${s})`;

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <Badge tone={severityTone[severity]} icon={severityIcon[severity]} className={className}>
      {severityLabel[severity]}
    </Badge>
  );
}

export function InfoBadge({ children }: { children: React.ReactNode }) {
  return (
    <Badge tone="info" icon={Info}>
      {children}
    </Badge>
  );
}

const severityDotBg: Record<Severity, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
};

export function SeverityDot({ severity }: { severity: Severity }) {
  return <span className={cn("size-1.5 shrink-0 rounded-full", severityDotBg[severity])} />;
}

/* --------------------------------- domain -------------------------------- */

const domainTone: Record<Domain, BadgeTone> = {
  compliance: "accent",
  governance: "info",
  cost: "green",
};

const domainLabel: Record<Domain, string> = {
  compliance: "Compliance",
  governance: "Governance",
  cost: "Cost",
};

export function DomainBadge({
  domain,
  className,
}: {
  domain: Domain;
  /** kept for call-site compatibility; abbreviations are no longer used */
  short?: boolean;
  className?: string;
}) {
  return (
    <Badge tone={domainTone[domain]} className={className}>
      {domainLabel[domain]}
    </Badge>
  );
}

/* -------------------------------- provider ------------------------------- */

const providerLabel: Record<Provider, string> = {
  aws: "AWS",
  azure: "Azure",
  gcp: "GCP",
  oci: "OCI",
  ibm: "IBM",
  k8s: "Kubernetes",
};

const providerTone: Record<Provider, BadgeTone> = {
  aws: "aws",
  azure: "azure",
  gcp: "gcp",
  oci: "oci",
  ibm: "ibm",
  k8s: "k8s",
};

export function ProviderBadge({ provider }: { provider: Provider }) {
  return (
    <Badge tone={providerTone[provider] ?? "info"}>{providerLabel[provider] ?? provider}</Badge>
  );
}

export function LayerBadge({ layerId, layerName }: { layerId: string; layerName?: string }) {
  return <Badge title={layerName}>{layerName ? `${layerId} ${layerName}` : layerId}</Badge>;
}

export function QualityBadge({ quality }: { quality: "real" | "derived" | "synthetic" }) {
  const label = { real: "Real", derived: "Derived", synthetic: "Synthetic" }[quality];
  const tone: BadgeTone = quality === "real" ? "green" : quality === "derived" ? "medium" : "info";
  return <Badge tone={tone}>{label}</Badge>;
}

/* -------------------------------- category ------------------------------- */

const catLabels: Record<FinopsCategory, string> = {
  waste_elimination: "Waste elimination",
  rate_optimization: "Rate optimization",
  right_sizing: "Right-sizing",
  cost_visibility: "Cost visibility",
};
export const finopsCategoryLabel = (c: FinopsCategory) => catLabels[c];

export function CategoryBadge({ category }: { category: FinopsCategory }) {
  return <Badge>{catLabels[category]}</Badge>;
}

/* ---------------------------------- chip --------------------------------- */

export function Chip({
  children,
  className,
  onClick,
  active,
}: {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-tertiary px-2 py-1 text-xs font-medium text-muted-foreground",
        onClick && "transition-colors duration-100 hover:text-foreground",
        active && "border-primary/30 bg-nav-active text-nav-active-fg",
        className,
      )}
    >
      {children}
    </Comp>
  );
}

/* ------------------------------ page header ------------------------------ */

export function PageHeader({
  title,
  subtitle,
  meta,
  actions,
  icon: Icon,
  breadcrumb,
}: {
  title: string;
  subtitle?: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  breadcrumb?: string[];
}) {
  const trail = breadcrumb ?? ["Cloud Estate", title];
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 pb-5">
      <div className="min-w-0">
        <nav className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {trail.map((t, i) => {
            const last = i === trail.length - 1;
            return (
              <React.Fragment key={t}>
                {i > 0 ? <span className="text-border-strong">/</span> : null}
                <span className={cn(last && "font-semibold text-foreground")}>{t}</span>
              </React.Fragment>
            );
          })}
        </nav>
        <div className="mt-2 flex items-center gap-2.5">
          {Icon ? <Icon className="size-[22px] shrink-0 text-primary" strokeWidth={2} /> : null}
          <h1 className="page-title truncate">{title}</h1>
        </div>
        {subtitle ? <p className="mt-1.5 text-xs text-muted-foreground">{subtitle}</p> : null}
        {meta ? <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2 pt-6">{actions}</div> : null}
    </div>
  );
}

/* --------------------------- section / card title ------------------------ */

export function SectionTitle({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <h2 className={cn("card-title", className)}>{children}</h2>;
}

/* -------------------------------- KPI card ------------------------------- */

export function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="panel px-4 py-3.5">
      <div className="label-caps">{label}</div>
      <div className="kpi-value mt-2">{value}</div>
      {sub ? <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

export function Delta({ value, invert }: { value: number; invert?: boolean }) {
  if (!value) return <span className="text-xs text-sub tnum">±0</span>;
  const up = value > 0;
  const good = invert ? !up : up;
  return (
    <span
      className={cn("text-xs font-semibold tnum", good ? "text-green" : "text-sev-high")}
      style={{ color: good ? "var(--green)" : "var(--sev-high)" }}
    >
      {up ? "↑" : "↓"}
      {Math.abs(value)}
    </span>
  );
}
