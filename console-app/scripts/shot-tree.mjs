import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const hit = await p.evaluate(() => {
  const els = [...document.querySelectorAll("div,button,span")];
  const el = els.reverse().find((e) => {
    const r = e.getBoundingClientRect();
    const t = (e.textContent ?? "").trim();
    return (
      r.x > 700 &&
      r.width > 90 &&
      r.width < 260 &&
      r.height > 14 &&
      r.height < 40 &&
      /^onam-eks-dedicated/.test(t) &&
      t.length < 60
    );
  });
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.x + 30, y: r.y + r.height / 2 };
});
await p.mouse.click(hit.x, hit.y);
await p.waitForTimeout(800);
// scroll the panel body to the Related tree
await p.evaluate(() => {
  const body = [...document.querySelectorAll("div")].find(
    (d) => d.className.includes("overflow-y-auto") && d.className.includes("flex-1"),
  );
  if (body) body.scrollTop = body.scrollHeight;
});
await p.waitForTimeout(400);
await p.screenshot({ path: "/tmp/tree.png" });
// now collapse the first expandable branch
const n = await p.evaluate(() => {
  const t = [...document.querySelectorAll('button[aria-expanded="true"]')];
  if (!t.length) return 0;
  t[0].click();
  return t.length;
});
await p.waitForTimeout(400);
await p.screenshot({ path: "/tmp/tree-collapsed.png" });
console.log("expandable branches:", n);
await b.close();
