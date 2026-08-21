import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1800, height: 1200 } });
const errs = []; p.on("pageerror", (e) => errs.push(String(e)));
const log = (n, ok, d = "") => console.log(`${ok ? "PASS" : "FAIL"}  ${n}${d ? "  — " + d : ""}`);

await p.goto("http://localhost:3200/architecture", { waitUntil: "networkidle" });
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: "networkidle" });
await p.waitForTimeout(2500);

/* The ACCOUNT's own north strip, not "any element whose text says CloudFront".
   The first probe matched an inline service tile and reported a failure that
   was entirely its own — the tab it should have measured reads
   `network · delivery`, because a door on a border is grouped by domain and
   counted like every other tab. */
const strip = await p.evaluate(() => {
  const strips = [...document.querySelectorAll("[data-canvas] div")].filter((d) =>
    d.className?.toString?.().includes("-translate-y-full"),
  );
  // The account is the outermost box, so its strip is the widest.
  const account = strips.sort((a, z) => z.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
  if (!account) return null;
  const zones = [...account.children].map((z) => {
    const tabs = [...z.querySelectorAll("button")].map((t) => ({
      label: t.textContent.trim().replace(/\s+/g, " "),
      x: Math.round(t.getBoundingClientRect().x),
    }));
    return tabs;
  });
  return { justify: getComputedStyle(account).justifyContent, zones, mid: Math.round(innerWidth / 2) };
});

log("account north strip exists", !!strip);
if (strip) {
  const [left, centre, right] = strip.zones;
  console.log("   left  :", JSON.stringify(left));
  console.log("   centre:", JSON.stringify(centre));
  console.log("   right :", JSON.stringify(right));

  log("strip splits its ends", strip.justify === "space-between", strip.justify);
  log("org tab is on the left", left.some((t) => /management . account/.test(t.label)),
      left.map((t) => t.label).join(","));
  log("DNS and CDN are on the right",
      right.some((t) => /dns-zones/.test(t.label)) && right.some((t) => /delivery/.test(t.label)),
      right.map((t) => t.label).join(","));
  const rightmost = right.length ? Math.min(...right.map((t) => t.x)) : -1;
  const leftmost = left.length ? Math.max(...left.map((t) => t.x)) : Infinity;
  log("left zone is left of the right zone", leftmost < rightmost, `${leftmost} < ${rightmost}`);
  log("nothing left inline that belongs on the border",
      !centre.some((t) => /delivery|dns-zones|management . account/.test(t.label)),
      centre.map((t) => t.label).join(",") || "(empty)");
}

// Inner strips must be untouched — a new field may not move what predates it.
const inner = await p.evaluate(() =>
  [...document.querySelectorAll("[data-canvas] div")]
    .filter((d) => d.className?.toString?.().includes("-translate-y-full"))
    .map((d) => getComputedStyle(d).justifyContent)
    .slice(1),
);
log("region and VPC strips still centred", inner.every((j) => j === "center"), inner.join(","));

await p.screenshot({ path: "/tmp/border.png" });
console.log(errs.length ? "ERRORS: " + errs.slice(0, 3).join(" | ") : "no page errors");
await b.close();
