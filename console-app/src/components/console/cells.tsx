import * as React from "react";
import {
  Boxes,
  Check,
  Copy,
  Database,
  FileText,
  Globe,
  HardDrive,
  Key,
  KeyRound,
  Layers,
  Minus,
  Network,
  Route,
  Scale,
  Server,
  ShieldHalf,
  Sparkles,
  Users,
  Wrench,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { ActionTier, Severity } from "@/lib/mock-data";
import { Badge, EmDash, SeverityDot, severityLabelOf } from "@/components/console/primitives";
import { AI_FIX_CAPTION, SEVERITY_RANK, absTime, relTime, resourceLabel } from "@/lib/console-data";

/* --------------------------------- copy ---------------------------------- */

export function CopyButton({
  value,
  label = "Copied",
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [done, setDone] = React.useState(false);
  return (
    <button
      type="button"
      aria-label="Copy"
      onClick={(e) => {
        e.stopPropagation();
        void navigator.clipboard?.writeText(value);
        setDone(true);
        toast.success(label);
        window.setTimeout(() => setDone(false), 1200);
      }}
      className={cn(
        "shrink-0 rounded p-0.5 text-sub opacity-0 transition group-hover:opacity-100 hover:bg-secondary hover:text-foreground focus:opacity-100",
        className,
      )}
    >
      {done ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </button>
  );
}

/* ---------------------------- middle truncation --------------------------- */

/** identifiers render as the tail only: last two segments of an ARN / path */
export function MonoId({ value, tail = 2 }: { value: string; head?: number; tail?: number }) {
  const parts = value.split(/(?=[:/])/g);
  const short = parts.length > tail ? parts.slice(-tail).join("").replace(/^[:/]/, "") : value;
  return (
    <span className="mono truncate" title={value}>
      {short}
    </span>
  );
}

/* ------------------------------ service icon ------------------------------ */

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  ec2: Server,
  s3: Boxes,
  rds: Database,
  lambda: Zap,
  iam: Users,
  vpc: Network,
  elb: Scale,
  eks: Layers,
  cloudwatch: FileText,
  kms: Key,
};

const TYPE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "ec2.volume": HardDrive,
  "ec2.security_group": ShieldHalf,
  "ec2.elastic_ip": Route,
  "ec2.snapshot": HardDrive,
  "iam.role": KeyRound,
  "vpc.subnet": Network,
  "s3.bucket": Boxes,
};

export function ServiceIcon({ type, className }: { type: string; className?: string }) {
  const Icon = TYPE_ICONS[type] ?? ICONS[type.split(".")[0] ?? ""] ?? Globe;
  return <Icon className={cn("size-4 text-muted-foreground", className)} />;
}

/* ------------------------------- entity cell ------------------------------ */

export function EntityCell({
  name,
  id,
  type,
  onClick,
  head,
  tail,
}: {
  name: string;
  id: string;
  type: string;
  onClick?: () => void;
  head?: number;
  tail?: number;
}) {
  return (
    <div className="group flex min-w-0 items-center gap-2.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised">
        <ServiceIcon type={type} />
      </span>
      <span className="min-w-0">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClick?.();
          }}
          className="block max-w-[240px] truncate text-left text-[12px] font-medium text-foreground transition-colors duration-100 hover:text-primary"
        >
          {name}
        </button>
        <span className="flex items-center gap-1">
          <MonoId
            value={id}
            {...(head !== undefined ? { head } : {})}
            {...(tail !== undefined ? { tail } : {})}
          />
          <CopyButton value={id} label="Resource id copied" />
        </span>
      </span>
    </div>
  );
}

/* --------------------------------- links ---------------------------------- */

export function LinkText({
  children,
  onClick,
  mono,
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  mono?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      className={cn(
        "text-left text-primary transition-colors duration-100 hover:underline",
        mono ? "mono !text-primary" : "text-[12px] font-medium",
        className,
      )}
    >
      {children}
    </button>
  );
}

/* ------------------------------ numbers / time ---------------------------- */

export function Num({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("num block", className)}>{children}</span>;
}

const recencyColor = (minutes: number) => {
  if (minutes <= 60 * 24) return "var(--age-1d)";
  if (minutes <= 60 * 24 * 7) return "var(--age-7d)";
  if (minutes <= 60 * 24 * 30) return "var(--age-30d)";
  return "var(--age-old)";
};

export function RelTimeCell({ minutes }: { minutes: number }) {
  return (
    <span className="block whitespace-nowrap leading-tight" title={absTime(minutes)}>
      <span
        className="block text-[11px] font-semibold tnum"
        style={{ color: recencyColor(minutes) }}
      >
        {relTime(minutes)}
      </span>
      <span className="block whitespace-nowrap text-[11px] text-sub tnum">
        {absTime(minutes).slice(0, 16)}
      </span>
    </span>
  );
}

/* ------------------------------ severity bits ----------------------------- */

export const severityCompare = (a: Severity, b: Severity) => SEVERITY_RANK[a] - SEVERITY_RANK[b];

