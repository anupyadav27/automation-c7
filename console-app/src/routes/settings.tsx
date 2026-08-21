import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Check, Laptop, Cloud, FlaskConical, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Chip, Mono, PageHeader } from "@/components/console/primitives";
import { REGIONS } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Cloud Estate Console" },
      {
        name: "description",
        content:
          "Choose the execution mode (local, Lambda or mock), default region, cache TTL and tenant id used by every pipeline run.",
      },
      { property: "og:title", content: "Settings — Cloud Estate Console" },
      {
        property: "og:description",
        content: "Execution mode, default region, cache TTL and tenant configuration.",
      },
    ],
  }),
  component: SettingsPage,
});

const MODES = [
  {
    key: "local",
    label: "Local",
    icon: Laptop,
    endpoint: "http://localhost:8082",
    detail: "Runs the pipeline against a local FastAPI worker. Full AWS credentials required.",
  },
  {
    key: "lambda",
    label: "Lambda",
    icon: Cloud,
    endpoint: "https://api-gw.execute-api.ap-south-1.amazonaws.com/prod",
    detail: "Invokes the deployed stage functions through API Gateway with IAM auth.",
  },
  {
    key: "mock",
    label: "Mock",
    icon: FlaskConical,
    endpoint: "in-memory fixtures",
    detail: "Serves deterministic fixture data. No cloud calls are made.",
  },
] as const;

function SettingsPage() {
  const [mode, setMode] = useState<string>("mock");
  const [region, setRegion] = useState("ap-south-1");
  const [ttl, setTtl] = useState("15");
  const [tenant, setTenant] = useState("acme-prod");

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col p-6">
      <PageHeader
        icon={Settings2}
        title="Settings"
        subtitle="Runtime configuration applied to every stage of the pipeline."
        meta={
          <>
            <Chip>
              mode <Mono className="text-primary">{mode}</Mono>
            </Chip>
            <Chip>
              tenant <Mono>{tenant}</Mono>
            </Chip>
          </>
        }
        actions={
          <Button
            size="sm"
            onClick={() =>
              toast.success("Settings saved", {
                description: `${mode} · ${region} · ttl ${ttl}m · ${tenant}`,
              })
            }
          >
            Save changes
          </Button>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="max-w-4xl space-y-6">
          <section>
            <div className="label-caps mb-2">Execution mode</div>
            <div className="grid gap-3 md:grid-cols-3">
              {MODES.map((m) => {
                const active = mode === m.key;
                return (
                  <button
                    key={m.key}
                    onClick={() => setMode(m.key)}
                    className={cn(
                      "panel p-4 text-left transition-colors",
                      active ? "border-primary/60 bg-primary/8" : "hover:border-border-strong",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <m.icon
                        className={cn("size-4", active ? "text-primary" : "text-muted-foreground")}
                      />
                      <span className="text-[13px] font-semibold">{m.label}</span>
                      {active ? (
                        <span className="ml-auto flex items-center gap-1 text-xs font-medium text-primary">
                          <Check className="size-3" /> active
                        </span>
                      ) : null}
                    </div>
                    <Mono className="mt-2 block break-all text-muted-foreground">{m.endpoint}</Mono>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{m.detail}</p>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="panel divide-y divide-border">
            <Field
              label="Default region"
              hint="Applied when a scan does not specify a region scope."
            >
              <Select value={region} onValueChange={setRegion}>
                <SelectTrigger className="h-8 w-56 bg-background text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REGIONS.map((r) => (
                    <SelectItem key={r} value={r} className="mono">
                      {r}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label="Cache TTL" hint="Minutes before discovered assets are considered stale.">
              <div className="flex items-center gap-2">
                <Input
                  value={ttl}
                  onChange={(e) => setTtl(e.target.value)}
                  inputMode="numeric"
                  className="h-8 w-24 rounded-md bg-background text-[13px]"
                />
                <span className="text-xs text-muted-foreground">minutes</span>
              </div>
            </Field>

            <Field label="Tenant id" hint="Namespaces assets, findings and recommendations.">
              <Input
                value={tenant}
                onChange={(e) => setTenant(e.target.value)}
                className="h-8 w-56 rounded-md bg-background text-[13px]"
              />
            </Field>
          </section>

          <section className="panel p-4">
            <div className="label-caps mb-2">Resolved configuration</div>
            <pre className="mono whitespace-pre-wrap">{`{
  "execution_mode": "${mode}",
  "endpoint": "${MODES.find((m) => m.key === mode)!.endpoint}",
  "default_region": "${region}",
  "cache_ttl_minutes": ${Number(ttl) || 0},
  "tenant_id": "${tenant}",
  "dry_run_default": true
}`}</pre>
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-3.5">
      <div>
        <div className="text-[13px] font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </div>
      {children}
    </div>
  );
}
