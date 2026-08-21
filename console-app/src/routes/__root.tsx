import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { CloudCog, Search } from "lucide-react";
import { AppSidebar } from "@/components/console/AppSidebar";
import { PanelProvider } from "@/components/console/panels";

import { Toaster } from "@/components/ui/sonner";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 card-title font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-[13px] text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="card-title font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-[13px] text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-[13px] font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Cloud Estate Console — Cloud Governance" },
      {
        name: "description",
        content:
          "Unified cloud governance: asset discovery, architecture mapping, CSPM compliance scanning and FinOps savings in one console.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
      },
      { rel: "icon", href: "/favicon.ico", type: "image/x-icon" },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      <PanelProvider>
        <div className="min-h-screen w-full bg-background">
          <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-border bg-rail">
            <div className="flex h-full w-60 shrink-0 items-center gap-2.5 border-r border-border px-5">
              <span className="flex size-7 items-center justify-center rounded-md bg-nav-active text-nav-active-fg">
                <CloudCog className="size-4" strokeWidth={2} />
              </span>
              <span className="text-[13px] font-semibold text-foreground">
                Cloud Estate Console
              </span>
            </div>
            <div className="flex flex-1 items-center gap-3 px-5">
              <button
                type="button"
                className="flex h-8 w-[260px] items-center gap-2 rounded-md border border-border bg-surface px-3 text-left text-[13px] text-sub shadow-card transition-colors duration-100 hover:border-border-strong"
              >
                <Search className="size-4" />
                <span className="flex-1">Search the estate…</span>
                <span className="mono text-[11px]">⌘K</span>
              </button>
              <div className="ml-auto flex items-center gap-3">
                <span className="chip chip-green">All scanners healthy</span>
                <span className="flex size-7 items-center justify-center rounded-full bg-nav-active text-[11px] font-bold text-nav-active-fg">
                  AK
                </span>
              </div>
            </div>
          </header>
          <div className="flex min-h-screen w-full pt-14">
            <div className="fixed bottom-0 top-14 w-60">
              <AppSidebar />
            </div>
            <main className="min-w-0 flex-1 bg-surface pl-60">
              {/* Required: nested routes render here. Removing <Outlet /> breaks all child routes. */}
              <Outlet />
            </main>
          </div>
        </div>
      </PanelProvider>
      <Toaster />
    </QueryClientProvider>
  );
}
