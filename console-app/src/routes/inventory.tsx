import { Boxes } from "lucide-react";
import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Chip, Mono, LayerBadge, ProviderBadge } from "@/components/console/primitives";
import { DataTable, type Column, type Facet } from "@/components/console/data-table";
import {
  EntityCell,
  FixIcon,
  GlobalPill,
  LinkText,
  Num,
  RelTimeCell,
  SeverityChips,
  TagChips,
} from "@/components/console/cells";
import { useConsolePanels } from "@/components/console/panels";
import { ASSET_ROWS, SEVERITY_RANK, TENANT, type AssetRow } from "@/lib/console-data";
import { money } from "@/lib/mock-data";

export const Route = createFileRoute("/inventory")({
  head: () => ({
    meta: [
      { title: "Inventory — Cloud Estate Console" },
      {
        name: "description",
        content:
          "Explore every discovered cloud asset with provider, account, region, layer placement, open findings, monthly cost and tags.",
      },
      { property: "og:title", content: "Inventory — Cloud Estate Console" },
      {
        property: "og:description",
        content: "Faceted asset explorer across accounts, regions, providers and resource types.",
      },
    ],
  }),
  component: Inventory,
});

function Inventory() {
  const { openAsset } = useConsolePanels();

  const columns: Column<AssetRow>[] = [
    {
      key: "resource",
      header: "Resource",
      width: "300px",
      cell: (r) => (
        <EntityCell
          name={r.name}
          id={r.resource_uid}
          type={r.resource_type}
          onClick={() => openAsset(r.resource_uid)}
        />
      ),
      sort: (a, b) => a.name.localeCompare(b.name),
      csv: (r) => `${r.name} ${r.resource_uid}`,
    },
    {
      key: "type",
      header: "Resource type",
      cell: (r) => <span className="text-xs text-muted-foreground">{r.type_display}</span>,
      sort: (a, b) => a.resource_type.localeCompare(b.resource_type),
      csv: (r) => r.type_display,
    },
    {
      key: "provider",
      header: "Provider",
      cell: (r) => <ProviderBadge provider={r.provider} />,
      sort: (a, b) => a.provider.localeCompare(b.provider),
      csv: (r) => r.provider,
    },
    {
      key: "account",
      header: "Account",
      cell: (r) => <Mono className="text-muted-foreground">{r.account_id}</Mono>,
      sort: (a, b) => a.account_id.localeCompare(b.account_id),
      csv: (r) => r.account_id,
    },
    {
      key: "region",
      header: "Region",
      cell: (r) =>
        r.topology.layer_id === "G0" ? (
          <GlobalPill />
        ) : (
          <Mono className="text-muted-foreground">{r.region}</Mono>
        ),
      sort: (a, b) => a.region.localeCompare(b.region),
      csv: (r) => (r.topology.layer_id === "G0" ? "global" : r.region),
    },
    {
      key: "placement",
      header: "Placement",
      cell: (r) => (
        <span className="flex items-center gap-1.5">
          <LayerBadge layerId={r.topology.layer_id} layerName={r.topology.layer_name} />
          <Mono className="text-muted-foreground">{r.topology.container}</Mono>
        </span>
      ),
      sort: (a, b) => a.topology.layer_id.localeCompare(b.topology.layer_id),
      csv: (r) => `${r.topology.layer_id} ${r.topology.container}`,
    },
    {
      key: "findings",
      header: "Findings",
      cell: (r) => <SeverityChips counts={r.findings} />,
      sort: (a, b) =>
        b.findings.critical * 1000 +
        b.findings.high * 100 +
        b.findings.medium * 10 +
        b.findings.low -
        (a.findings.critical * 1000 +
          a.findings.high * 100 +
          a.findings.medium * 10 +
          a.findings.low),
      csv: (r) => r.findings.total,
    },
    {
      key: "cost",
      header: "Cost /mo",
      align: "right",
      cell: (r) => (
        <Num className={r.cost_monthly === null ? "text-sub" : ""}>
          {r.cost_monthly === null ? "—" : money(r.cost_monthly)}
        </Num>
      ),
      sort: (a, b) => (b.cost_monthly ?? -1) - (a.cost_monthly ?? -1),
      csv: (r) => r.cost_monthly ?? "",
    },
    {
      key: "tags",
      header: "Tags",
      cell: (r) => <TagChips tags={r.tags} />,
      csv: (r) =>
        Object.entries(r.tags)
          .map(([k, v]) => `${k}=${v}`)
          .join(" "),
    },
    {
      key: "last_seen",
      header: "Last seen",
      cell: (r) => <RelTimeCell minutes={r.last_seen} />,
      sort: (a, b) => a.last_seen - b.last_seen,
      csv: (r) => r.last_seen,
    },
    /* audit columns */
    {
      key: "tenant",
      header: "Tenant",
      audit: true,
      cell: () => <Mono>{TENANT}</Mono>,
      csv: () => TENANT,
    },
    {
      key: "audit_provider",
      header: "Provider (audit)",
      audit: true,
      cell: (r) => <Mono>{r.provider}</Mono>,
      csv: (r) => r.provider,
    },
    {
      key: "audit_account",
      header: "Account (audit)",
      audit: true,
      cell: (r) => <Mono>{r.account_id}</Mono>,
      csv: (r) => r.account_id,
    },
    {
      key: "scan",
      header: "Scan ID",
      audit: true,
      cell: (r) => <ScanLink scanId={r.scan_id} />,
      csv: (r) => r.scan_id,
    },
    {
      key: "first_seen",
      header: "First seen",
      audit: true,
      cell: (r) => <RelTimeCell minutes={r.first_seen} />,
      sort: (a, b) => a.first_seen - b.first_seen,
      csv: (r) => r.first_seen,
    },
    {
      key: "audit_last_seen",
      header: "Last seen (audit)",
      audit: true,
      cell: (r) => <RelTimeCell minutes={r.last_seen} />,
      csv: (r) => r.last_seen,
    },
    {
      key: "fix",
      header: "Fix",
      audit: true,
      cell: (r) => <FixIcon has={r.findings.total > 0} />,
      csv: (r) => (r.findings.total > 0 ? "available" : ""),
    },
  ];

  const facets: Facet<AssetRow>[] = [
    { key: "provider", label: "Provider", get: (r) => r.provider },
    { key: "account", label: "Account", get: (r) => r.account_id },
    { key: "region", label: "Region", get: (r) => r.region },
    { key: "type", label: "Resource type", get: (r) => r.resource_type },
    { key: "layer", label: "Layer", get: (r) => r.topology.layer_id },
    {
      key: "hasFindings",
      label: "Findings",
      options: ["with findings", "clean"],
      get: (r) => (r.findings.total ? "with findings" : "clean"),
    },
  ];

  const withFindings = ASSET_ROWS.filter((a) => a.findings.total > 0).length;

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col p-6">
      <PageHeader
        icon={Boxes}
        title="Inventory"
        subtitle="Every asset discovered by the pipeline, deduplicated by resource UID."
        meta={
          <>
            <Chip>
              <Mono>{ASSET_ROWS.length}</Mono> assets
            </Chip>
            <Chip>
              <Mono>{withFindings}</Mono> with open findings
            </Chip>
            <Chip>
              tenant <Mono>{TENANT}</Mono>
            </Chip>
          </>
        }
      />
      <DataTable
        rows={ASSET_ROWS}
        columns={columns}
        rowKey={(r) => r.resource_uid}
        facets={facets}
        defaultSort={{ key: "findings", dir: "asc" }}
        onRowClick={(r) => openAsset(r.resource_uid)}
        search={(r) => `${r.name} ${r.resource_uid} ${r.resource_type} ${r.account_id} ${r.region}`}
        searchPlaceholder="Search name, ARN, type…"
        csvName="cloud-estate-inventory"
      />
    </div>
  );
}

function ScanLink({ scanId }: { scanId: string }) {
  const { openRun } = useConsolePanels();
  return (
    <LinkText mono onClick={() => openRun(scanId)}>
      {scanId}
    </LinkText>
  );
}
