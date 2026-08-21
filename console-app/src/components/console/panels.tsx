import * as React from "react";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  CircleSlash,
  Clock,
  ExternalLink,
  Play,
  Tag as TagIcon,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Chip,
  DomainBadge,
  Mono,
  ProviderBadge,
  SeverityBadge,
} from "@/components/console/primitives";
import {
  ActionTierBadge,
  AiFixCard,
  ConfidenceBadge,
  CopyButton,
  DiffTable,
  ExposureBadge,
  JsonBlock,
  KV,
  LinkText,
  MonoId,
  PanelSection,
  RelTimeCell,
  ServiceIcon,
  SeverityChips,
} from "@/components/console/cells";
import {
  ASSET_ROWS,
  DRIFT_ROWS,
  FINDING_ROWS,
  POLICY_ROWS,
  REC_ROWS,
  RUN_ROWS,
  absTime,
  findingFixPrompt,
  findingsForUid,
  policyFixTemplate,
  policyMeta,
  policyYaml,
  recFixPrompt,
  recsForUid,
  relTime,
  resourceLabel,
  savingsRange,
  type AssetRow,
  type DriftRow,
  type FindingRow,
  type PolicyRow,
  type RecRow,
  type RunRow,
} from "@/lib/console-data";
import { LAYERS, money } from "@/lib/mock-data";

/* ------------------------------- panel host ------------------------------- */

type PanelState =
  | { kind: "asset"; id: string }
  | { kind: "finding"; id: string }
  | { kind: "rec"; id: string }
  | { kind: "policy"; id: string }
  | { kind: "run"; id: string }
  | { kind: "drift"; id: string }
  | null;

interface PanelApi {
  openAsset: (uid: string) => void;
  openFinding: (id: string) => void;
  openRec: (id: string) => void;
  openPolicy: (id: string) => void;
  openRun: (idOrScan: string) => void;
  openDrift: (id: string) => void;
  close: () => void;
}

const PanelContext = React.createContext<PanelApi | null>(null);

export function useConsolePanels(): PanelApi {
  const ctx = React.useContext(PanelContext);
  return (
    ctx ?? {
      openAsset: () => {},
      openFinding: () => {},
      openRec: () => {},
      openPolicy: () => {},
      openRun: () => {},
      openDrift: () => {},
      close: () => {},
    }
  );
}

export function PanelProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<PanelState>(null);
  const api = React.useMemo<PanelApi>(
    () => ({
      openAsset: (id) => setState({ kind: "asset", id }),
      openFinding: (id) => setState({ kind: "finding", id }),
      openRec: (id) => setState({ kind: "rec", id }),
      openPolicy: (id) => setState({ kind: "policy", id }),
      openRun: (id) => setState({ kind: "run", id }),
      openDrift: (id) => setState({ kind: "drift", id }),
      close: () => setState(null),
    }),
    [],
  );

  return (
    <PanelContext.Provider value={api}>
      {children}
      <Sheet open={!!state} onOpenChange={(o) => !o && setState(null)}>
        <SheetContent
          side="right"
          className="flex w-full flex-col gap-0 border-l border-border p-0 shadow-drawer duration-200 sm:max-w-[640px]"
        >
          <SheetTitle className="sr-only">Detail panel</SheetTitle>
          {state ? <PanelRouter state={state} /> : null}
        </SheetContent>
      </Sheet>
    </PanelContext.Provider>
  );
}

function PanelRouter({ state }: { state: NonNullable<PanelState> }) {
  switch (state.kind) {
    case "asset": {
      const row = ASSET_ROWS.find((a) => a.resource_uid === state.id || a.resource_id === state.id);
      return row ? <AssetPanel row={row} /> : <Missing what="asset" />;
    }
    case "finding": {
      const row = FINDING_ROWS.find((f) => f.id === state.id);
      return row ? <FindingPanel row={row} /> : <Missing what="finding" />;
    }
    case "rec": {
      const row = REC_ROWS.find((r) => r.id === state.id);
      return row ? <RecommendationPanel row={row} /> : <Missing what="recommendation" />;
    }
    case "policy": {
      const row = POLICY_ROWS.find((p) => p.policy === state.id);
      return row ? <PolicyPanel row={row} /> : <Missing what="policy" />;
    }
    case "run": {
      const row = RUN_ROWS.find((r) => r.run_id === state.id || r.scan_id === state.id);
      return row ? <RunPanel row={row} /> : <Missing what="run" />;
    }
    case "drift": {
      const row = DRIFT_ROWS.find((d) => d.id === state.id);
      return row ? <DriftPanel row={row} /> : <Missing what="change" />;
    }
  }
}

