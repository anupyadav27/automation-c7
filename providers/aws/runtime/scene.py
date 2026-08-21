"""
Assets + edges -> scene graph.

The transform is one rule:

    containment edges become NESTING.  everything else becomes an ARROW.

A `contained-in` edge is not drawn as a line - it decides which box a node sits
inside. `protected-by`, `encrypted-by`, `assumes` and the rest have no spatial
meaning, so they stay as lines between boxes and can be toggled per overlay.
That single distinction is what turns a flat edge list into a diagram instead of
a hairball.

Placement is derived from the edges themselves, not passed in. An instance is in
a subnet because a validated `contained-in` edge says so, so the diagram is a
rendering of the relation data rather than a second, hand-maintained copy of it.

The output is renderer-agnostic: a nesting tree, overlay buckets, and a list of
arrows. `render/mermaid.py` and `render/graphviz.py` are thin adapters over it,
and a UI can consume the JSON directly.
"""

import csv
import os
import re
from collections import defaultdict

from providers.aws.runtime.layers import LayerTree, LAYER_NAMES, _detail
from providers.common.topology.layout import (
    layout, load_binding, load_model, sort_key,
)

# States that mean "attached to nothing", said by the resource about itself.
# An interface or volume in one of these is correctly on the border; anything
# else that lands there lost its owner edge somewhere.
_DETACHED_STATES = frozenset({'available', 'detached', 'unattached', 'free'})

# An interface whose attachment owner is not us is a managed service's
# footprint in our subnet, not a free-floating interface and not a missing
# edge. AWS says so two ways: a service name (`amazon-elb`, `amazon-rds`,
# `amazon-aws`) or a different account id - EKS control-plane interfaces are
# owned by 553894343830, which is AWS, not a customer. Ten of the fifteen
# apparent orphans in this estate were one of these two.
_SERVICE_OWNERS = ('amazon-', 'aws-')

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')

# Placement rules live in the provider-neutral model; this file only says which
# AWS types play which role. See providers/common/topology/model.yaml.
BINDING = os.path.join(CATALOG, 'topology_binding.yaml')

# Edges that place a node rather than connect it.
CONTAINMENT = 'contained-in'
ATTACHMENT = 'attached-to'

# ── identity AWS owns, rather than identity we run ────────────────────
#
# Three things in an account's IAM are not the account's own work, and the ARN
# says which without a second API call:
#
#   arn:aws:iam::aws:policy/...              a managed policy AWS authors
#   .../role/aws-service-role/...            a service-linked role AWS creates
#   .../role/aws-reserved/sso.amazonaws.com  a role Identity Center creates
#
# They are real and they are not noise — but an access review asks "what have
# we granted", and a rail listing AWS's own catalogue alongside our roles
# answers a different question at the same volume. So they are kept only when
# something in the estate actually uses them.
_AWS_OWNED_IAM = re.compile(
    r'^arn:[^:]*:iam::aws:'
    r'|^arn:[^:]*:iam::\d+:role/aws-service-role/'
    r'|^arn:[^:]*:iam::\d+:role/aws-reserved/'
)

# An attachment record IS a statement of use — `role X has policy Y` — so it
# can never be dropped for being unused. Reading these as ordinary AWS-managed
# policies would have deleted the only evidence that the managed policies we DO
# rely on are attached to anything.
_ATTACHMENT_RECORDS = frozenset({
    'iam.attached_role_policy',
    'iam.attached_user_policy',
    'iam.attached_group_policy',
})


