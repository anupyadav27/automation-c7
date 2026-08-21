import * as React from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Columns3,
  Download,
  Rows3,
  Search,
  SearchX,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  sort?: (a: T, b: T) => number;
  align?: "right";
  /** audit columns are hidden by default but offered in the column picker */
  audit?: boolean;
  width?: string;
  csv?: (row: T) => string | number;
}

export interface Facet<T> {
  key: string;
  label: string;
  get: (row: T) => string | string[];
  options?: string[];
}

interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  facets?: Facet<T>[];
  defaultSort?: { key: string; dir: "asc" | "desc" };
  onRowClick?: (row: T) => void;
  search?: (row: T) => string;
  searchPlaceholder?: string;
  csvName?: string;
  toolbarExtra?: React.ReactNode;
  selectedKey?: string | null;
  expand?: (row: T) => React.ReactNode;
  pageSize?: number;
  emptyLabel?: string;
  /** left-edge severity stripe color per row */
  stripe?: (row: T) => string | undefined;
  loading?: boolean;
  /** table sits inside a card: drop its own frame (never two borders) */
  embedded?: boolean;
}

function FacetFilter<T>({
  facet,
  rows,
  selected,
  onChange,
}: {
  facet: Facet<T>;
  rows: T[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const options = React.useMemo(() => {
    if (facet.options) return facet.options;
    const set = new Set<string>();
    for (const r of rows) {
      const v = facet.get(r);
      if (Array.isArray(v)) v.forEach((x) => x && set.add(x));
      else if (v) set.add(v);
    }
    return [...set].sort();
  }, [facet, rows]);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "h-8 rounded-md text-[13px] font-medium",
            selected.length && "bg-tint-blue text-tint-blue-fg",
          )}
        >
          {facet.label}
          {selected.length ? (
            <span className="ml-1 rounded-full bg-primary/10 px-1.5 text-[11px] tnum text-primary">
              {selected.length}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-56 overflow-auto">
        <DropdownMenuLabel className="label-caps">{facet.label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o}
            checked={selected.includes(o)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(c) =>
              onChange(c ? [...selected, o] : selected.filter((x) => x !== o))
            }
            className="text-[13px]"
          >
            {o}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  facets = [],
  defaultSort,
  onRowClick,
  search,
  searchPlaceholder = "Search…",
  csvName = "export",
  toolbarExtra,
  selectedKey,
  expand,
  pageSize: initialPageSize = 50,
  emptyLabel = "No rows match the current filters.",
  stripe,
  loading = false,
  embedded = false,
}: DataTableProps<T>) {
  const [pageSize, setSize] = React.useState(initialPageSize);
  const [sort, setSort] = React.useState<{ key: string; dir: "asc" | "desc" } | null>(
    defaultSort ?? null,
  );
  const [visible, setVisible] = React.useState<Record<string, boolean>>(() =>
    Object.fromEntries(columns.map((c) => [c.key, !c.audit])),
  );
  const [filters, setFilters] = React.useState<Record<string, string[]>>({});
  const [q, setQ] = React.useState("");
  const [page, setPage] = React.useState(0);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [density, setDensity] = React.useState<32 | 48 | 56>(48);

  const activeFilters = Object.entries(filters).filter(([, v]) => v.length);

  const filtered = React.useMemo(() => {
    let out = rows;
    for (const [key, vals] of activeFilters) {
      const facet = facets.find((f) => f.key === key);
      if (!facet) continue;
      out = out.filter((r) => {
        const v = facet.get(r);
        return Array.isArray(v) ? v.some((x) => vals.includes(x)) : vals.includes(v);
      });
    }
    if (q.trim() && search) {
      const needle = q.trim().toLowerCase();
      out = out.filter((r) => search(r).toLowerCase().includes(needle));
    }
    return out;
  }, [rows, JSON.stringify(filters), q, search, facets]);

  const sorted = React.useMemo(() => {
    if (!sort) return filtered;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sort) return filtered;
    const copy = filtered.slice().sort(col.sort);
    return sort.dir === "asc" ? copy : copy.reverse();
  }, [filtered, sort, columns]);

  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pages - 1);
  const pageRows = sorted.slice(current * pageSize, current * pageSize + pageSize);
  const shownColumns = columns.filter((c) => visible[c.key]);
  const pageButtons = React.useMemo(() => {
    const start = Math.max(0, Math.min(current - 2, pages - 5));
    return Array.from({ length: Math.min(5, pages) }, (_, i) => start + i).filter((p) => p < pages);
  }, [current, pages]);

  const exportCsv = () => {
    const head = shownColumns.map((c) => c.header);
    const lines = [head.join(",")];
    for (const r of sorted) {
      lines.push(
        shownColumns
          .map((c) => {
            const raw = c.csv ? c.csv(r) : "";
            return `"${String(raw).replace(/"/g, '""')}"`;
          })
          .join(","),
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${csvName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggleSort = (col: Column<T>) => {
    if (!col.sort) return;
    setPage(0);
    setSort((s) =>
      s?.key === col.key
        ? { key: col.key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key: col.key, dir: "desc" },
    );
  };

  const btn =
    "h-8 rounded-md border border-border bg-surface-raised px-2.5 text-[13px] font-medium text-body transition-colors duration-100 hover:bg-surface-tertiary hover:text-foreground inline-flex items-center gap-1.5";

  const rowH = density === 32 ? "h-8" : density === 48 ? "h-12" : "h-14";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {search ? (
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-sub" />
            <Input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(0);
              }}
              placeholder={searchPlaceholder}
              className="h-8 w-64 rounded-md border-border-strong bg-surface-tertiary pl-10 text-[13px] placeholder:text-sub"
            />
          </div>
        ) : null}
        {facets.map((f) => (
          <FacetFilter
            key={f.key}
            facet={f}
            rows={rows}
            selected={filters[f.key] ?? []}
            onChange={(next) => {
              setFilters((s) => ({ ...s, [f.key]: next }));
              setPage(0);
            }}
          />
        ))}
        {activeFilters.length || q ? (
          <button
            type="button"
            className={btn}
            onClick={() => {
              setFilters({});
              setQ("");
            }}
          >
            <X className="size-4" /> Clear
          </button>
        ) : null}
        <span className="chip chip-info">{sorted.length.toLocaleString()} rows</span>
        {toolbarExtra}
        <div className="ml-auto flex items-center gap-1.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className={btn} title="Columns">
                <Columns3 className="size-4" /> Columns
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-96 w-60 overflow-auto">
              <DropdownMenuLabel className="label-caps">Columns</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {columns
                .filter((c) => !c.audit)
                .map((c) => (
                  <DropdownMenuCheckboxItem
                    key={c.key}
                    checked={visible[c.key] ?? false}
                    onSelect={(e) => e.preventDefault()}
                    onCheckedChange={(v) => setVisible((s) => ({ ...s, [c.key]: !!v }))}
                    className="text-[13px]"
                  >
                    {c.header}
                  </DropdownMenuCheckboxItem>
                ))}
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="label-caps">Audit columns</DropdownMenuLabel>
              {columns
                .filter((c) => c.audit)
                .map((c) => (
                  <DropdownMenuCheckboxItem
                    key={c.key}
                    checked={visible[c.key] ?? false}
                    onSelect={(e) => e.preventDefault()}
                    onCheckedChange={(v) => setVisible((s) => ({ ...s, [c.key]: !!v }))}
                    className="text-[13px]"
                  >
                    {c.header}
                  </DropdownMenuCheckboxItem>
                ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className={btn} title="Row density">
                <Rows3 className="size-4" /> Density
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuLabel className="label-caps">Row height</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {([32, 48, 56] as const).map((d) => (
                <DropdownMenuCheckboxItem
                  key={d}
                  checked={density === d}
                  onSelect={(e) => e.preventDefault()}
                  onCheckedChange={() => setDensity(d)}
                  className="text-[13px]"
                >
                  {d === 32 ? "Compact" : d === 48 ? "Default" : "Relaxed"} · {d}px
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <button type="button" className={btn} onClick={exportCsv} title="Export CSV">
            <Download className="size-4" /> Export
          </button>
        </div>
      </div>

      {/* table */}
      <div className={cn("min-h-0 flex-1 overflow-auto", !embedded && "table-frame")}>
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10">
            <tr className="h-10 bg-surface-tertiary text-left">
              {expand ? (
                <th className="w-8 border-b border-border-strong bg-surface-tertiary" />
              ) : null}
              {shownColumns.map((c) => (
                <th
                  key={c.key}
                  style={c.width ? { width: c.width } : undefined}
                  className={cn(
                    "border-b border-border-strong bg-surface-tertiary px-3 py-0 whitespace-nowrap first:pl-4 last:pr-4",
                    c.align === "right" && "text-right",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(c)}
                    className={cn(
                      "label-caps group inline-flex items-center gap-1",
                      c.sort ? "hover:text-foreground" : "cursor-default",
                      c.align === "right" && "justify-end",
                    )}
                  >
                    {c.header}
                    {c.sort ? (
                      sort?.key === c.key ? (
                        sort.dir === "asc" ? (
                          <ArrowUp className="size-3 text-primary" strokeWidth={2.5} />
                        ) : (
                          <ArrowDown className="size-3 text-primary" strokeWidth={2.5} />
                        )
                      ) : (
                        <ArrowDown className="size-3 opacity-0 transition-opacity duration-100 group-hover:opacity-60" />
                      )
                    ) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className={cn("grid-cell", rowH)}>
                    {expand ? <td /> : null}
                    {shownColumns.map((c) => (
                      <td key={c.key} className="px-3 first:pl-4 last:pr-4">
                        <span className="shimmer block h-3 w-[70%]" />
                      </td>
                    ))}
                  </tr>
                ))
              : pageRows.map((r) => {
                  const key = rowKey(r);
                  const isOpen = expanded === key;
                  const stripeColor = stripe?.(r);
                  return (
                    <React.Fragment key={key}>
                      <tr
                        onClick={() => {
                          if (expand) setExpanded(isOpen ? null : key);
                          onRowClick?.(r);
                        }}
                        style={
                          stripeColor && selectedKey !== key
                            ? { boxShadow: `inset 3px 0 0 0 ${stripeColor}` }
                            : undefined
                        }
                        className={cn(
                          "group/row data-row grid-cell align-middle",
                          rowH,
                          (onRowClick || expand) && "cursor-pointer",
                          selectedKey === key &&
                            "bg-row-selected shadow-[inset_3px_0_0_0_var(--primary)] hover:bg-row-selected",
                        )}
                      >
                        {expand ? (
                          <td className="pl-3">
                            <ChevronRight
                              className={cn(
                                "size-4 text-sub transition-transform duration-100",
                                isOpen && "rotate-90",
                              )}
                            />
                          </td>
                        ) : null}
                        {shownColumns.map((c) => (
                          <td
                            key={c.key}
                            className={cn(
                              "px-3 py-1.5 text-body first:pl-4 last:pr-4",
                              c.align === "right" && "text-right tnum",
                            )}
                          >
                            {c.cell(r)}
                          </td>
                        ))}
                      </tr>
                      {expand && isOpen ? (
                        <tr className="grid-cell bg-row-hover">
                          <td colSpan={shownColumns.length + 1} className="px-4 py-4">
                            {expand(r)}
                          </td>
                        </tr>
                      ) : null}
                    </React.Fragment>
                  );
                })}
            {!loading && !pageRows.length ? (
              <tr>
                <td
                  colSpan={shownColumns.length + (expand ? 1 : 0)}
                  className="px-6 py-16 text-center"
                >
                  <div className="flex flex-col items-center gap-3">
                    <span
                      className="flex size-10 items-center justify-center rounded-full"
                      style={{ background: "color-mix(in srgb, var(--sev-info) 12%, transparent)" }}
                    >
                      <SearchX className="size-5 text-sev-info" />
                    </span>
                    <span className="text-[13px] font-medium text-foreground">{emptyLabel}</span>
                    <span className="text-xs text-muted-foreground">
                      {activeFilters.length || q
                        ? "Clear the filters or widen your search to see rows again."
                        : "New rows appear here after the next discovery run completes."}
                    </span>
                    {activeFilters.length || q ? (
                      <button
                        type="button"
                        className={btn}
                        onClick={() => {
                          setFilters({});
                          setQ("");
                        }}
                      >
                        Clear filters
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {/* pagination */}
      <div className="panel-flat flex flex-wrap items-center justify-between gap-3 px-4 py-2 text-[13px]">
        <span className="text-xs text-muted-foreground tnum">
          {sorted.length === 0
            ? "0 of 0"
            : `${current * pageSize + 1}–${Math.min(sorted.length, (current + 1) * pageSize)} of ${sorted.length.toLocaleString()}`}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Rows per page</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setSize(Number(e.target.value));
              setPage(0);
            }}
            className="h-8 rounded-md border border-border bg-surface-raised px-2 text-[13px] text-body"
          >
            {[25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className={cn(btn, "disabled:opacity-40")}
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              Prev
            </button>
            {pageButtons.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPage(p)}
                className={cn(
                  "h-8 min-w-8 rounded-md border px-2 text-[13px] font-medium transition-colors duration-100",
                  p === current
                    ? "border-transparent text-white"
                    : "border-border bg-surface-raised text-body hover:bg-surface-tertiary",
                )}
                style={p === current ? { background: "rgb(37,99,235)" } : undefined}
              >
                {p + 1}
              </button>
            ))}
            <button
              type="button"
              className={cn(btn, "disabled:opacity-40")}
              disabled={current >= pages - 1}
              onClick={() => setPage(current + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
