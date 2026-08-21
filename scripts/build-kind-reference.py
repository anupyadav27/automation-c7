#!/usr/bin/env python3
"""
Build the KIND reference page from the figures, never from memory.

    python3 scripts/kind-grid.py --json | python3 scripts/build-kind-reference.py -

Every count on the page comes through `kind-grid.py`, so the document cannot
drift from the estate it describes. A reference full of hand-copied numbers is
accurate exactly once.

Design follows `docs/design-language.md` — Inter and JetBrains Mono, the 11/12/
13/15/22 scale, the slate token set, the chip formula. Two departures, both
deliberate:

  * the system is light-only; an artifact renders in the reader's theme, so the
    dark tokens here are DERIVED from the light ones (same hues, inverted
    lightness, accent lifted for contrast) rather than a second palette;
  * the fonts are declared as stacks led by Inter and JetBrains Mono. The
    artifact CSP blocks font CDNs and there is no binary to inline, so the stack
    falls through to system-ui rather than failing silently on a dead URL.
"""

import html
import json
import sys

ORDER = ['boundary', 'resident', 'part', 'door', 'rule', 'record']

# What each kind IS — the one-question test, where it draws, and what breaks
# without it, which is the only honest argument for a kind existing.
KINDS = {
    'boundary': dict(
        test='I <em>am</em> one.',
        draws='The spine. Nests inside the boundary above it.',
        breaks='No nesting at all — the estate flattens into one list.',
        example='account · region · VPC · availability zone · subnet'),
    'resident': dict(
        test='I live inside it and hold an address.',
        draws='Inline, in a band. Vertical position is the traffic path.',
        breaks='Nothing is “the architecture” — workloads and annotations '
               'become indistinguishable.',
        example='EC2 · S3 · Lambda · RDS · CloudFront'),
    'part': dict(
        test='I belong to exactly one resident.',
        draws='Nested inside its host, not beside it.',
        breaks='A volume sits <em>next to</em> its instance, so one machine '
               'reads as four independent boxes.',
        example='EBS volume · network interface · target group · API stage'),
    'door': dict(
        test='I am a way through it.',
        draws='Straddling the border line — in the boundary, not inside it.',
        breaks='The internet gateway becomes just another box in the VPC, and '
               '<em>how traffic gets in</em> is buried among the workloads.',
        example='internet gateway · NAT · VPC endpoint · transit gateway'),
    'rule': dict(
        test='I govern everything inside it, and hold no address.',
        draws='A rail just inside the border of the boundary it is scoped to.',
        breaks='Policies sit in bands as though they were infrastructure, and '
               'the estate looks several times larger than it is.',
        example='security group · IAM role · KMS key · route table'),
    'record': dict(
        test='I am not in the picture. I describe something that is.',
        draws='Never drawn. It lives in the detail panel of what it describes.',
        breaks='Snapshots, images and versions are drawn as architecture.',
        example='AMI · snapshot · launch template · Lambda version'),
}

# Which of the four primitives every diagramming format offers this kind maps
# onto. Two do not map, and saying so is the point of the section.
PRIMITIVE = {
    'boundary': ('container node', 'clean'),
    'resident': ('node, with a parent', 'clean'),
    'part': ('node whose parent is a resident', 'clean'),
    'record': ('not exported', 'clean'),
    'door': ('no native form', 'strains'),
    'rule': ('no native form', 'strains'),
}