function Missing({ what }: { what: string }) {
  return (
    <div className="p-6">
      <div className="dashed-box">This {what} is not in the current scan snapshot.</div>
    </div>
  );
}

/* ------------------------------ panel chrome ------------------------------ */

function EntityHeader({
  name,
  id,
  type,
  chips,
  badges,
}: {
  name: string;
  id: string;
  type: string;
  chips?: React.ReactNode;
  badges?: React.ReactNode;
}) {
  return (
    <header className="border-b border-border bg-surface px-5 py-4 pr-12">
      <div className="group flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised">
          <ServiceIcon type={type} className="size-4.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="card-title truncate">{name}</h2>
          <div className="mt-0.5 flex items-center gap-1">
            <MonoId value={id} head={26} tail={20} />
            <CopyButton value={id} label="Copied" className="opacity-100" />
          </div>
        </div>
        {badges ? <div className="flex shrink-0 items-center gap-1.5">{badges}</div> : null}
      </div>
      {chips ? <div className="mt-3 flex flex-wrap items-center gap-1.5">{chips}</div> : null}
    </header>
  );
}

function PanelFooter({
  scanId,
  firstSeen,
  lastSeen,
}: {
  scanId: string;
  firstSeen: number;
  lastSeen: number;
}) {
  const { openRun } = useConsolePanels();
  return (
    <footer className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border bg-surface px-5 py-2.5 text-xs text-muted-foreground">
      <LinkText mono onClick={() => openRun(scanId)}>
        {scanId}
      </LinkText>
      <span>·</span>
      <span title={absTime(firstSeen)}>First seen {relTime(firstSeen)}</span>
      <span>·</span>
      <span title={absTime(lastSeen)}>Last seen {relTime(lastSeen)}</span>
    </footer>
  );
}

function PanelBody({ children }: { children: React.ReactNode }) {
  return <div className="min-h-0 flex-1 space-y-5 overflow-auto px-5 py-4">{children}</div>;
}

function PanelTabs({
  tabs,
}: {
  tabs: { value: string; label: string; content: React.ReactNode }[];
}) {
  return (
    <Tabs defaultValue={tabs[0]!.value} className="flex min-h-0 flex-1 flex-col gap-0">
      <TabsList className="h-auto w-full justify-start gap-4 rounded-none border-b border-border bg-surface px-5 py-0">
        {tabs.map((t) => (
          <TabsTrigger
            key={t.value}
            value={t.value}
            className="-mb-px rounded-none border-b-2 border-transparent bg-transparent px-0 py-2.5 text-[13px] font-medium text-muted-foreground shadow-none transition-colors duration-200 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((t) => (
        <TabsContent key={t.value} value={t.value} className="mt-0 min-h-0 flex-1 overflow-hidden">
          <PanelBody>{t.content}</PanelBody>
        </TabsContent>
      ))}
    </Tabs>
  );
}

