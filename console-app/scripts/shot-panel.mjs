import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1100 } });
const errs = [];
p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
p.on("pageerror", (e) => errs.push(String(e)));
await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
// click an EC2 instance chip
const hit = await p.evaluate(() => {
  // A node chip is a clickable element inside the VPC band whose text starts
  // with the instance name; the legend chips at the left are not nodes.
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
  return { x: r.x + 30, y: r.y + r.height / 2, text: (el.textContent || "").trim().slice(0, 40) };
});
if (!hit) {
  console.log("no instance chip found");
  await b.close();
  process.exit(0);
}
console.log("clicking:", hit.text);
await p.mouse.click(hit.x, hit.y);
await p.waitForTimeout(900);
await p.screenshot({ path: "/tmp/panel.png" });
console.log(errs.length ? "ERRORS:\n" + errs.slice(0, 6).join("\n") : "no console errors");
await b.close();
