import { readFileSync } from "node:fs";
import {
  relatedTo,
  toTree,
  byService,
} from "/Users/apple/Desktop/cloud-estate/console-app/src/components/console/related.ts";
const S = JSON.parse(readFileSync("/Users/apple/Desktop/cloud-estate/out/scene.json", "utf8"));
const all = [];
const w = (n) => {
  all.push(n);
  (n.children ?? []).forEach(w);
};
w(S.tree);
const E = S.relations ?? S.edges ?? [];
// The types that gained rules this round.
for (const t of [
  "elbv2.listener",
  "ec2.route_table",
  "eks.cluster",
  "stepfunctions.state_machine",
  "cloudtrail.trail",
  "ec2.flow_log",
  "ec2.vpc",
  "eks.nodegroup",
  "elb.load_balancer",
]) {
  const n = all.find((x) => x.type === t);
  if (!n) {
    console.log(`${t.padEnd(30)} (not in scene)`);
    continue;
  }
  const g = byService(toTree(relatedTo(n.key, S.tree, E)));
  const tot = g.reduce((a, s) => a + s.total, 0);
  console.log(
    `${t.padEnd(30)} ${String(tot).padStart(3)}  ${g.map((s) => `${s.service}:${s.total}`).join(" ")}`,
  );
}
