"""
Layered containment model — the diagram's scene graph.

Built the way a diagram tool builds one: each layer is a *projection over its
parent*, never an independent list. A node stores a pointer to its container and
nothing else about it, so layer N is derived from layer N-1 at read time. Change
layer 1 - filter to one region, drop a VPC - and every layer below reflects it
with no invalidation step, because the lower layers were never materialised
separately in the first place.

Nesting order follows AWS's own architecture-diagram convention:

    L0 account
    L1 region
    L2 vpc          outer box; regional, spans zones
    L3 az           columns drawn INSIDE each vpc
    L4 subnet       the join: exactly one az and one vpc
    L5 workload     ec2, rds, lambda-in-vpc, ecs-task
    L6 attached     ebs, eni

Two consequences of that ordering worth stating plainly:

  * az nodes are scoped per-vpc (`az:vpc-1/apse1-a`), because that is what the
    diagram draws - each VPC gets its own column set. A region-level az node is
    used only for resources that sit in a zone without a VPC.
  * anything with no spatial position at all - iam, kms, s3, route53 - is not
    forced into the tree. It goes in an overlay bucket and is drawn as a
    floating group with edges into the tree.
"""

import csv
import os
from collections import defaultdict
from functools import lru_cache

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')

L_GLOBAL = -1          # outside the region: iam, route53, cloudfront
L_ACCOUNT, L_REGION, L_VPC, L_AZ, L_SUBNET, L_WORKLOAD, L_ATTACHED = range(7)
L_REGIONAL = 8         # in the region, beside the vpc: s3, dynamodb, kms

LAYER_NAMES = {
    L_GLOBAL: 'global', L_ACCOUNT: 'account', L_REGION: 'region',
    L_VPC: 'vpc', L_AZ: 'az', L_SUBNET: 'subnet', L_WORKLOAD: 'workload',
    L_ATTACHED: 'attached', L_REGIONAL: 'regional',
}

# catalog layer_id -> the spatial constant used inside the tree.
LAYER_ID = {
    'G0': L_GLOBAL, 'L0': L_ACCOUNT, 'L1': L_REGION, 'L2': L_VPC, 'L3': L_AZ,
    'L4': L_SUBNET, 'L5': L_WORKLOAD, 'L6': L_ATTACHED,
    'R1': L_REGIONAL, 'R2': L_REGIONAL, 'R3': L_REGIONAL,
}

# Layer membership is read from catalog/layer_assignment.csv, never restated
# here. It used to be hardcoded against c7n names ('iam-role', 'kms-key'); when
# the vocabulary moved to catalog slugs ('iam.role', 'kms.key') every set
# silently stopped matching and classification became a no-op that nothing
# caught. Data in the catalog cannot drift away from the catalog.
_LAYER_ID_TO_CONST = {
    'L0': L_ACCOUNT, 'L1': L_REGION, 'L2': L_VPC, 'L3': L_AZ,
    'L4': L_SUBNET, 'L5': L_WORKLOAD, 'L6': L_ATTACHED,
}

# Structural types define a layer rather than being placed in one. Both the
# catalog slug and the synthetic node type map to the same role, because
# _ensure_* mints 'vpc'/'az' nodes of its own alongside discovered 'ec2.vpc'.
STRUCTURAL_ROLE = {'ec2.vpc': 'vpc', 'vpc': 'vpc',
                   'ec2.subnet': 'subnet', 'subnet': 'subnet',
                   'az': 'az'}
STRUCTURAL = STRUCTURAL_ROLE


def structural_role(type_):
    """'vpc' | 'subnet' | 'az' | None for a resource type."""
    return STRUCTURAL_ROLE.get(type_)


@lru_cache(maxsize=1)
def load_assignment():
    """{resource_key: (layer_id, layer_name, kind)} from the catalog."""
    path = os.path.join(CATALOG, 'layer_assignment.csv')
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return {r['key']: (r['layer_id'], r['layer_name'], r['kind'],
                           r.get('overlay_group', ''))
                for r in csv.DictReader(fh)}


def overlay_for(resource_key):
    """
    The rendering group a type belongs to, or None.

    This is a TOGGLE, not a placement. Every real resource has a spatial home:
    a KMS key is in the region and is also tagged `encryption` so a renderer can
    hide it. Conflating the two is what previously drew S3 outside the region
    box entirely, because "has an overlay group" was read as "is not in the
    tree".
    """
    row = load_assignment().get(resource_key)
    return (row[3] or None) if row else None


