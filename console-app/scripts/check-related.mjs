import { readFileSync } from "node:fs";
import { relatedTo } from "../src/components/console/related.ts";
const S = JSON.parse(readFileSync(new URL("../../out/scene.json", import.meta.url), "utf8"));
const all = [];
const walk = (n) => {
  all.push(n);
  (n.children ?? []).forEach(walk);
};
walk(S.tree);
const show = (key) => {
  const n = all.find((x) => x.key === key);
  if (!n) return console.log(`(${key} not in scene)`);
  const rows = relatedTo(key, S.tree, S.edges ?? []);
  console.log(`\n${n.type}  ${n.name || n.id}   — ${rows.length} rows`);
  for (const r of rows) {
    const f = r.rollup ? `+ ${r.rollup - 5} more of ${r.rollup}` : r.name;
    console.log(
      `  ${r.relationship.padEnd(16)} ${String(f).slice(0, 42).padEnd(44)} ${r.type.padEnd(26)} via ${r.via || "—"}`,
    );
  }
};
show(all.find((n) => n.type === "ec2.instance")?.key);
show(all.find((n) => n.type === "ec2.security_group")?.key);
show(all.find((n) => n.type === "s3.bucket")?.key);
show(all.find((n) => n.type === "rds.db_instance")?.key);