def prune_unused_aws_identity(assets, edges):
    """
    Drop identity AWS owns and nothing in this estate refers to.

    Kept, in every case:
      · anything we created, wherever it sits — including console-made roles
        under `/service-role/`, which are ours the moment we accept them
      · any attachment record, because its existence is the use
      · any AWS-owned role or policy something in the estate points at

    Dropped: the remainder — AWS's catalogue, present in every account and
    telling you nothing about this one.

    Pure, and returns a new list, so a caller can diff what it removed.
    """
    used = set()
    for edge in edges:
        used.add(edge.get('source_asset_id'))
        used.add(edge.get('target_asset_id'))

    def keep(asset):
        arn = asset.get('arn') or ''
        if not _AWS_OWNED_IAM.match(arn):
            return True
        if asset.get('resource_key') in _ATTACHMENT_RECORDS:
            return True
        return asset.get('asset_id') in used

    return [a for a in assets if keep(a)]


def _load(name, key):
    path = os.path.join(CATALOG, name)
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return {r[key]: r for r in csv.DictReader(fh)}


class Scene:
    """A built scene graph, queryable and renderable."""

    def __init__(self, tree, assets, edges, meta, relations=None):
        self.tree = tree
        self.assets = assets          # asset_id -> asset dict
        self.edges = edges            # arrows the canvas draws
        # Every edge, including the containment and attachment ones the canvas
        # expresses as nesting instead. A panel needs them: nesting tells you a
        # listener sits under its load balancer only if you are looking at the
        # load balancer.
        self.relations = relations if relations is not None else edges
        self.meta = meta
        self._positions = None        # computed lazily; see positions()

    # ── filtering, delegated to the tree so the cascade is free ───────

    def filter_layer(self, layer, keys):
        self.tree.set_filter(layer, keys)
        return self

    def clear_filters(self):
        self.tree.clear_filters()
        return self

    def visible_edges(self):
        """
        Arrows whose endpoints are both visible.

        Filtering is expressed once, on the tree; edges inherit it rather than
        carrying their own filter state, so an edge can never survive a filter
        that removed the node it points at.
        """
        out = []
        for edge in self.edges:
            src, tgt = edge['source_key'], edge['target_key']
            src_ok = src not in self.tree.nodes or self.tree.is_visible(src)
            tgt_ok = tgt not in self.tree.nodes or self.tree.is_visible(tgt)
            if src_ok and tgt_ok:
                out.append(edge)
        return out

    # ── placement ─────────────────────────────────────────────────────

    def positions(self):
        """
        Where every node draws, from the universal topology model.

        Computed here rather than in the renderer because placement needs the
        resources' RAW payloads - a gateway endpoint and an interface endpoint
        are the same type in different places, and only the payload says which.
        `to_dict()` does not carry raw, so a renderer physically cannot make
        that call correctly.
        """
        if self._positions is None:
            # Only nodes the tree actually PLACED. A structural resource is
            # registered under its collected key and again under the synthetic
            # container key the tree mints for it, and the collected one is left
            # orphaned - present in `nodes`, absent from every child list, never
            # drawn. Handing those to layout would place three VPCs as six.
            placed = self._reachable()
            self._positions = layout(
                {k: n for k, n in self.tree.nodes.items() if k in placed},
                self.tree._children, self.edges, load_binding(BINDING))
        return self._positions

    def _reachable(self):
        """Keys reachable from the account root — exactly what to_dict emits."""
        seen, stack = set(), [self.tree.account_key]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            stack.extend(self.tree._children.get(key, []))
        return seen

    def to_dict(self):
        positions = self.positions()
        doc = self.tree.to_dict(positions=positions, order_by=sort_key)
        doc['meta'] = self.meta
        doc['edges'] = self.visible_edges()
        doc['meta']['visible_edges'] = len(doc['edges'])
        # Unfiltered on purpose. Visibility is a statement about the CANVAS -
        # a collapsed group or an active filter hides an arrow - and it must
        # not decide what a panel knows about the resource you just clicked.
        doc['relations'] = self.relations
        doc['meta']['relations'] = len(self.relations)
        # Which border orders its doors centre-out, from the model rather than
        # from a prop the renderer sets by hand. `edge_order.centre_out` was
        # declared and never read, so the model said one thing and the view
        # decided another - they agreed, but only by coincidence.
        doc['meta']['centre_out'] = (load_model().get('edge_order') or {}).get(
            'centre_out', [])


        # A component of nothing is usually a defect and occasionally the
        # truth, and the two must not be reported as one number.
        #
        # A resource's own data settles it: an interface whose status is
        # `in-use` IS attached to something, so having no host means the owner
        # edge was never collected - that is a defect. An interface whose
        # status is `available` is attached to nothing, so the border is
        # exactly where it belongs, and it is a cost finding rather than a
        # collection bug. Twelve of thirteen were the first kind.
        detached, unclaimed, footprints = [], [], []
        for key, pos in positions.items():
            if pos.kind != 'part' or not pos.dangling:
                continue
            node = self.tree.nodes.get(key)
            detail = _detail(node) or {} if node else {}
            state = str(detail.get('status', '')).lower()
            owner = str(detail.get('attachment_owner', ''))
            foreign = bool(owner) and owner != str(self.meta.get('account_id', ''))
            if owner.startswith(_SERVICE_OWNERS) or foreign:
                footprints.append(key)
            elif state in _DETACHED_STATES:
                unclaimed.append(key)
            else:
                detached.append(key)

        doc['meta']['orphan_components'] = len(detached)
        doc['meta']['orphan_component_keys'] = sorted(detached)[:50]
        # Neither of these is a defect, and both were being counted as one.
        doc['meta']['unattached_components'] = len(unclaimed)
        doc['meta']['unattached_component_keys'] = sorted(unclaimed)[:50]
        doc['meta']['service_footprints'] = len(footprints)
        doc['meta']['service_footprint_keys'] = sorted(footprints)[:50]
        return doc