def spatial_layer(resource_key):
    """The layer constant a type defaults to, or None when uncollectable."""
    row = load_assignment().get(resource_key)
    return LAYER_ID.get(row[0]) if row else None



def _load_detail_fields(path=None):
    """
    Which raw fields survive into the scene, per type.

    The raw response is kept on every asset and thrown away at the scene
    boundary, which is right - a scene carrying 4761 types' worth of API
    payloads is not a scene. But some fields ARE the answer: a security group
    rule without its ports is a row that says nothing, and an instance without
    its state is a box that might not exist.

    So: a catalog decides, not the renderer. Adding a field to a panel is a CSV
    row, which is the same rule the rest of this engine follows.
    """
    path = path or os.path.join(CATALOG, 'detail_fields.csv')
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            key, field = row.get('resource_key'), row.get('field')
            if key and field:
                out.setdefault(key, []).append(
                    (field, row.get('label') or field, row.get('type') or 'str'))
    return out


# The same coercion table `emit` uses, so one catalog has one meaning.
from providers.aws.runtime.emit import _COERCE  # noqa: E402

DETAIL_FIELDS = _load_detail_fields()


def _detail(node):
    """
    The declared fields for this node's type, read out of its raw payload.

    Coerced through the SAME table `emit` uses. Without that the catalog had
    two readers who disagreed: `emit` turned `ec2.volume.Attachments` into the
    boolean `attached` its `present` type asks for, while the scene passed the
    whole attachment list through and the panel printed a JSON blob in a cell.
    One catalog, one meaning.
    """
    wanted = DETAIL_FIELDS.get(node.type)
    if not wanted:
        return None
    out = {}
    for path, label, kind in wanted:
        value = node.raw
        for segment in path.split('.'):
            value = value.get(segment) if isinstance(value, dict) else None
            if value is None:
                break
        coerce = _COERCE.get(kind.strip(), _COERCE['str'])
        value = coerce(value)
        if value is not None and value != '':
            out[label] = value
    return out or None


class Node:
    """One element of the scene graph. Holds a parent KEY, never a parent copy."""

    __slots__ = ('key', 'type', 'id', 'name', 'arn', 'raw',
                 'parent', 'layer', 'overlay', 'zone', 'vpc', 'subnet',
                 'attached_to')

    def __init__(self, key, type_, id_, name=None, arn=None, raw=None):
        self.key = key
        self.type = type_
        self.id = id_
        self.name = name or id_
        self.arn = arn
        self.raw = raw or {}
        self.parent = None
        self.layer = None
        self.overlay = None
        self.zone = None
        self.vpc = None
        self.subnet = None
        self.attached_to = None

    def __repr__(self):
        return f'<Node {self.key} layer={self.layer}>'


def _load(name, key):
    path = os.path.join(CATALOG, name)
    if not os.path.exists(path):
        return {}
    return {r[key]: r for r in csv.DictReader(open(path))}


