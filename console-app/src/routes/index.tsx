import { createFileRoute } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { ArrowUpRight, RefreshCw, LayoutDashboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Chip,
  Mono,
  PageHeader,
  SectionTitle,
  SeverityBadge,
  SeverityDot,
  DomainBadge,
  CategoryBadge,
} from "@/components/console/primitives";
import {
  ACCOUNT_COUNT,
  NETWORK_COUNT,
  PIPELINE_STAGES,
  REGION_COUNT,
  TOTAL_ASSETS,
} from "@/lib/mock-data";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Estate Overview — Cloud Estate Console" },
      {
        name: "description",
        content:
          "Pipeline freshness, critical findings, drift events and monthly savings opportunity across your entire multi-cloud estate.",
      },
      { property: "og:title", content: "Estate Overview — Cloud Estate Console" },
      {
        property: "og:description",
        content: "Pipeline freshness, findings by domain and top cloud savings opportunities.",
      },
    ],
  }),
  component: Overview,
});

function StageCard({ s, i }: { s: (typeof PIPELINE_STAGES)[number]; i: number }) {
  return (
    <div className="panel flex items-start gap-3 p-4">
      <span className="card-title font-normal leading-none text-border-strong tnum">{i + 1}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium text-foreground">{s.label}</div>
        <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className={cn("size-1.5 rounded-full", s.fresh ? "bg-fresh" : "bg-stale")} />
          <span>
            {s.fresh ? "Fresh" : "Stale"} · {s.last_run}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground tnum">
          {s.records.toLocaleString()} records
        </div>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="panel p-4">
      <div className="label-caps">{label}</div>
      <div className="mt-2 kpi-value font-semibold text-foreground tnum">{value}</div>
      {sub ? <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

function Overview() {
  return (
    <div className="pb-10">
      <PageHeader
        icon={LayoutDashboard}
        title="Estate Overview"
        subtitle="What was discovered, and how it is shaped."
        meta={
          <>
            <Chip>
              <span className="size-1.5 rounded-full bg-fresh" /> Last full run 12m ago
            </Chip>
            <Chip>
              <Mono>run_01JQ8F3K2A</Mono>
            </Chip>
          </>
        }
        actions={
          <Button size="sm" className="h-8 text-[13px]">
            <RefreshCw className="size-4" /> Run pipeline
          </Button>
        }
      />

      <div className="space-y-6">
        <section>
          <SectionTitle className="mb-2.5">Pipeline status</SectionTitle>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {PIPELINE_STAGES.map((s, i) => (
              <StageCard key={s.key} s={s} i={i} />
            ))}
          </div>
        </section>

        {/* The estate, not a scoreboard. Compliance and cost moved to their own
            platform; what an architecture tool owes its reader on the way in is
            how big the thing is and how it is shaped. */}
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            label="Total assets"
            value={TOTAL_ASSETS.toLocaleString()}
            sub="discovered this scan"
          />
          <Kpi label="Accounts" value={ACCOUNT_COUNT} sub="in this tenant" />
          <Kpi label="Regions" value={REGION_COUNT} sub="with at least one resource" />
          <Kpi label="Networks" value={NETWORK_COUNT} sub="VPCs across all regions" />
        </section>
      </div>
    </div>
  );
}
