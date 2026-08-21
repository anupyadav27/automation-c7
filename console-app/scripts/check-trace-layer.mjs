import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = []; p.on("pageerror", (e) => errs.push(String(e)));
const log = (n, ok, d="") => console.log(`${ok?"PASS":"FAIL"}  ${n}${d?"  — "+d:""}`);

await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);

await p.locator("button", { hasText: "show connections" }).click();
await p.waitForTimeout(1200);
const svg = await p.evaluate(() => {
  const s = document.querySelector("svg.fixed.inset-0");
  if (!s) return null;
  return { z: +getComputedStyle(s).zIndex, parent: s.parentElement?.tagName, paths: s.querySelectorAll("path[stroke-width='1.5']").length };
});
log("trace overlay is portalled to body", svg?.parent === "BODY", `parent=${svg?.parent}`);
log("lines are drawn", (svg?.paths ?? 0) > 0, `${svg?.paths} paths`);

// Open a panel and confirm the lines still paint above it.
const tab = p.locator("[data-canvas] button").filter({ hasText: /\S/ }).nth(3);
await tab.scrollIntoViewIfNeeded(); await tab.click(); await p.waitForTimeout(800);
const panelZ = await p.evaluate(() => {
  const el = document.querySelector('[aria-label="close list"]')?.closest("div.fixed");
  return el ? +getComputedStyle(el).zIndex : null;
});
log("trace z is above the panel z", (svg?.z ?? 0) > (panelZ ?? 0), `trace z-${svg?.z} vs panel z-${panelZ}`);

// The decisive check: at a point on a line that crosses the panel, who wins?
const verdict = await p.evaluate(() => {
  const panel = document.querySelector('[aria-label="close list"]')?.closest("div.fixed");
  const s = document.querySelector("svg.fixed.inset-0");
  if (!panel || !s) return "no panel/svg";
  const pr = panel.getBoundingClientRect();
  // Does any drawn path pass through the panel's area?
  for (const path of s.querySelectorAll("path[stroke-width='1.5']")) {
    const r = path.getBoundingClientRect();
    const overlaps = r.left < pr.right && r.right > pr.left && r.top < pr.bottom && r.bottom > pr.top;
    if (overlaps) {
      // Compare paint order via compareDocumentPosition: later sibling paints on top.
      const later = panel.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING;
      return `overlapping line found; svg paints ${later ? "AFTER (on top of)" : "BEFORE"} panel`;
    }
  }
  return "no overlap in this arrangement";
});
console.log("      " + verdict);
await p.screenshot({ path: "/tmp/traces-over-panel.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0,3).join(" | ") : "no page errors");
await b.close();
