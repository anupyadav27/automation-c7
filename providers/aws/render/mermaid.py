"""
Scene graph -> Mermaid.

Mermaid is the default renderer because it needs nothing installed, renders in
GitHub, docs and chat, and diffs as text in git - so a diagram change shows up
in review as a change rather than as a new binary.

The mapping is direct, which is the point of the scene graph:

    nesting tree  -> nested `subgraph` blocks
    overlay group -> a visibility toggle over nodes already IN that tree
    arrow         -> `-->` with the edge type as its label

Two things Mermaid forces on us, both handled here rather than left to bite:
node ids must be alphanumeric, and labels must not contain quotes or brackets.
"""

import re

# Line style per edge type, so a reader can tell an attachment from a grant
# without reading every label.
EDGE_STYLE = {
    'attached-to': '---',
    'protected-by': '-.->',
    'encrypted-by': '-.->',
    'assumes': '==>',
    'can-access': '==>',
    'accessible-by': '==>',
    'routes-to': '-->',
}
DEFAULT_STYLE = '-->'

# Overlay groups shown by default. Overlays are a VISIBILITY TOGGLE over nodes
# that are already placed in the tree, not a separate region of the canvas -
# drawing identity, encryption and traffic all at once is what makes these
# diagrams unreadable, so they are opt-in.
DEFAULT_OVERLAYS = ()

_SAFE = re.compile(r'[^A-Za-z0-9]')


def _nid(key):
    """A Mermaid-safe node id. Deterministic so diffs stay stable."""
    return 'n' + _SAFE.sub('_', key)


def _label(text, limit=42):
    """Strip characters Mermaid treats as syntax."""
    text = str(text or '')
    text = text.replace('"', "'").replace('[', '(').replace(']', ')')
    text = text.replace('{', '(').replace('}', ')').replace('|', '/')
    return text[:limit]


def _type_name(resource_key):
    return resource_key.split('.', 1)[-1].replace('_', ' ') if resource_key else ''


def _anchor(node):
    return (node.get('position') or {}).get('anchor', 'in')


def _lane(node):
    return (node.get('position') or {}).get('lane')


# How many members of a category lane to name before collapsing to a count. The
# UI uses the same threshold, so a lane reads identically in both renderers.
COLLAPSE_AT = 5


def _emit_lane(lines, pad, container_id, lane, members, walk, depth):
    """
    One category lane as its own box.

    Without this every regional service is a peer of every other and the region
    is a flat wall of boxes - which is what it looked like when placement data
    existed but nothing consumed it. The lane is the grouping the model already
    decided; the renderer only has to honour it.
    """
    lid = f'{container_id}_lane_{_SAFE.sub("_", lane)}'
    lines.append(f'{pad}  subgraph {lid}["{_label(lane)} · {len(members)}"]')
    for node in members[:COLLAPSE_AT]:
        walk(node, depth + 2)
    if len(members) > COLLAPSE_AT:
        lines.append(f'{pad}    {lid}_more["+{len(members) - COLLAPSE_AT} more"]')
    lines.append(f'{pad}  end')


def _emit_rail_chips(lines, pad, container_id, rails):
    """
    Collapse each rail to one counted chip.

    A rail exists because those services apply to EVERYTHING in the container -
    drawing seventy security groups inline is what makes these diagrams
    unreadable, and it also asserts a position in the traffic path that they do
    not have. One chip per rail keeps the fact and drops the noise.
    """
    groups = {}
    for node in rails:
        side = _anchor(node).split('.', 1)[-1]
        groups.setdefault(side, []).append(node)
    for side, members in sorted(groups.items()):
        role = (members[0].get('position') or {}).get('role', 'rail')
        chip = f'{container_id}_rail_{side}'
        lines.append(f'{pad}  {chip}[/"{_label(role)} · {len(members)}"/]')