def build_scene(assets, edges, account_id, region, account_name=None,
                layer_assignment=None, location_paths=None):
    """
    Turn collected assets and validated edges into a scene graph.

    `assets` are dicts with at least asset_id, resource_key, id; optionally
    name, arn, availability_zone. `edges` are dicts with source_asset_id,
    target_asset_id, edge_type.
    """
    layers = layer_assignment or _load('layer_assignment.csv', 'key')
    # Before anything is placed: AWS's own identity catalogue is not this
    # account's architecture unless this account uses it.
    assets = prune_unused_aws_identity(assets, edges)
    by_id = {a['asset_id']: a for a in assets}

    # ── 1. containment edges decide placement ─────────────────────────
    # Read them first so every node knows its vpc/subnet before the tree is
    # built; the tree resolves parents in one pass afterwards.
    parent_of = {}
    for edge in edges:
        target = by_id.get(edge['target_asset_id'])
        if not target:
            continue
        kind = edge.get('edge_type')
        if kind == CONTAINMENT:
            role = target['resource_key']
            slot = ('vpc' if role.endswith('.vpc')
                    else 'subnet' if role.endswith('.subnet') else None)
            if slot:
                parent_of.setdefault(edge['source_asset_id'], {})[slot] = target['id']
        elif kind == ATTACHMENT:
            # Attachment is placement too: a volume nests under its instance
            # rather than floating in the zone they share.
            parent_of.setdefault(edge['source_asset_id'], {})['attached_to'] = (
                f"{target['resource_key']}:{target['id']}")

    # Some children have no edge to their parent because their payload never
    # names it: an API Gateway stage is returned per-API and says nothing about
    # which API it came from. The collector knew - it passed the ApiId - and
    # recorded it as `parent_asset_id`. That is an attachment like any other,
    # and without it three stages sat on a rail belonging to nothing.
    for asset in assets:
        parent = by_id.get(asset.get('parent_asset_id') or '')
        if parent and 'attached_to' not in parent_of.get(asset['asset_id'], {}):
            parent_of.setdefault(asset['asset_id'], {})['attached_to'] = (
                f"{parent['resource_key']}:{parent['id']}")

    # ── 2. build the nesting tree ─────────────────────────────────────
    tree = LayerTree(account_id, region, location_paths=location_paths)
    seen_ids = set()
    for asset in assets:
        placement = parent_of.get(asset['asset_id'], {})
        # The tree keys on `type:id`, and some ids are unique only within their
        # parent: two API gateways each have a stage called `$default`, and they
        # collapsed onto one node - two real resources drawn as one, silently.
        # The asset_id is already unique, so it settles the collision without
        # making every other key uglier.
        node_id = asset['id']
        if (asset['resource_key'], node_id) in seen_ids:
            node_id = asset['asset_id']
        seen_ids.add((asset['resource_key'], asset['id']))
        node = tree.add_resource(
            asset['resource_key'], node_id,
            name=asset.get('name') or asset['id'],
            arn=asset.get('arn'),
            raw=asset.get('raw') or {},
            vpc=placement.get('vpc'),
            subnet=placement.get('subnet'),
            zone=asset.get('availability_zone'),
            attached_to=placement.get('attached_to'),
        )
        # The tree keys nodes by type:id; remember the asset_id so edges can be
        # translated between the two identifier spaces.
        asset['_node_key'] = node.key
    tree.build()

    node_key = {a['asset_id']: a['_node_key'] for a in assets if '_node_key' in a}

    # ── 3. everything else becomes an arrow ───────────────────────────
    #
    # Two lists, because they answer two questions. `arrows` is what the canvas
    # DRAWS, so containment and attachment are dropped - the diagram already
    # says them by nesting one box inside another. `relations` is what a PANEL
    # reads, and there they matter: a listener's own panel has to name the load
    # balancer it is attached to, and nesting only tells you that if you happen
    # to be looking at the parent. Filtering the panel through the canvas's
    # list left 2 listeners, 16 volumes and 47 interfaces reporting no
    # relationships at all.
    arrows, relations = [], []
    for edge in edges:
        src = node_key.get(edge['source_asset_id'])
        tgt = node_key.get(edge['target_asset_id'])
        if not src:
            continue
        target_asset = by_id.get(edge['target_asset_id'])
        row = {
            'source_key': src,
            'target_key': tgt or edge['target_asset_id'],
            'source_asset_id': edge['source_asset_id'],
            'target_asset_id': edge['target_asset_id'],
            'edge_type': edge.get('edge_type', 'references'),
            'layer': (layers.get(target_asset['resource_key'], {}).get('layer_id', '')
                      if target_asset else ''),
            'overlay': (layers.get(target_asset['resource_key'], {}).get('layer_name', '')
                        if target_asset else ''),
            'verdict': edge.get('verdict', ''),
            'attributes': edge.get('attributes', {}),
            # Provenance travels with the edge. Without it every row in a
            # detail table looks equally certain, and a human-verified c7n path
            # and a mined inference are not the same claim.
            'mechanism': edge.get('mechanism', ''),
            'confidence': edge.get('confidence', ''),
            'via': edge.get('via', ''),
            'value': edge.get('value', ''),
            # How many independent paths found this same relationship. Several
            # paths agreeing is evidence the edge is real, and it is the only
            # thing that survives the collapse of duplicate rows.
            'corroborations': edge.get('corroborations', 1),
            # An edge pointing outside the collected set is kept and marked, not
            # dropped: a reference to something we did not collect is a finding.
            'external': target_asset is None,
        }
        relations.append(row)
        if edge.get('edge_type') not in (CONTAINMENT, ATTACHMENT):
            arrows.append(row)

    counts = defaultdict(int)
    for asset in assets:
        counts[asset['resource_key']] += 1

    meta = {
        'account_id': account_id,
        'account_name': account_name or account_id,
        'region': region,
        'assets': len(assets),
        'edges': len(arrows),
        'containment_edges': sum(1 for e in edges if e.get('edge_type') == CONTAINMENT),
        'external_edges': sum(1 for a in arrows if a['external']),
        'by_type': dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }
    return Scene(tree, by_id, arrows, meta, relations=relations)