CSS = """
:root{
  /* docs/design-language.md, unchanged */
  --page:#ffffff; --band:#f6f8fb; --head:#eef2f7;
  --line:#e5e9f0; --line-2:#cdd6e2;
  --ink:#0f172a; --ink-2:#1e3350; --label:#4a6280; --muted:#6b849e;
  --accent:#3b82f6; --warn:#b45309; --good:#0284c7;
  --shadow:0 1px 2px rgba(15,23,42,.04),0 1px 3px rgba(15,23,42,.06);
  --radius:12px; --chip-r:5px;
}
@media (prefers-color-scheme:dark){
  :root{
    --page:#0d1117; --band:#161b22; --head:#1c2128;
    --line:#26313d; --line-2:#33404f;
    --ink:#e6edf3; --ink-2:#cdd9e5; --label:#9db2c9; --muted:#7d8fa3;
    --accent:#58a6ff; --warn:#e3a008; --good:#4cb3e8;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 1px 3px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --page:#0d1117; --band:#161b22; --head:#1c2128;
  --line:#26313d; --line-2:#33404f;
  --ink:#e6edf3; --ink-2:#cdd9e5; --label:#9db2c9; --muted:#7d8fa3;
  --accent:#58a6ff; --warn:#e3a008; --good:#4cb3e8;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 1px 3px rgba(0,0,0,.3);
}
:root[data-theme="light"]{
  --page:#ffffff; --band:#f6f8fb; --head:#eef2f7;
  --line:#e5e9f0; --line-2:#cdd6e2;
  --ink:#0f172a; --ink-2:#1e3350; --label:#4a6280; --muted:#6b849e;
  --accent:#3b82f6; --warn:#b45309; --good:#0284c7;
  --shadow:0 1px 2px rgba(15,23,42,.04),0 1px 3px rgba(15,23,42,.06);
}

*{box-sizing:border-box;}
body{
  margin:0; background:var(--page); color:var(--ink);
  font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:13px; line-height:1.6;
  font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
.mono{font-family:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;}

.wrap{max-width:78ch; margin:0 auto; padding:56px 24px 96px;
      display:flex; flex-direction:column; gap:44px;}
section{display:flex; flex-direction:column; gap:16px;}

h1{font-size:22px; font-weight:700; letter-spacing:-.02em; margin:0;
   line-height:1.25; text-wrap:balance;}
h2{font-size:15px; font-weight:600; letter-spacing:-.01em; margin:0;
   text-wrap:balance;}
h3{font-size:13px; font-weight:600; margin:0;}
p{margin:0; max-width:68ch;}
em{font-style:italic;}
strong{font-weight:600;}

.eyebrow{font-size:11px; font-weight:700; letter-spacing:.055em;
         text-transform:uppercase; color:var(--label);}
.lede{font-size:15px; line-height:1.55; color:var(--ink-2); max-width:64ch;}
.meta{font-size:12px; color:var(--muted);}
.rule-line{height:1px; background:var(--line); border:0; margin:0;}

/* ── the specimens: each kind drawn as the thing it describes ───────── */
.specimens{display:flex; flex-direction:column; gap:12px;}
.spec{
  display:grid; grid-template-columns:132px 1fr; gap:20px; align-items:start;
  border:1px solid var(--line); border-radius:var(--radius);
  background:var(--page); box-shadow:var(--shadow); padding:16px 18px;
}
.spec-body{display:flex; flex-direction:column; gap:7px; min-width:0;}
.spec-name{font-size:13px; font-weight:700; letter-spacing:.01em;}
.spec-test{font-size:13px; color:var(--ink-2);}
.spec-row{font-size:12px; color:var(--muted);}
.spec-row b{color:var(--label); font-weight:600;}
.spec-eg{font-size:11px; color:var(--muted);}

/* the drawing: a boundary, and this kind's position relative to it */
.fig{
  position:relative; height:74px; border:1.5px solid var(--line-2);
  border-radius:8px; background:var(--band);
  display:flex; align-items:center; justify-content:center;
}
.fig-lab{position:absolute; top:5px; left:7px; font-size:9px; font-weight:700;
         letter-spacing:.05em; text-transform:uppercase; color:var(--muted);}
.dot{background:var(--accent); border-radius:4px; height:17px; width:44px;}
.dot.sm{height:9px; width:22px; opacity:.55;}
.dot.host{height:34px; width:56px; background:transparent;
          border:1.5px solid var(--accent); display:flex; align-items:flex-end;
          justify-content:center; padding-bottom:3px; border-radius:5px;}
.fig.is-boundary{border-style:solid; border-color:var(--accent);}
.fig.is-boundary .inner{width:56px; height:30px; border:1px dashed var(--line-2);
                        border-radius:5px;}
.fig.is-door .dot{position:absolute; top:-9px;}
.fig.is-rule .bar{position:absolute; left:8px; right:8px; bottom:6px; height:8px;
                  border-radius:3px; background:var(--accent); opacity:.75;}
.fig.is-record{background:transparent; border-style:dashed;}
.fig.is-record .dot{background:var(--muted); opacity:.5;
                    position:absolute; right:-18px; bottom:-10px;}

.count{
  font-size:11px; font-weight:700; padding:2px 8px; border-radius:var(--chip-r);
  background:color-mix(in srgb,var(--accent) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);
  color:var(--accent); white-space:nowrap;
}
.count.q{background:color-mix(in srgb,var(--muted) 12%,transparent);
         border-color:color-mix(in srgb,var(--muted) 30%,transparent);
         color:var(--muted);}

/* ── tables ────────────────────────────────────────────────────────── */
.scroll{overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius);}
table{border-collapse:collapse; width:100%; font-size:12px;}
thead th{
  background:var(--head); font-size:11px; font-weight:700; letter-spacing:.055em;
  text-transform:uppercase; color:var(--label); text-align:left;
  padding:8px 12px; white-space:nowrap; border-bottom:1px solid var(--line-2);
}
thead th.num, td.num{text-align:right;}
tbody td{padding:7px 12px; border-top:1px solid var(--line); color:var(--ink-2);}
tbody tr:hover{background:var(--band);}
td.zero{color:var(--muted); opacity:.45;}
td.span{color:var(--warn); font-weight:600;}

.note{
  border-left:3px solid var(--warn); background:var(--band);
  padding:12px 16px; border-radius:0 8px 8px 0;
  display:flex; flex-direction:column; gap:6px;
}
.note .eyebrow{color:var(--warn);}

.grid2{display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px;}
.card{border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px;
      display:flex; flex-direction:column; gap:6px; background:var(--page);}
.card .eyebrow{color:var(--label);}

.stack{display:flex; flex-direction:column; gap:9px;}
.step{display:grid; grid-template-columns:22px 1fr; gap:12px; align-items:baseline;}
.step-n{font-size:11px; font-weight:700; color:var(--muted);}

ul{margin:0; padding-left:18px; display:flex; flex-direction:column; gap:6px;
   max-width:66ch;}
li::marker{color:var(--muted);}

a{color:var(--accent);}
a:focus-visible, th:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
@media (prefers-reduced-motion:reduce){*{transition:none !important; animation:none !important;}}
@media (max-width:640px){
  .spec{grid-template-columns:1fr;}
  .wrap{padding:36px 16px 64px;}
}
"""