export function SeverityChips({
  counts,
}: {
  counts: { critical: number; high: number; medium: number; low: number };
}) {
  const entries: [Severity, number][] = [
    ["critical", counts.critical],
    ["high", counts.high],
    ["medium", counts.medium],
    ["low", counts.low],
  ];
  const active = entries.filter(([, n]) => n > 0);
  if (!active.length) return <EmDash />;
  return (
    <span className="flex flex-wrap items-center gap-2.5">
      {active.map(([sev, n]) => (
        <span
          key={sev}
          title={`${n} ${severityLabelOf(sev).toLowerCase()}`}
          className="flex items-center gap-1 text-[12px] font-medium text-foreground tnum"
        >
          <SeverityDot severity={sev} />
          {n}
        </span>
      ))}
    </span>
  );
}

export function DeltaBadge({ value, invert }: { value: number; invert?: boolean }) {
  if (!value) return <EmDash />;
  const up = value > 0;
  const good = invert ? !up : up;
  return (
    <span
      className={cn(
        "ml-1.5 text-xs font-medium tnum",
        good ? "text-tint-emerald-fg" : "text-tint-orange-fg",
      )}
    >
      {up ? "↑" : "↓"}
      {Math.abs(value)}
    </span>
  );
}

/* --------------------------------- badges --------------------------------- */

const tierLabel: Record<ActionTier, string> = {
  notify: "Notify",
  mark: "Mark",
  tag: "Tag",
  remediate: "Remediate",
  destroy: "Destroy",
};

export function ActionTierBadge({ tier }: { tier: ActionTier }) {
  return <Badge tone={tier === "destroy" ? "red" : "slate"}>{tierLabel[tier] ?? tier}</Badge>;
}

export function AutomatableIcon({ value }: { value: boolean }) {
  return value ? (
    <Check className="size-4 text-tint-emerald-fg" aria-label="automatable" />
  ) : (
    <EmDash />
  );
}

export function ExposureBadge({ value }: { value?: string }) {
  if (!value) return <EmDash />;
  return <Badge tone="red">{value}</Badge>;
}

export function GlobalPill() {
  return <Badge>Global</Badge>;
}

export function ConfidenceBadge({ value }: { value: string }) {
  return <Badge>{value.charAt(0).toUpperCase() + value.slice(1)}</Badge>;
}

export function TagChips({ tags }: { tags: Record<string, string> }) {
  const entries = Object.entries(tags);
  if (!entries.length) return <EmDash />;
  const shown = entries.slice(0, 2);
  const rest = entries.length - shown.length;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map(([k, v]) => (
        <Badge key={k} title={`${k}=${v}`}>
          {k}: {v.length > 12 ? `${v.slice(0, 12)}…` : v}
        </Badge>
      ))}
      {rest > 0 ? <span className="text-xs text-muted-foreground">+{rest}</span> : null}
    </span>
  );
}

export function ThresholdChips({ items }: { items: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((t) => (
        <Badge key={t}>{t}</Badge>
      ))}
    </span>
  );
}

export function FixIcon({ has }: { has: boolean }) {
  return has ? (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">
            <Wrench className="size-4 text-primary" />
          </span>
        </TooltipTrigger>
        <TooltipContent>AI fix prompt available</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  ) : (
    <EmDash />
  );
}

/* ------------------------------ AI fix card ------------------------------- */

export function AiFixCard({ prompt }: { prompt: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="card-title flex items-center gap-2">
          <Sparkles className="size-4 text-primary" /> AI fix prompt
        </span>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            void navigator.clipboard?.writeText(prompt);
            setCopied(true);
            toast.success("Fix prompt copied");
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="mono max-h-72 overflow-auto whitespace-pre-wrap px-3 py-2.5 leading-relaxed">
        {prompt}
      </pre>
      <p className="border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
        {AI_FIX_CAPTION}
      </p>
    </div>
  );
}

/* ----------------------------- panel building ----------------------------- */

export function PanelSection({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="card-title">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

export function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="panel divide-y divide-divider overflow-hidden">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[128px_1fr] items-start gap-3 px-3 py-2">
          <dt className="text-xs font-medium text-sub">{k}</dt>
          <dd className="min-w-0 break-words text-right text-[12px] font-medium text-foreground">
            {v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  return (
    <div className="panel relative overflow-hidden">
      <div className="absolute right-1.5 top-1.5">
        <CopyButton value={text} label="JSON copied" className="opacity-100" />
      </div>
      <pre className="mono max-h-80 overflow-auto whitespace-pre-wrap px-3 py-2.5">{text}</pre>
    </div>
  );
}

export function DiffTable({ diff }: { diff: { field: string; before: string; after: string }[] }) {
  if (!diff.length)
    return <p className="text-[13px] text-muted-foreground">No field-level changes recorded.</p>;
  return (
    <div className="panel overflow-hidden">
      <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 border-b border-border px-2.5 py-2">
        <span className="label-caps">Field</span>
        <span className="label-caps">Before</span>
        <span className="label-caps">After</span>
      </div>
      {diff.map((d) => (
        <div
          key={d.field}
          className="grid grid-cols-[1fr_1fr_1fr] gap-2 border-b border-divider px-2.5 py-2 last:border-0"
        >
          <span className="mono">{d.field}</span>
          <span className="mono rounded-[4px] bg-tint-red px-1 !text-tint-red-fg">
            − {d.before}
          </span>
          <span className="mono rounded-[4px] bg-tint-emerald px-1 !text-tint-emerald-fg">
            + {d.after}
          </span>
        </div>
      ))}
    </div>
  );
}

export const typeLabel = resourceLabel;