def render(scene, overlays=DEFAULT_OVERLAYS, direction='TB', show_types=True,
           expand_rails=False):
    """
    Render a Scene to Mermaid text.

    `overlays` names which overlay groups to SHOW. Every node is drawn in its
    real place in the tree; an overlay-tagged node that was not requested is
    simply skipped. Passing '*' shows everything.

    Children arrive from `to_dict()` already in placement order, so this walk
    never sorts - the ordering rule lives in exactly one place and a renderer
    cannot drift away from it.

    Two things Mermaid genuinely cannot draw, and how they degrade:

      * a node ON a border line. Mermaid has no concept of a boundary object,
        so `edge.*` anchors render FIRST inside their container with a hexagon
        shape. Position is approximated; the fact that it is a boundary is not.
      * a rail. Cross-cutting groups collapse to a single counted chip rather
        than being scattered through the flow, which is the readable half of
        what a rail is for. Pass expand_rails=True to draw the members.
    """
    doc = scene.to_dict()
    wanted = None if overlays == '*' else set(overlays)
    lines = [f'graph {direction}']
    drawn = set()

    def hidden(node):
        group = node.get('overlay')
        return bool(group) and wanted is not None and group not in wanted

    def walk(node, depth):
        if hidden(node) and not node.get('children'):
            return
        pad = '  ' * (depth + 1)
        nid = _nid(node['key'])
        drawn.add(node['key'])
        label = _label(node.get('name') or node['id'])
        kind = _type_name(node.get('type', ''))

        if node.get('children'):
            heading = f'{label}' if not show_types else f'{kind}: {label}'
            lines.append(f'{pad}subgraph {nid}["{_label(heading, 56)}"]')
            lines.append(f'{pad}  direction {direction}')

            kids = node['children']
            borders = [c for c in kids if _anchor(c).startswith('edge.')]
            rails = [c for c in kids if _anchor(c).startswith('rail.')]
            inflow = [c for c in kids if _anchor(c) == 'in']

            # Boundaries first: they are the container's edge, so they read
            # correctly at the top even without true border placement.
            for child in borders:
                bid = _nid(child['key'])
                drawn.add(child['key'])
                lines.append(f'{pad}  {bid}{{{{"{_label(child.get("name") or child["id"])}"}}}}')

            # Children already arrive in placement order, so grouping by lane
            # preserves that order without re-sorting.
            lanes, loose = {}, []
            for child in inflow:
                lane = _lane(child)
                if lane and not child.get('children'):
                    lanes.setdefault(lane, []).append(child)
                else:
                    loose.append(child)

            for child in loose:
                walk(child, depth + 1)
            for lane, members in lanes.items():
                _emit_lane(lines, pad, nid, lane, members, walk, depth)

            if expand_rails:
                for child in rails:
                    walk(child, depth + 1)
            else:
                _emit_rail_chips(lines, pad, nid, rails)

            lines.append(f'{pad}end')
        else:
            shape = f'["{label}"]' if not show_types else f'["{_label(kind)}<br/>{label}"]'
            lines.append(f'{pad}{nid}{shape}')

    if doc.get('tree'):
        walk(doc['tree'], 0)

    lines.append('')
    for edge in doc['edges']:
        # Only draw an arrow when both ends are on the canvas. An edge into an
        # overlay that was not requested would otherwise silently resurrect that
        # node as a bare, unlabelled box.
        if edge['source_key'] not in drawn or edge['target_key'] not in drawn:
            continue
        style = EDGE_STYLE.get(edge['edge_type'], DEFAULT_STYLE)
        lines.append(f'  {_nid(edge["source_key"])} {style}'
                     f'|{_label(edge["edge_type"], 24)}| {_nid(edge["target_key"])}')

    return '\n'.join(lines)


def render_summary(scene):
    """A counts-only view: services and totals, for when the full graph is too big."""
    doc = scene.to_dict()
    meta = doc['meta']
    lines = ['graph LR',
             f'  acct["{_label(meta["account_name"])}<br/>{meta["region"]}"]']
    for resource_key, count in list(meta['by_type'].items())[:40]:
        nid = _nid(resource_key)
        lines.append(f'  acct --> {nid}["{_label(_type_name(resource_key))}<br/>{count}"]')
    return '\n'.join(lines)