function MiniFindings({ rows }: { rows: FindingRow[] }) {
  const { openFinding } = useConsolePanels();
  if (!rows.length) return <p className="text-[13px] text-muted-foreground">No open findings.</p>;
  return (
    <div className="panel divide-y divide-divider overflow-hidden">
      {rows.map((f) => (
        <button
          key={f.id}
          onClick={() => openFinding(f.id)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-row-hover"
        >
          <SeverityBadge severity={f.severity} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{f.title}</span>
            <Mono>{f.policy}</Mono>
          </span>
          <DomainBadge domain={f.domain} />
        </button>
      ))}
    </div>
  );
}

/* ------------------------------- asset panel ------------------------------ */

export function AssetPanel({ row }: { row: AssetRow }) {
  const { openRec, openDrift } = useConsolePanels();
  const findings = findingsForUid(row.resource_uid);
  const recs = recsForUid(row.resource_uid);
  const savings = recs.reduce(
    (acc, r) => ({
      min: acc.min + r.estimated_monthly_savings_usd.min,
      max: acc.max + r.estimated_monthly_savings_usd.max,
    }),
    { min: 0, max: 0 },
  );
  const drift = DRIFT_ROWS.filter((d) => d.resource_uid === row.resource_uid);
  const layer = LAYERS.find((l) => l.id === row.topology.layer_id);

  return (
    <>
      <EntityHeader
        name={row.name}
        id={row.resource_uid}
        type={row.resource_type}
        badges={<SeverityChips counts={row.findings} />}
        chips={
          <>
            <ProviderBadge provider={row.provider} />
            <Chip>
              <Mono>{row.account_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.region}</Mono>
            </Chip>
            <Chip>{resourceLabel(row.resource_type)}</Chip>
          </>
        }
      />
      <PanelTabs
        tabs={[
          {
            value: "overview",
            label: "Overview",
            content: (
              <>
                <PanelSection title="Metadata">
                  <KV
                    rows={[
                      ["Resource type", <Mono key="t">{row.resource_type}</Mono>],
                      ["Resource id", <Mono key="i">{row.resource_id}</Mono>],
                      ["Provider", row.provider],
                      ["Account", <Mono key="a">{row.account_id}</Mono>],
                      ["Region", <Mono key="r">{row.region}</Mono>],
                      ["Zone", <Mono key="z">{row.topology.zone}</Mono>],
                      ["UID quality", row.topology.uid_quality],
                    ]}
                  />
                </PanelSection>
                <PanelSection title="Tags">
                  {Object.keys(row.tags).length ? (
                    <KV
                      rows={Object.entries(row.tags).map(([k, v]) => [k, <Mono key={k}>{v}</Mono>])}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">No tags on this resource.</p>
                  )}
                </PanelSection>
                <PanelSection title="Cost">
                  <KV
                    rows={[
                      [
                        "Monthly cost",
                        row.cost_monthly === null ? "— unpriced" : money(row.cost_monthly),
                      ],
                      [
                        "Savings opportunity",
                        savings.max ? (
                          <span className="text-tint-emerald-fg">
                            {savingsRange(savings.min, savings.max)}
                          </span>
                        ) : (
                          "none identified"
                        ),
                      ],
                    ]}
                  />
                </PanelSection>
              </>
            ),
          },
          {
            value: "compliance",
            label: `Compliance (${findings.length})`,
            content: (
              <PanelSection title="Findings on this resource">
                <MiniFindings rows={findings} />
              </PanelSection>
            ),
          },
          {
            value: "cost",
            label: `Cost (${recs.length})`,
            content: (
              <>
                <PanelSection title="Total savings">
                  <div className="panel px-3 py-2.5">
                    <p className="card-title font-semibold text-tint-emerald-fg tnum">
                      {savings.max ? savingsRange(savings.min, savings.max) : "—"}
                    </p>
                    <p className="text-xs text-muted-foreground">estimated per month</p>
                  </div>
                </PanelSection>
                <PanelSection title="Recommendations">
                  {recs.length ? (
                    <div className="panel divide-y divide-divider overflow-hidden">
                      {recs.map((r) => (
                        <button
                          key={r.id}
                          onClick={() => openRec(r.id)}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-row-hover"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium">{r.title}</span>
                            <Mono className="text-muted-foreground">{r.rule_id}</Mono>
                          </span>
                          <span className="text-tint-emerald-fg tnum text-[13px]">
                            {savingsRange(
                              r.estimated_monthly_savings_usd.min,
                              r.estimated_monthly_savings_usd.max,
                            )}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">No cost recommendations.</p>
                  )}
                </PanelSection>
              </>
            ),
          },
          {
            value: "architecture",
            label: "Architecture",
            content: (
              <>
                <PanelSection title="Layer placement">
                  <KV
                    rows={[
                      [
                        "Layer",
                        <span key="l" className="mono">
                          {row.topology.layer_id} · {layer?.name}
                        </span>,
                      ],
                      ["Container", <Mono key="c">{row.topology.container}</Mono>],
                    ]}
                  />
                </PanelSection>
                <PanelSection title="Container chain">
                  <div className="panel flex flex-wrap items-center gap-1.5 px-3 py-2.5">
                    {[
                      row.account_id,
                      row.region,
                      row.topology.container,
                      row.topology.zone,
                      row.topology.layer_id === "G0" ? "global" : "subnet",
                    ].map((seg, i, arr) => (
                      <React.Fragment key={`${seg}-${i}`}>
                        <Mono>{seg}</Mono>
                        {i < arr.length - 1 ? (
                          <ArrowRight className="size-3 text-muted-foreground" />
                        ) : null}
                      </React.Fragment>
                    ))}
                  </div>
                </PanelSection>
                <PanelSection title="Relationships">
                  <div className="panel divide-y divide-divider overflow-hidden">
                    {[
                      ["contained_in", row.topology.container],
                      ["scoped_to", row.region],
                      ["owned_by", row.tags["Owner"] ?? "unassigned"],
                    ].map(([rel, target]) => (
                      <div key={rel} className="flex items-center gap-2 px-3 py-1.5">
                        <span className="text-xs text-muted-foreground">{rel}</span>
                        <ArrowRight className="size-3 text-muted-foreground" />
                        <Mono>{target}</Mono>
                      </div>
                    ))}
                  </div>
                </PanelSection>
                <Button asChild size="sm" variant="secondary">
                  <Link to="/architecture">
                    <ExternalLink className="size-3.5" /> View in diagram
                  </Link>
                </Button>
              </>
            ),
          },
          {
            value: "drift",
            label: `Drift (${drift.length})`,
            content: (
              <PanelSection title="Change timeline">
                {drift.length ? (
                  <ol className="space-y-2">
                    {drift.map((d) => (
                      <li key={d.id}>
                        <button
                          onClick={() => openDrift(d.id)}
                          className="panel flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-row-hover"
                        >
                          <ChangeBadge row={d} />
                          <span className="min-w-0 flex-1 truncate text-xs">{d.what}</span>
                          <RelTimeCell minutes={d.detected} />
                        </button>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No changes observed for this resource.
                  </p>
                )}
              </PanelSection>
            ),
          },
          {
            value: "raw",
            label: "Raw",
            content: <JsonBlock value={row} />,
          },
        ]}
      />
      <PanelFooter scanId={row.scan_id} firstSeen={row.first_seen} lastSeen={row.last_seen} />
    </>
  );
}

/* ------------------------------ finding panel ----------------------------- */

function ConfirmAction({
  label,
  destructive,
  description,
}: {
  label: string;
  destructive?: boolean;
  description: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [stage, setStage] = React.useState(0);
  return (
    <>
      <Button
        size="sm"
        variant={destructive ? "destructive" : "secondary"}
        onClick={() => {
          setStage(0);
          setOpen(true);
        }}
      >
        {destructive ? <Trash2 className="size-3.5" /> : <TagIcon className="size-3.5" />}
        {label}
        {destructive ? (
          <span className="mono ml-1 rounded-[4px] bg-destructive-foreground/20 px-1 !text-current">
            LIVE
          </span>
        ) : null}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              {destructive ? <AlertTriangle className="size-4 text-destructive" /> : null}
              {stage === 0 ? label : "Confirm again — this is LIVE"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {stage === 0
                ? description
                : "This action executes against the live cloud account and cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            {destructive && stage === 0 ? (
              <Button variant="destructive" onClick={() => setStage(1)}>
                Continue
              </Button>
            ) : (
              <AlertDialogAction
                onClick={() => {
                  toast.success(`${label} queued`);
                  setOpen(false);
                }}
              >
                {destructive ? "Execute LIVE" : "Confirm"}
              </AlertDialogAction>
            )}
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export function FindingPanel({ row }: { row: FindingRow }) {
  const { openAsset, openPolicy, openRun } = useConsolePanels();
  return (
    <>
      <EntityHeader
        name={row.title}
        id={row.arn}
        type={row.resource_type}
        badges={<SeverityBadge severity={row.severity} />}
        chips={
          <>
            <DomainBadge domain={row.domain} />
            <ActionTierBadge tier={row.action_tier} />
            <ProviderBadge provider={row.provider} />
            <Chip onClick={() => openAsset(row.arn)}>
              <Mono>{row.resource_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.account_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.region}</Mono>
            </Chip>
            {row.exposure ? <ExposureBadge value={row.exposure} /> : null}
          </>
        }
      />
      <PanelTabs
        tabs={[
          {
            value: "overview",
            label: "Overview",
            content: (
              <>
                <PanelSection title="Finding">
                  <p className="text-[13px]">{row.description}</p>
                  <p className="text-xs text-muted-foreground">{row.rationale}</p>
                </PanelSection>
                <PanelSection title="Policy">
                  <KV
                    rows={[
                      [
                        "Policy id",
                        <LinkText key="p" mono onClick={() => openPolicy(row.policy)}>
                          {row.policy}
                        </LinkText>,
                      ],
                      ["Automatable", row.automatable],
                      ["Resource type", <Mono key="t">{row.resource_type}</Mono>],
                      [
                        "Scan",
                        <LinkText key="s" mono onClick={() => openRun(row.scan_id)}>
                          {row.scan_id}
                        </LinkText>,
                      ],
                    ]}
                  />
                </PanelSection>
                <PanelSection title="Evidence">
                  <JsonBlock value={row.evidence} />
                </PanelSection>
              </>
            ),
          },
          {
            value: "fix",
            label: "Fix",
            content: (
              <>
                <PanelSection title="Remediation steps">
                  <ol className="panel divide-y divide-divider overflow-hidden text-xs">
                    {[
                      `Locate the definition of ${row.resource_id} in your IaC repository.`,
                      row.remediation,
                      "Plan the change and review the diff with the resource owner.",
                      "Apply, then re-run the compliance stage to confirm the finding clears.",
                    ].map((s, i) => (
                      <li key={i} className="flex gap-2 px-3 py-2">
                        <span className="text-xs text-label tnum">{i + 1}.</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ol>
                </PanelSection>
                <AiFixCard prompt={findingFixPrompt(row)} />
              </>
            ),
          },
          {
            value: "actions",
            label: "Actions",
            content: (
              <>
                <PanelSection title="Non-destructive">
                  <div className="flex flex-wrap gap-2">
                    <ConfirmAction
                      label="Tag resource"
                      description={`Apply governance tags to ${row.resource_id}.`}
                    />
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => toast.success("Owner notified")}
                    >
                      <Bell className="size-3.5" /> Notify owner
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => toast.success("Finding marked as reviewed")}
                    >
                      <CheckCircle2 className="size-3.5" /> Mark reviewed
                    </Button>
                  </div>
                </PanelSection>
                <PanelSection title="Destructive">
                  <div className="flex flex-wrap gap-2">
                    <ConfirmAction
                      destructive
                      label="Remediate now"
                      description={`Execute: ${row.remediation}`}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Destructive actions require double confirmation and are labelled LIVE.
                  </p>
                </PanelSection>
              </>
            ),
          },
          {
            value: "history",
            label: "History",
            content: (
              <PanelSection title="Occurrences across scans">
                <div className="panel divide-y divide-divider overflow-hidden">
                  {row.occurrences.map((o) => (
                    <div key={o.scan_id} className="flex items-center gap-2 px-3 py-2">
                      <LinkText mono onClick={() => openRun(o.scan_id)}>
                        {o.scan_id}
                      </LinkText>
                      <span className="ml-auto text-xs capitalize text-muted-foreground">
                        {o.status}
                      </span>
                      <RelTimeCell minutes={o.at} />
                    </div>
                  ))}
                </div>
              </PanelSection>
            ),
          },
        ]}
      />
      <PanelFooter scanId={row.scan_id} firstSeen={row.first_seen} lastSeen={row.last_seen} />
    </>
  );
}

/* -------------------------- recommendation panel -------------------------- */

export function RecommendationPanel({ row }: { row: RecRow }) {
  const { openAsset } = useConsolePanels();
  return (
    <>
      <EntityHeader
        name={row.title}
        id={row.resource_uid}
        type={row.resource_type}
        badges={<ConfidenceBadge value={row.confidence} />}
        chips={
          <>
            <Chip onClick={() => openAsset(row.resource_uid)}>
              <Mono>{row.resource_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.rule_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.account_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.region}</Mono>
            </Chip>
          </>
        }
      />
      <PanelTabs
        tabs={[
          {
            value: "overview",
            label: "Overview",
            content: (
              <>
                <PanelSection title="Why this fired">
                  <p className="text-[13px]">{row.description}</p>
                </PanelSection>
                <PanelSection title="Evaluated conditions">
                  <div className="panel divide-y divide-divider overflow-hidden">
                    {row.evaluated.map((e) => (
                      <div key={e.metric} className="flex items-center gap-2 px-3 py-1.5">
                        <span className="mono flex-1">
                          {e.metric} <span className="text-primary">{e.actual}</span>{" "}
                          <span className="text-muted-foreground">{e.threshold}</span>
                        </span>
                        <CheckCircle2 className="size-4 text-tint-emerald-fg" />
                      </div>
                    ))}
                  </div>
                </PanelSection>
                <PanelSection title="Savings math">
                  <KV
                    rows={[
                      [
                        "Current monthly cost",
                        row.current_monthly_cost_usd
                          ? money(row.current_monthly_cost_usd)
                          : "— unpriced",
                      ],
                      ["Savings model", <Mono key="m">{row.savings_model}</Mono>],
                      ["Rule estimate", row.estimated_savings],
                      [
                        "Estimated savings",
                        <span key="s" className="text-tint-emerald-fg">
                          {savingsRange(
                            row.estimated_monthly_savings_usd.min,
                            row.estimated_monthly_savings_usd.max,
                          )}{" "}
                          / mo
                        </span>,
                      ],
                      ["Confidence", row.confidence],
                    ]}
                  />
                </PanelSection>
              </>
            ),
          },
          {
            value: "fix",
            label: "Fix",
            content: (
              <>
                <PanelSection title="Recommended change">
                  <p className="text-[13px]">{row.fix}</p>
                </PanelSection>
                <AiFixCard prompt={recFixPrompt(row)} />
              </>
            ),
          },
          {
            value: "history",
            label: "History",
            content: (
              <>
                <PanelSection title="Occurrences">
                  <div className="panel divide-y divide-divider overflow-hidden">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-2">
                        <Mono className="text-muted-foreground">{row.scan_id}</Mono>
                        <span className="ml-auto text-xs text-muted-foreground">Open</span>
                        <RelTimeCell minutes={row.detected + i * 240} />
                      </div>
                    ))}
                  </div>
                </PanelSection>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => toast.success("Recommendation dismissed for 30 days")}
                >
                  <CircleSlash className="size-3.5" /> Dismiss
                </Button>
              </>
            ),
          },
        ]}
      />
      <PanelFooter scanId={row.scan_id} firstSeen={row.first_seen} lastSeen={row.last_seen} />
    </>
  );
}

/* ------------------------------- policy panel ----------------------------- */

export function PolicyPanel({ row }: { row: PolicyRow }) {
  const meta = policyMeta(row.policy);
  return (
    <>
      <EntityHeader
        name={row.title}
        id={row.policy}
        type={row.resource_key}
        badges={<SeverityBadge severity={row.severity} />}
        chips={
          <>
            <DomainBadge domain={row.domain} />
            <ActionTierBadge tier={row.action_tier} />
            <Chip>
              <Mono>{row.resource_key}</Mono>
            </Chip>
            <Chip>{row.findings_count} findings</Chip>
          </>
        }
      />
      <PanelTabs
        tabs={[
          {
            value: "metadata",
            label: "Metadata",
            content: (
              <>
                <PanelSection title="Description">
                  <p className="text-[13px]">{meta.description}</p>
                </PanelSection>
                <PanelSection title="Rationale">
                  <p className="text-xs text-muted-foreground">{meta.rationale}</p>
                </PanelSection>
                <PanelSection title="References">
                  <div className="panel divide-y divide-divider overflow-hidden">
                    {meta.references.length ? (
                      meta.references.map((r) => (
                        <a
                          key={r.label}
                          href={r.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-2 px-3 py-1.5 text-xs text-primary hover:underline"
                        >
                          <ExternalLink className="size-3" /> {r.label}
                        </a>
                      ))
                    ) : (
                      <p className="px-3 py-1.5 text-xs text-muted-foreground">No references.</p>
                    )}
                  </div>
                </PanelSection>
              </>
            ),
          },
          {
            value: "definition",
            label: "Definition",
            content: (
              <div className="panel relative overflow-hidden">
                <div className="absolute right-1.5 top-1.5">
                  <CopyButton value={policyYaml(row)} label="YAML copied" className="opacity-100" />
                </div>
                <pre className="mono overflow-auto whitespace-pre px-3 py-2.5">
                  {policyYaml(row)}
                </pre>
              </div>
            ),
          },
          {
            value: "fix",
            label: "Fix template",
            content: <AiFixCard prompt={policyFixTemplate(row)} />,
          },
          {
            value: "run",
            label: "Run",
            content: (
              <>
                <PanelSection title="Scan launcher">
                  <KV
                    rows={[
                      ["Policies", <Mono key="p">{row.policy}</Mono>],
                      ["Resource scope", <Mono key="s">{row.resource_key}</Mono>],
                      ["Region", "all regions"],
                      ["Dry run", "on"],
                    ]}
                  />
                </PanelSection>
              </>
            ),
          },
        ]}
      />
      <footer className="border-t border-border bg-surface px-5 py-2.5 text-xs text-muted-foreground">
        Registry policy · {row.findings_count} open findings · graph check{" "}
        {row.graph_check ? "enabled" : "disabled"}
      </footer>
    </>
  );
}

/* --------------------------------- run panel ------------------------------ */

export function RunPanel({ row }: { row: RunRow }) {
  const prev = RUN_ROWS[RUN_ROWS.findIndex((r) => r.run_id === row.run_id) + 1];
  return (
    <>
      <EntityHeader
        name={`Pipeline run · ${row.status}`}
        id={row.run_id}
        type="cloudwatch.log_group"
        badges={
          <span
            className={cn(
              "flex items-center gap-1 text-[13px]",
              row.status === "success"
                ? "text-fresh"
                : row.status === "partial"
                  ? "text-stale"
                  : "text-tint-red-fg",
            )}
          >
            {row.status === "failed" ? (
              <CircleSlash className="size-3.5" />
            ) : (
              <CheckCircle2 className="size-3.5" />
            )}
            {row.status}
          </span>
        }
        chips={
          <>
            <Chip>
              <Mono>{row.scan_id}</Mono>
            </Chip>
            <Chip>
              <Clock className="size-3" /> {row.duration}
            </Chip>
            <Chip>{row.trigger}</Chip>
            {row.scope.map((s) => (
              <Chip key={s}>{s}</Chip>
            ))}
          </>
        }
      />
      <PanelTabs
        tabs={[
          {
            value: "stages",
            label: "Stages",
            content: (
              <PanelSection title="Pipeline stages">
                <div className="panel divide-y divide-divider overflow-hidden">
                  {row.stages.map((s) => (
                    <div key={s.key} className="flex items-center gap-3 px-3 py-2">
                      <span
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          s.status === "ok"
                            ? "bg-fresh"
                            : s.status === "failed"
                              ? "bg-sev-critical"
                              : "bg-border-strong",
                        )}
                      />
                      <span className="flex-1 text-xs font-medium">{s.label}</span>
                      <span className="text-xs text-muted-foreground tnum">{s.duration}</span>
                      <span className="w-16 text-right text-xs text-muted-foreground tnum">
                        {s.records || "—"}
                      </span>
                      <button
                        className="text-xs text-primary hover:underline"
                        onClick={() => toast.info(`Artifact ${row.scan_id}/${s.key}.json`)}
                      >
                        artifact
                      </button>
                    </div>
                  ))}
                </div>
              </PanelSection>
            ),
          },
          {
            value: "deltas",
            label: "Deltas",
            content: (
              <PanelSection title={`vs ${prev?.run_id ?? "previous run"}`}>
                <KV
                  rows={[
                    [
                      "Assets",
                      `${row.assets} (${row.assets_delta >= 0 ? "+" : ""}${row.assets_delta})`,
                    ],
                    [
                      "Findings",
                      `${row.findings} (${row.findings_delta >= 0 ? "+" : ""}${row.findings_delta})`,
                    ],
                    [
                      "Savings",
                      row.savings_max
                        ? `${savingsRange(row.savings_min, row.savings_max)} (${row.savings_delta >= 0 ? "+" : ""}${row.savings_delta})`
                        : "—",
                    ],
                    ["Duration", row.duration],
                    ["Started", absTime(row.started_ago)],
                  ]}
                />
              </PanelSection>
            ),
          },
        ]}
      />
      <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-surface px-5 py-2.5 text-xs text-muted-foreground">
        <Mono>{row.scan_id}</Mono>
        <span>·</span>
        <span>Started {relTime(row.started_ago)}</span>
        <span>·</span>
        <span>{row.stages_completed}/5 stages</span>
      </footer>
    </>
  );
}

/* -------------------------------- drift panel ----------------------------- */

export function ChangeBadge({ row }: { row: DriftRow }) {
  const sym = row.change === "added" ? "+" : row.change === "removed" ? "−" : "~";
  const style =
    row.change === "added"
      ? "bg-tint-emerald text-tint-emerald-fg"
      : row.change === "removed"
        ? "bg-tint-red text-tint-red-fg"
        : "bg-tint-amber text-tint-amber-fg";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-xs font-medium capitalize",
        style,
      )}
    >
      {sym} {row.label}
    </span>
  );
}

export function DriftPanel({ row }: { row: DriftRow }) {
  const { openAsset, openRun } = useConsolePanels();
  return (
    <>
      <EntityHeader
        name={row.resource_name}
        id={row.resource_uid}
        type={row.is_edge ? "vpc.network" : row.resource_type}
        badges={<ChangeBadge row={row} />}
        chips={
          <>
            <Chip onClick={() => openAsset(row.resource_uid)}>
              <Mono>{row.resource_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.account_id}</Mono>
            </Chip>
            <Chip>
              <Mono>{row.region}</Mono>
            </Chip>
            <Chip>{row.type_display}</Chip>
          </>
        }
      />
      <PanelBody>
        <PanelSection title="What changed">
          <p className="text-[13px]">{row.what}</p>
        </PanelSection>
        <PanelSection title="Between scans">
          <div className="panel flex items-center gap-2 px-3 py-2">
            <LinkText mono onClick={() => openRun(row.from_scan)}>
              {row.from_scan}
            </LinkText>
            <ArrowRight className="size-3 text-muted-foreground" />
            <LinkText mono onClick={() => openRun(row.to_scan)}>
              {row.to_scan}
            </LinkText>
            <span className="ml-auto">
              <RelTimeCell minutes={row.detected} />
            </span>
          </div>
        </PanelSection>
        <PanelSection title="Field diff">
          <DiffTable diff={row.diff} />
        </PanelSection>
      </PanelBody>
      <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-surface px-5 py-2.5 text-xs text-muted-foreground">
        <Mono>{row.to_scan}</Mono>
        <span>·</span>
        <span title={absTime(row.detected)}>Detected {relTime(row.detected)}</span>
      </footer>
    </>
  );
}
