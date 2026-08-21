import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  Boxes,
  Network,
  ShieldCheck,
  PiggyBank,
  ScrollText,
  History,
  Settings2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ASSETS, FINDINGS, RECOMMENDATIONS, POLICY_COUNT, DRIFT_COUNT } from "@/lib/mock-data";

const sections = [
  {
    label: "Discover",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, badge: null },
      { to: "/inventory", label: "Inventory", icon: Boxes, badge: String(ASSETS.length) },
      { to: "/architecture", label: "Architecture", icon: Network, badge: null },
    ],
  },
  {
    label: "Operate",
    items: [{ to: "/settings", label: "Settings", icon: Settings2, badge: null }],
  },
] as const;

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-rail">
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {sections.map((section) => (
          <div key={section.label} className="mb-5">
            <div className="section-caps px-3 pb-2">{section.label}</div>
            {section.items.map((m) => {
              const active = m.to === "/" ? pathname === "/" : pathname.startsWith(m.to);
              return (
                <Link
                  key={m.to}
                  to={m.to}
                  className={cn(
                    "mb-0.5 flex h-9 items-center gap-2.5 rounded-md border-l-[3px] pr-2.5 pl-2 text-sm font-medium transition-colors duration-100",
                    active
                      ? "border-l-nav-active-fg bg-nav-active text-nav-active-fg"
                      : "border-l-transparent text-nav hover:bg-nav-hover hover:text-foreground",
                  )}
                >
                  <m.icon
                    className={cn(
                      "size-[18px] shrink-0",
                      active ? "text-nav-active-fg" : "text-sub",
                    )}
                    strokeWidth={2}
                  />
                  <span className="flex-1 truncate">{m.label}</span>
                  {m.badge ? (
                    <span
                      className={cn(
                        "rounded-full px-1.5 text-[11px] font-bold tnum",
                        active
                          ? "bg-white text-nav-active-fg"
                          : "bg-surface-tertiary text-muted-foreground",
                      )}
                    >
                      {m.badge}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border px-5 py-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="size-1.5 rounded-full bg-green" />
          <span>Mock execution · ap-south-1</span>
        </div>
        <div className="mt-1 text-xs text-sub">Tenant acme-prod</div>
      </div>
    </aside>
  );
}
