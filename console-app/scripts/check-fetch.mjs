import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const calls = [];
p.on("request", (r) => {
  if (r.url().includes("/api/v1/inventory/assets/")) calls.push(r.url().split("/api/v1")[1]);
});
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2000);
const chip = p.locator("[data-canvas] [data-node]", { hasText: /onam-eks-dedicated/ }).first();
await chip.scrollIntoViewIfNeeded();
await chip.click();
await p.waitForTimeout(1500);
console.log("API calls on click:", calls.length ? calls : "(none)");
const t = await p
  .locator("h3", { hasText: /Configuration/i })
  .first()
  .textContent()
  .catch(() => null);
console.log("heading:", (t ?? "").trim());
const bad = await p.locator("dd", { hasText: "[object" }).count();
console.log("object-dump cells:", bad);
await b.close();