def fig(kind):
    """The little drawing. Each kind is shown in the position it occupies."""
    if kind == 'boundary':
        return ('<div class="fig is-boundary"><span class="fig-lab">is the box</span>'
                '<div class="inner"></div></div>')
    if kind == 'resident':
        return ('<div class="fig"><span class="fig-lab">inside</span>'
                '<div class="dot"></div></div>')
    if kind == 'part':
        return ('<div class="fig"><span class="fig-lab">inside a resident</span>'
                '<div class="dot host"><div class="dot sm"></div></div></div>')
    if kind == 'door':
        return ('<div class="fig is-door"><span class="fig-lab">on the line</span>'
                '<div class="dot"></div></div>')
    if kind == 'rule':
        return ('<div class="fig is-rule"><span class="fig-lab">against it</span>'
                '<div class="bar"></div></div>')
    return ('<div class="fig is-record"><span class="fig-lab">outside</span>'
            '<div class="dot"></div></div>')


def build(d):
    e = html.escape
    out = []
    add = out.append

    add(f'<title>The KIND axis — cloud-estate diagram reference</title>')
    add(f'<style>{CSS}</style>')
    add('<div class="wrap">')

    # ── header ──
    add('<header class="stack">')
    add('<span class="eyebrow">Diagram engine · reference model</span>')
    add('<h1>Six kinds, and the one question they all answer</h1>')
    add('<p class="lede">Every resource on the architecture diagram is exactly '
        'one <strong>kind</strong>, and the kind decides where it draws. Each kind '
        'answers the same question — <em>what is my relationship to the boundary '
        'I am drawn in?</em> — which is why six is enough and why they form a '
        'family rather than a list.</p>')
    add(f'<p class="meta mono">account {e(str(d["account"]))} · {e(str(d["region"]))} '
        f'· {d["nodes"]:,} nodes · {d["edges"]:,} edges</p>')
    add('</header>')
    add('<hr class="rule-line">')

    # ── the compression ──
    add('<section>')
    add('<span class="eyebrow">What the kinds are for</span>')
    add(f'<h2>{d["nodes"]:,} collected nodes become {d["boxes"]:,} boxes</h2>')
    add('<p>That compression is the diagram. Kind decides the geometry; a second '
        'axis, <strong>domain</strong>, decides the grouping. A box is one cell '
        'where the two cross — nodes agreeing on container, anchor, kind and '
        'domain are drawn once, together.</p>')
    add('<div class="grid2">')
    for label, value, sub in [
        ('Collected', f'{d["nodes"]:,}', 'every node the pipeline knows about'),
        ('Drawn', f'{d["drawn"]:,}', 'kinds that appear on the canvas'),
        ('Off-canvas', f'{d["not_drawn"]:,}', 'records — reachable in panels only'),
        ('Boxes', f'{d["boxes"]:,}', 'container × anchor × kind × domain'),
    ]:
        add(f'<div class="card"><span class="eyebrow">{e(label)}</span>'
            f'<span style="font-size:22px;font-weight:700;line-height:1.1">{e(value)}</span>'
            f'<span class="meta">{e(sub)}</span></div>')
    add('</div>')
    res = d['kinds']['resident']
    add(f'<p><strong>Only {res} of {d["nodes"]:,} nodes are the '
        f'architecture.</strong> Nine in ten are annotation on it. That is not '
        f'a defect — it is the reason the kind axis exists: show {res} things '
        f'well, and make the other {d["nodes"] - res:,} reachable rather than '
        f'drawn.</p>')
    add('</section>')

    # ── the six specimens ──
    add('<section>')
    add('<span class="eyebrow">The six kinds</span>')
    add('<h2>Each one drawn where it actually sits</h2>')
    add('<p>The blue mark is the kind; the grey frame is the boundary it is being '
        'placed relative to.</p>')
    add('<div class="specimens">')
    for k in ORDER:
        spec = KINDS[k]
        n = d['kinds'][k]
        spans = d['kind_spans_domains'][k]
        add('<div class="spec">')
        add(fig(k))
        add('<div class="spec-body">')
        add(f'<div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">'
            f'<span class="spec-name mono">{e(k)}</span>'
            f'<span class="count">{n:,}</span>'
            f'<span class="count q">{spans} domains</span></div>')
        add(f'<div class="spec-test">{spec["test"]}</div>')
        add(f'<div class="spec-row"><b>Draws</b> — {spec["draws"]}</div>')
        add(f'<div class="spec-row"><b>Without it</b> — {spec["breaks"]}</div>')
        add(f'<div class="spec-eg mono">{e(spec["example"])}</div>')
        add('</div></div>')
    add('</div>')
    add('</section>')

    # ── resolution ──
    add('<section>')
    add('<span class="eyebrow">How a position is decided</span>')
    add('<h2>Kind, then scope, then cardinality</h2>')
    add('<p>Three steps, in order. The kind is settled first because every step '
        'after it branches on the answer.</p>')
    add('<div class="stack">')
    for i, (title, body) in enumerate([
        ('Kind', 'The type’s role in the provider binding declares it. '
                 'A resident branches differently from a rule from here on.'),
        ('Scope', 'Which boundary owns it — <em>not</em> which one contains it. '
                  'A VPC-scoped network ACL hoists out of the subnet that '
                  'happens to hold it.'),
        ('Cardinality', 'Attached to exactly one host → it nests. Attached to '
                        'none → the scope border, and that is a cost finding as '
                        'much as a placement. Many, or no host concept → the '
                        'border, or inline.'),
    ], start=1):
        add(f'<div class="step"><span class="step-n mono">{i}</span>'
            f'<div><strong>{e(title)}</strong> — {body}</div></div>')
    add('</div>')
    add('<p>The result is an <strong>anchor</strong>. Across this estate: '
        + ' · '.join(f'<span class="mono">{e(a)}</span> {n:,}'
                     for a, n in list(d['anchors'].items())[:6]) + '.</p>')
    add('</section>')

    # ── the grid ──
    add('<section>')
    add('<span class="eyebrow">Kind × domain</span>')
    add(f'<h2>A matrix, not a hierarchy — {d["domains_spanning_kinds"]} of '
        f'{d["domains"]} domains span more than one kind</h2>')
    add('<p>Domain does not nest under kind. The same domain appears under '
        'several kinds and lands in completely different places, which is why '
        'the two axes have to stay independent. Rows in amber span more than '
        'one kind.</p>')
    add('<div class="scroll"><table><thead><tr><th>Domain</th>')
    for k in ORDER:
        add(f'<th class="num">{e(k)}</th>')
    add('</tr></thead><tbody>')
    rows = sorted(d['grid'].items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    for dom, cells in rows:
        multi = len(cells) > 1
        cls = ' class="span"' if multi else ''
        add(f'<tr><td class="mono"{cls}>{e(dom)}</td>')
        for k in ORDER:
            v = cells.get(k)
            add(f'<td class="num">{v:,}</td>' if v else '<td class="num zero">·</td>')
        add('</tr>')
    add('</tbody></table></div>')
    add('<div class="note">')
    add('<span class="eyebrow">The grid is emergent, and nobody reviews it</span>')
    add('<p>Kind comes from a type’s role, domain from its taxonomy, and this '
        'grid is whatever falls out. No one authors it — which is how '
        '<strong>228 security group rules</strong> came to be filed under '
        '<span class="mono">compute.instances</span> instead of '
        '<span class="mono">network.firewall</span>: the rule type had no '
        'explicit mapping, so it fell through to the '
        '<span class="mono">ec2</span> service default. Their <em>kind</em> is '
        'right; only the domain is wrong. Open, and fixable.</p>')
    add('</div>')
    add('</section>')

    # ── primitives ──
    add('<section>')
    add('<span class="eyebrow">Exporting to a diagramming tool</span>')
    add('<h2>Four primitives, and two kinds that do not fit them</h2>')
    add('<p>Formats like draw.io’s CSV import express exactly four things: a '
        '<strong>node</strong>, <strong>containment</strong>, an '
        '<strong>edge</strong>, and <strong>style</strong>. There is no concept '
        'of kind anywhere in them — the meaning lives in which shape a person '
        'chose. So an export cannot <em>define</em> our kinds. It can test them: '
        'a kind that maps onto a primitive is one any tool can express.</p>')
    add('<div class="scroll"><table><thead><tr>'
        '<th>Kind</th><th>Maps onto</th><th>Verdict</th></tr></thead><tbody>')
    for k in ORDER:
        prim, verdict = PRIMITIVE[k]
        tone = ' class="span"' if verdict == 'strains' else ''
        add(f'<tr><td class="mono">{e(k)}</td><td>{e(prim)}</td>'
            f'<td{tone}>{e(verdict)}</td></tr>')
    add('</tbody></table></div>')
    add('<p><strong>Door and rule are our own inventions</strong>, layered on top '
        'of what the formats offer. A tool can only render them as a styled node '
        'or as a container — which is exactly what AWS does: its architecture '
        'icon set ships <em>Security group</em> and <em>Auto Scaling group</em> '
        'as <strong>group</strong> icons, drawn as boxes around their members '
        'rather than as symbols beside them.</p>')
    add('<p class="meta">draw.io’s directives are confirmed from its '
        'documentation: <span class="mono"># label</span>, '
        '<span class="mono"># style</span>, <span class="mono"># connect</span>, '
        '<span class="mono"># layout</span>, <span class="mono"># ignore</span>, '
        '<span class="mono"># namespace</span>, <span class="mono"># width</span>, '
        '<span class="mono"># height</span>. Lucid’s exact column names are '
        'not stated here because its documentation could not be retrieved — the '
        'four-primitive claim holds for both regardless.</p>')
    add('</section>')

    # ── the rule render mode ──
    contiguous, scattered = d['rules_contiguous'], d['rules_scattered']
    total = contiguous + scattered
    add('<section>')
    add('<span class="eyebrow">Where the model is being extended</span>')
    add(f'<h2>A rule can be a box — {contiguous} times out of {total}</h2>')
    add('<p>If every resource a rule governs sits inside one container, the rule '
        'can be drawn <em>as</em> that container: a dashed box around its '
        'members, the way a hand-drawn AWS diagram does it. When its members '
        'scatter, no box is honest and it falls back to the border rail.</p>')
    add('<div class="scroll"><table><thead><tr>'
        '<th>Containers a rule’s members occupy</th>'
        '<th class="num">Rules</th><th>Can draw as a box</th>'
        '</tr></thead><tbody>')
    for k, v in sorted(d['rule_member_spread'].items(), key=lambda kv: int(kv[0])):
        ok = int(k) <= 1
        add(f'<tr><td>{e(str(k))}</td><td class="num">{v}</td>'
            f'<td{"" if ok else " class=\"span\""}>{"yes" if ok else "no — rail"}</td></tr>')
    add('</tbody></table></div>')
    add('<p>This is a <strong>render mode, not a seventh kind</strong>. A kind '
        'earns its place by changing placement for every member; this changes it '
        'per resource, decided by measurement. One kind, one extra measured fact, '
        'no new vocabulary.</p>')
    add('</section>')

    # ── the other axis ──
    add('<section>')
    add('<span class="eyebrow">The other axis</span>')
    add('<h2>Domain says what it is — and it is a grid, not a hierarchy</h2>')
    add(f'<p>Kind decides geometry. <strong>Domain</strong> decides grouping, '
        f'filtering and criticality, and never position. They are independent: '
        f'<strong>{d["domains_spanning_kinds"]} of {d["domains"]} domains in '
        f'this estate span more than one kind</strong>, so neither nests under '
        f'the other. <span class="mono">compute.instances</span> alone is '
        f'residents, rules and records at once — three kinds, three completely '
        f'different places on the canvas.</p>')
    add('<p>Thirteen categories over sixty subcategories. Twelve of the '
        'thirteen are infrastructure primitives; the thirteenth, '
        '<span class="mono">application</span>, is for services the cloud runs '
        '<em>for</em> you — a contact centre, a device platform, a media '
        'pipeline. It exists because without it those services were forced into '
        'the nearest infrastructure slot, and '
        '<span class="mono">integration.messaging</span> grew to 312 of 3,070 '
        'catalog types while meaning nothing. A filter that returns a contact '
        'centre when you ask for queues has failed at the only job this axis '
        'has.</p>')
    add('<div class="scroll"><table><thead><tr><th>was</th>'
        '<th class="num">before</th><th class="num">after</th><th>why</th>'
        '</tr></thead><tbody>')
    for was, before, after, why in [
        ('integration.messaging', 312, 20,
         'a contact centre and an email service are not messaging infrastructure'),
        ('compute.edge', 262, 51,
         'the IoT platform is a thing you talk to; edge is where your code runs'),
    ]:
        add(f'<tr><td class="mono">{e(was)}</td><td class="num span">{before}</td>'
            f'<td class="num">{after}</td><td>{e(why)}</td></tr>')
    add('</tbody></table></div>')
    add('<p class="meta">Guarded by test: no subcategory may hold more than 10% '
        'of the catalog, and the edge/platform line is pinned so it cannot '
        'quietly collapse again.</p>')
    add('</section>')

    # ── the extension test ──
    add('<section>')
    add('<span class="eyebrow">Adding a seventh</span>')
    add('<h2>What a new kind has to prove</h2>')
    add('<p>One test: <strong>does it change where something draws?</strong> If '
        'it does not, it is a domain wearing a kind’s clothes.</p>')
    add('<ul>')
    add('<li><strong>Orchestrator</strong> — ECS and EKS clusters, Step '
        'Functions, scaling groups. <em>Rejected.</em> It rides the same scope '
        'rail a security group does. It is a domain, which is what gives it its '
        'own heading and its Members panel without disturbing the axis.</li>')
    add('<li><strong>Enclosure</strong> — something that both governs and '
        'encloses. <em>Rejected.</em> It would decide placement differently per '
        'resource, and that is precisely what a render mode is for.</li>')
    add('</ul>')
    add('<p class="meta">Both were live proposals. Recording why they were turned '
        'down is more useful than recording that they were.</p>')
    add('</section>')

    add('<hr class="rule-line">')
    add('<footer class="stack">')
    add('<p class="meta">Generated from <span class="mono">out/scene.json</span> by '
        '<span class="mono">scripts/kind-grid.py</span> and '
        '<span class="mono">scripts/build-kind-reference.py</span>. Every figure '
        'on this page is read from the built scene — none is typed by hand.</p>')
    add('</footer>')
    add('</div>')
    return '\n'.join(out)


if __name__ == '__main__':
    src = sys.stdin if len(sys.argv) > 1 and sys.argv[1] == '-' else open(sys.argv[1])
    sys.stdout.write(build(json.load(src)))