class LayerTree:
    """
    Containment tree plus overlay buckets, with cascading filters.

    Filters are stored per layer and evaluated on read: a node is visible only
    if every one of its ancestors is visible too. That is what makes a change at
    layer 1 propagate downward automatically - there is no second copy of the
    lower layers to keep in step.
    """

    def __init__(self, account_id, region, location_paths=None):
        self.account_id = account_id
        self.region = region
        self.locations = location_paths or _load('location_paths.csv', 'resource')
        self.nodes = {}
        self._children = defaultdict(list)
        self._filters = {}
        # Collected key -> the synthetic container key that stands for it.
        # A VPC arrives twice: as the collected `ec2.vpc:X` and as the `vpc:X`
        # node minted to hold its contents. Anything pointing at the collected
        # key must resolve to the container, or it hangs off a node that is in
        # `nodes` but in no child list - present, visible, and never drawn.
        self._alias = {}

        self.account_key = f'account:{account_id}'
        self.region_key = f'region:{account_id}/{region}'
        self._add(Node(self.account_key, 'account', account_id), None, L_ACCOUNT)
        self._add(Node(self.region_key, 'region', region), self.account_key, L_REGION)

    # ── construction ──────────────────────────────────────────────────

    def _add(self, node, parent_key, layer):
        node.parent = parent_key
        node.layer = layer
        self.nodes[node.key] = node
        if parent_key:
            self._children[parent_key].append(node.key)
        return node

    def _ensure(self, key, type_, id_, parent_key, layer):
        """
        Place a structural node, creating it if needed.

        Idempotent and order-independent: the node may already exist because the
        caller registered it via add_resource before its children arrived, in
        which case it exists but is unplaced. Both cases must end with it linked
        exactly once.
        """
        node = self.nodes.get(key)
        if node is None:
            node = Node(key, type_, id_)
        elif node.layer is not None:
            return key
        self._add(node, parent_key, layer)
        return key

    def _ensure_vpc(self, vpc_id):
        return self._ensure(f'vpc:{vpc_id}', 'vpc', vpc_id, self.region_key, L_VPC)

    def _ensure_az(self, zone, vpc_id=None):
        """
        AZ nodes are scoped to their VPC because that is how the diagram draws
        them - each VPC renders its own column per zone. Zone-without-VPC falls
        back to a region-scoped node.
        """
        if vpc_id:
            key = self._ensure(f'az:{vpc_id}/{zone}', 'az', zone,
                               self._ensure_vpc(vpc_id), L_AZ)
        else:
            key = self._ensure(f'az:{self.region}/{zone}', 'az', zone,
                               self.region_key, L_AZ)
        # Remember the scoping VPC: build() clears placement before re-running,
        # and without this a rebuild would rescope the zone to the region and
        # mint a second node for it.
        self.nodes[key].vpc = vpc_id
        return key

    def add_resource(self, type_, id_, name=None, arn=None, raw=None,
                     vpc=None, subnet=None, zone=None, attached_to=None):
        """
        Register a resource. Placement is deferred to build(): a subnet may
        arrive before the VPC that contains it, so parents are resolved only
        once every node is known.
        """
        node = Node(f'{type_}:{id_}', type_, id_, name, arn, raw)
        node.vpc, node.subnet = vpc, subnet
        node.attached_to = attached_to
        node.zone = zone or self._zone_from_raw(type_, raw)
        self.nodes[node.key] = node
        return node

    def _zone_from_raw(self, type_, raw):
        """Read the AZ out of a resource using its location_paths recipe."""
        if not raw:
            return None
        rule = self.locations.get(type_)
        if not rule or not rule.get('az_path'):
            return None
        from providers.aws.runtime.resolver import resolve_path
        found = resolve_path(raw, rule['az_path'])
        return found[0] if found else None

    def build(self):
        """Resolve every node's parent. Idempotent — safe to re-run after adds."""
        self._children.clear()
        self._alias.clear()
        for node in self.nodes.values():
            if node.type in ('account', 'region'):
                continue
            node.parent = node.layer = node.overlay = None

        # Re-link the two synthetic roots first.
        self.nodes[self.region_key].parent = self.account_key
        self._children[self.account_key].append(self.region_key)

        # Containers before their contents, so a subnet never has to invent the
        # VPC it names, and so every alias exists before anything can point at
        # one. Ranked by STRUCTURAL ROLE, not by raw type: `ec2.vpc` and `vpc`
        # are the same role, and ranking the collected slug alongside ordinary
        # resources let an internet gateway be placed before the alias for the
        # VPC it attaches to existed - which resolved differently depending on
        # dict order.
        # `key` breaks ties so placement order is a pure function of the data.
        # Without it, ties fell back to insertion order - the order the
        # collector happened to return - so which half of a mutual attachment
        # won could change between runs.
        rank = {'vpc': 0, 'az': 1, 'subnet': 2}
        for node in sorted(self.nodes.values(),
                           key=lambda n: (rank.get(structural_role(n.type), 3),
                                          n.key)):
            if node.type in ('account', 'region') or node.layer is not None:
                continue
            self._place(node)
        return self

    def _place(self, node):
        # The overlay group is recorded, never used to skip placement. Every
        # real resource has a spatial home; hiding it is the renderer's call.
        node.overlay = self._overlay_for(node.type)

        role = structural_role(node.type)
        if role == 'vpc':
            self._alias[node.key] = self._ensure_vpc(node.id)
            return
        if role == 'az':
            self._alias[node.key] = self._ensure_az(node.id, node.vpc)
            return

        if role == 'subnet':                         # subnet: az ∩ vpc
            node.parent = (self._ensure_az(node.zone, node.vpc) if node.zone
                           else self._ensure_vpc(node.vpc) if node.vpc
                           else self.region_key)
            node.layer = L_SUBNET
        elif node.attached_to and self._would_nest(
                node, self._alias.get(node.attached_to, node.attached_to)):
            # A volume or ENI belongs against the workload it is attached to,
            # not in the zone it happens to share with it. Without this the
            # attachment shows only as an arrow and the volume floats loose in
            # the availability zone.
            #
            # Resolved through the alias, because an internet gateway attaches
            # to the COLLECTED vpc key while the tree hangs everything off the
            # synthetic one. Pointing at the collected key put the gateway
            # under a node that is never drawn, so it vanished from the diagram
            # while still counting as visible.
            node.parent = self._alias.get(node.attached_to, node.attached_to)
            node.layer = L_ATTACHED
        elif node.subnet and self._subnet_key(node.subnet):
            node.parent = self._subnet_key(node.subnet)
            node.layer = L_WORKLOAD
        elif node.zone and node.vpc:
            # A zone is only a CONTAINER when it holds part of a network. For
            # anything outside one, the zone is a property of the resource, not
            # a place that can be drawn around it - an autoscaling group spans
            # zones, and a snapshot is a backup rather than something running
            # in one. Minting a box for those produced a second "ap-south-1b"
            # beside the VPC that already had one: same physical zone, two
            # boxes, and 12 database snapshots drawn as though they were
            # infrastructure sitting in an availability zone.
            node.parent = self._ensure_az(node.zone, node.vpc)
            node.layer = L_WORKLOAD
        elif node.vpc:
            node.parent = self._ensure_vpc(node.vpc)
            node.layer = L_WORKLOAD
        else:
            default = spatial_layer(node.type)
            if default == L_GLOBAL:
                # No region at all - iam, route53, cloudfront. Hangs off the
                # account, outside the region box.
                node.parent = self.account_key
                node.layer = L_GLOBAL
            else:
                # In the region but in no VPC: s3, dynamodb, kms, and any
                # Lambda whose payload carried no VpcConfig. Placement is per
                # ASSET, so two Lambdas can legitimately land in different
                # boxes depending on their own data.
                node.parent = self.region_key
                node.layer = L_REGIONAL if default is None else default

        self._children[node.parent].append(node.key)

    def _would_nest(self, node, parent_key):
        """
        Whether `node` can nest under `parent_key` without closing a loop.

        Attachment is reported per direction, and AWS reports both: a volume is
        attached-to its instance AND the instance carries the volume. Taking
        both literally makes each the other's parent, and the renderer then
        recurses between them forever - the scene builds fine and `to_dict()`
        never returns.

        Which half wins is decided by DEPTH, not by order. A volume's natural
        layer is deeper than an instance's, so a volume may nest into an
        instance and never the reverse. Breaking the tie on sort order instead
        put five instances inside their own root volume - stable, reproducible,
        and backwards.
        """
        if parent_key not in self.nodes:
            return False

        parent = self.nodes[parent_key]
        here, above = spatial_layer(node.type), spatial_layer(parent.type)
        # Only comparable within one axis. `R1` is 8 and `L6` is 6, but that 8
        # does not mean "deeper than a volume" - it means "not in the network
        # at all". Compared across axes it said an API Gateway is deeper than
        # its own stage, so three stages refused to nest in the API that owns
        # them and sat on a rail belonging to nothing. Across axes the cycle
        # check below is the real protection, and it is sufficient.
        same_axis = (here is not None and above is not None
                     and (here <= L_ATTACHED) == (above <= L_ATTACHED))
        if same_axis and above > here:
            return False
        seen, cur = set(), parent_key
        while cur is not None and cur not in seen:
            if cur == node.key:
                return False
            seen.add(cur)
            cur = self.nodes[cur].parent if cur in self.nodes else None
        return True

    def _subnet_key(self, subnet_id):
        """Find a registered subnet node by id, whatever type slug it carries."""
        for candidate in (f'ec2.subnet:{subnet_id}', f'subnet:{subnet_id}'):
            if candidate in self.nodes:
                return candidate
        return None

    @staticmethod
    def _overlay_for(type_):
        return overlay_for(type_)

    # ── cascade ───────────────────────────────────────────────────────

    def set_filter(self, layer, keys):
        """
        Restrict a layer to `keys`. Every deeper layer follows automatically,
        because visibility is evaluated by walking ancestors on read.
        Pass None to clear.
        """
        if keys is None:
            self._filters.pop(layer, None)
        else:
            self._filters[layer] = set(keys)
        return self

    def clear_filters(self):
        self._filters.clear()
        return self

    def is_visible(self, key):
        node = self.nodes.get(key)
        while node is not None:
            allowed = self._filters.get(node.layer)
            if allowed is not None and node.key not in allowed:
                return False
            node = self.nodes.get(node.parent) if node.parent else None
        return True

    def layer(self, n):
        """Visible nodes at layer n, honouring every ancestor filter."""
        return [nd for nd in self.nodes.values()
                if nd.layer == n and self.is_visible(nd.key)]

    def children(self, key):
        return [self.nodes[k] for k in self._children.get(key, [])
                if self.is_visible(k)]

    def subtree(self, key):
        """`key` plus every visible descendant — the cascade made explicit."""
        out, stack = [], [key]
        while stack:
            cur = stack.pop()
            if not self.is_visible(cur):
                continue
            out.append(self.nodes[cur])
            stack.extend(self._children.get(cur, []))
        return out

    def ancestors(self, key):
        out, node = [], self.nodes.get(key)
        while node is not None and node.parent:
            node = self.nodes.get(node.parent)
            if node is None:
                break
            out.append(node)
        return out

    def overlays(self):
        """
        Nodes grouped by rendering toggle.

        These are ALSO in the tree - the grouping exists so a renderer can hide
        identity or encryption without disturbing layout, not because the nodes
        live somewhere else.
        """
        buckets = defaultdict(list)
        for nd in self.nodes.values():
            if nd.overlay and self.is_visible(nd.key):
                buckets[nd.overlay].append(nd)
        return dict(buckets)

    # ── output ────────────────────────────────────────────────────────

    def to_dict(self, positions=None, order_by=None):
        """
        Render payload: nested tree plus overlay buckets.

        `positions` maps node key -> a placement object with `.to_dict()`, and
        `order_by(node, position)` is the sort rule siblings are drawn in. Both
        are optional so the tree stays usable without a layout pass - but when
        they are supplied, children are emitted in POSITION order rather than
        insertion order, which is the difference between a diagram that is
        stable across runs and one that reshuffles whenever the collector does.
        """
        positions = positions or {}

        def ordered(key):
            kids = [c for c in self._children.get(key, []) if self.is_visible(c)]
            if not (positions and order_by):
                return kids
            # Anything without a position sorts last, keyed by its own name, so
            # an unplaced node is visible and stable rather than dropped.
            return sorted(kids, key=lambda c: (
                order_by(self.nodes[c], positions[c]) if c in positions
                else (999, '', self.nodes[c].name or '', self.nodes[c].id or '')))

        def pack(key, seen=frozenset()):
            # Belt and braces against a containment loop. `_would_nest` stops
            # one being built, but a cycle here costs an unkillable hang rather
            # than a wrong diagram, and that is not a failure mode worth
            # leaving to a single guard upstream.
            if key in seen:
                return None
            seen = seen | {key}
            nd = self.nodes[key]
            out = {
                'key': nd.key, 'type': nd.type, 'id': nd.id, 'name': nd.name,
                'arn': nd.arn, 'layer': nd.layer,
                'layer_name': LAYER_NAMES.get(nd.layer),
                'overlay': nd.overlay,
                'children': [c for c in (pack(k, seen) for k in ordered(key))
                             if c is not None],
            }
            detail = _detail(nd)
            if detail:
                out['detail'] = detail
            placement = positions.get(key)
            if placement is not None:
                out['position'] = placement.to_dict()
            return out
        return {
            'account': self.account_id,
            'region': self.region,
            'tree': pack(self.account_key) if self.is_visible(self.account_key) else None,
            'overlays': {
                bucket: [{'key': n.key, 'type': n.type, 'id': n.id,
                          'name': n.name, 'arn': n.arn,
                          'layer': n.layer,
                          'layer_name': LAYER_NAMES.get(n.layer)} for n in nodes]
                for bucket, nodes in self.overlays().items()
            },
            'counts': {LAYER_NAMES[n]: len(self.layer(n)) for n in LAYER_NAMES},
        }
