"""
Placement — where a node draws inside the container that holds it.

This is deliberately NOT the containment tree. A provider's tree module already
answers "what contains what"; this answers the four questions it does not:

    in what ORDER do siblings appear?
    along which AXIS - stacked, or side by side?
    WHERE relative to the container border - inside, on it, or on a rail?
    which nodes are ONE unit?

Keeping them apart is the whole design. Layout never moves a node between
containers, so it cannot corrupt containment, and a containment bug can never be
blamed on layout. It is a decoration pass: in, tree; out, one Position per node.

Provider-neutral by construction. Every rule lives in
`providers/common/topology/model.yaml` in terms of ROLES; each cloud ships a
binding saying which of its types play which role. No provider type name appears
in this file, and if one ever does, the next cloud will need a fork.

The ordering rule that makes regeneration byte-identical:

    sort by (rank, service, name, id) - never count, never insertion order.

`id` is unique, so the key is total and ties are impossible.
"""

import os
import re
from collections import defaultdict
from functools import lru_cache

import yaml

HERE = os.path.dirname(__file__)
MODEL_PATH = os.path.join(HERE, 'model.yaml')

# Roles that place a node on a border rather than inside the container. Kept
# here rather than inferred from the string so a typo in a binding fails loudly
# instead of silently becoming an anchor.
_BORDER = ('edge.', 'rail.')


class Position:
    """Where one node draws. Every field is derived; none is authored."""

    __slots__ = ('role', 'band', 'lane', 'rank', 'anchor', 'cluster',
                 'span', 'tier', 'order', 'entry', 'derived',
                 'kind', 'edge_rank', 'hoist_to', 'dangling', 'exposure',
                 'category', 'subcategory', 'sub_rank', 'drawn', 'wrap',
                 'lane_rank', 'slot', 'slot_along', 'slot_layers', 'rollup',
                 'edge_align')

    def __init__(self, role=None, band=None, lane=None, rank=999,
                 anchor='in', cluster=None, span=None, tier=None):
        self.role = role
        self.band = band
        self.lane = lane
        self.rank = rank
        self.anchor = anchor
        self.cluster = cluster
        self.span = span or []
        self.tier = tier
        self.kind = None       # boundary|resident|part|door|rule|record
        self.exposure = None    # 1..4 hops from the internet; None off the path
        self.lane_rank = 0      # order among lanes INSIDE a band
        self.slot = None        # which rail slot, for a rule on a border
        self.slot_along = None  # start | middle | end, along that arm
        self.slot_layers = 1    # how deep that slot may stack
        self.rollup = None      # several domains shown as one tab
        self.sub_rank = 999     # order among subcategories sharing one slot
        self.drawn = True       # False for records - they live in a panel
        self.wrap = None        # a rule may be drawn AS a box round its members
        self.edge_rank = 50     # position along a border; lower is more central
        # Which END of that border. `edge_rank` orders things ALONG an arm and
        # says nothing about where the run starts, so every strip has always
        # begun at the same place. A door that belongs at the right-hand end of
        # a wide border - a CDN on an account's top line - had no way to say so.
        self.edge_align = 'centre'   # left | centre | right
        self.hoist_to = None    # container this binding's border belongs to
        self.dangling = False   # a one-to-one attachment that found no host
        # What KIND of service this is - independent of where it draws. A
        # security group is a binding on the network's rail AND a
        # network.firewall service; neither fact follows from the other.
        self.category = None
        self.subcategory = None
        self.order = 0          # index after empty bands collapse (§5)
        self.entry = False      # the diagram's front door, if this won it
        self.derived = True     # False when we had to assume rather than derive

    def to_dict(self):
        d = {'role': self.role, 'band': self.band, 'lane': self.lane,
             'rank': self.rank, 'anchor': self.anchor, 'order': self.order}
        # Only emit the optional facts when they hold, so a scene.json diff
        # shows real changes rather than a wall of nulls.
        if self.cluster:
            d['cluster'] = self.cluster
        if self.span:
            d['span'] = self.span
        if self.tier:
            d['tier'] = self.tier
        if self.entry:
            d['entry'] = True
        if not self.derived:
            d['assumed'] = True
        if self.kind:
            d['kind'] = self.kind
        if self.exposure:
            d['exposure'] = self.exposure
        if self.wrap:
            d['wrap'] = self.wrap
        if not self.drawn:
            # Stated by the engine rather than inferred by the view. The model
            # said `render: detail` for months and no code read it, so the
            # renderer decided for itself and the two only agreed by luck.
            d['drawn'] = False
        if self.anchor.startswith('edge.'):
            d['edge_rank'] = self.edge_rank
            d['edge_align'] = self.edge_align
        if self.slot:
            d['slot'] = self.slot
            d['slot_along'] = self.slot_along
            d['slot_layers'] = self.slot_layers
        if self.rollup:
            d['rollup'] = self.rollup
        if self.hoist_to:
            d['hoist_to'] = self.hoist_to
        if self.dangling:
            d['dangling'] = True
        if self.category:
            d['category'] = self.category
            d['subcategory'] = self.subcategory
            # The ORDER of the two axes, not just their names. `sub_rank` comes
            # from taxonomy_ranks() and `lane_rank` from the model's lane list,
            # and both were computed here and thrown away at the boundary - so
            # the view received `datastore` and `object` with nothing saying
            # which came first, and fell back to sorting by the alphabet of
            # whatever the first member happened to be called.
            #
            # That is the same defect as `render: detail` above, and as
            # `edge_order.centre_out`, and as `categories.wrap`: a fact the
            # engine knows, does not say, and the renderer then guesses.
            d['sub_rank'] = self.sub_rank
            d['lane_rank'] = self.lane_rank
        return d

    def __repr__(self):
        return (f'<Position {self.role} band={self.band} lane={self.lane} '
                f'rank={self.rank} anchor={self.anchor}>')


# ── catalog loading ───────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_model(path=MODEL_PATH):
    with open(path) as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=8)
def load_binding(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def _role_table(path=MODEL_PATH):
    """
    role -> {band, lane, rank, anchor, container, spans, collapsed}

    Flattens two sections of the model into one lookup: `roles`, and the
    application-plane `categories`, which are lanes inside the role
    `resident.regional` rather than roles in their own right. A binding names
    either kind and does not need to know the difference.
    """
    model = load_model(path)
    table = {}

    for role, spec in (model.get('roles') or {}).items():
        spec = spec or {}
        anchor = spec.get('anchor', 'in')
        table[role] = {
            'band': spec.get('band'),
            'lane': None,
            'rank': spec.get('rank', 999),
            'anchor': anchor,
            'container': spec.get('container'),
            'spans': spec.get('spans'),
            'collapsed': bool(spec.get('collapsed')),
            'kind': spec.get('kind'),
            'exposure': spec.get('exposure'),
            'drawn': spec.get('render') != 'detail',
            'edge_rank': spec.get('edge_rank', 50),
            'edge_align': spec.get('edge_align', 'centre'),
            'cardinality': spec.get('cardinality'),
        }

    plane = table.get('resident.regional', {})
    for lane in ((model.get('categories') or {}).get('lanes') or []):
        table[lane['role']] = {
            'band': plane.get('band', 'services'),
            'lane': lane['role'],
            # The BAND's rank, so a lane never sorts against another band.
            'rank': plane.get('rank', 999),
            'lane_rank': lane.get('rank', 999),
            'anchor': 'in',
            'container': plane.get('container', 'region'),
            'spans': None,
            'collapsed': False,
            'kind': 'resident',
            'drawn': True,
            # A category lane is a subdivision of resident.regional, so it
            # inherits that band's distance from the internet unless it states
            # its own - an API gateway is an entry point wherever it draws.
            'exposure': lane.get('exposure', plane.get('exposure')),
            'edge_rank': 50,
            'edge_align': 'centre',
            'cardinality': None,
        }

    # `part` is declared in the model like every other role, so nothing is
    # patched in here. Its rank still comes from the binding's attachment_order,
    # resolved per node, because which part sorts first is a provider question.
    return table


# ── small helpers, deliberately provider-agnostic ─────────────────────

def _dig(raw, path):
    """Read a dotted path out of a payload. Returns None when any hop misses."""
    cur = raw
    for part in path.split('.'):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _tags(raw):
    """
    Normalise tags to {key: value}.

    Clouds disagree on the shape - a list of {Key, Value} pairs, or a plain
    map - and ownership claims are expressed in tags, so this has to handle
    both or clustering only works on one provider.
    """
    tags = raw.get('Tags') or raw.get('tags') or raw.get('TagList') or []
    if isinstance(tags, dict):
        return {str(k): str(v) for k, v in tags.items()}
    out = {}
    for item in tags or []:
        if isinstance(item, dict):
            key = item.get('Key') or item.get('key') or item.get('name')
            if key:
                out[str(key)] = str(item.get('Value') or item.get('value') or '')
    return out


def _service(type_):
    return type_.split('.', 1)[0] if '.' in type_ else type_


def _spine_roles(nodes, binding):
    """
    node key -> spine role ('network', 'zone', 'segment', ...).

    Derived from the binding rather than read off the node, because a tree's
    Node uses __slots__ and cannot be tagged, and because the spine is exactly
    the thing that differs per cloud. A provider lists both its real type slug
    and any synthetic one its tree mints for the same role.
    """
    by_type = {}
    for role, spec in (binding.get('spine') or {}).items():
        for type_ in (spec or {}).get('types') or []:
            by_type[type_] = role
    return {n.key: by_type[n.type] for n in nodes.values() if n.type in by_type}


def sort_key(node, pos):
    """
    The one ordering rule: (rank, lane_rank, sub_rank, service, name, id).

    `lane_rank` orders lanes WITHIN a band and must never be compared across
    bands. It used to be written straight into `rank`, so a lane rank of 10
    (`resident.api`) sorted above the network band's rank of 20 and the region's
    regional services interleaved with the VPC instead of forming a block
    beneath it.

    `sub_rank` comes after because several subcategories routinely share
    one rank - thirteen of them ride the region's north rail - and without it the
    tie-break was alphabetical by service, which is not an order anyone chose.

    Public because a renderer has to order siblings the same way the engine did,
    and two copies of this rule would eventually disagree. Never count, never
    insertion order, never a hash. `id` is unique, so the key is total and ties
    are impossible - which is what makes regeneration byte-identical.
    """
    return (pos.rank, pos.lane_rank, pos.sub_rank, _service(node.type),
            (node.name or ''), node.id or '')


# ── stage 3: CLASSIFY — resolve a type to a role ──────────────────────

def taxonomy_ranks(model):
    """
    `category.subcategory` -> a sortable rank, from the order the model lists.

    No new numbers to author: the sequence someone wrote the taxonomy in IS the
    sequence it draws in. Category first so all of `security` stays together,
    then position within it, so `security.identity` precedes
    `security.posture` because that is how they are written.

    Exists because the taxonomy was the ONE axis in this model with no ordering
    at all - bands have `band_rank`, lanes have `rank`, doors have `edge_rank`,
    exposure is 1..4 - and thirteen subcategories sharing a rail therefore fell
    back to alphabetical by service name.
    """
    out = {}
    for c_index, (category, subs) in enumerate((model.get('taxonomy') or {}).items()):
        for s_index, sub in enumerate(subs):
            out[f'{category}.{sub}'] = (c_index + 1) * 100 + (s_index + 1) * 10
    return out


def resolve_slot(category, subcategory, model):
    """
    Which rail slot a supporting domain draws in.

    A `category.subcategory` key wins over a bare `category` key, so a category
    can send most of itself to one slot and split out the parts that behave
    differently — `security` does exactly that: access control on the east wall,
    monitoring down on the south line with governance.

    Returns (slot_name, arm, along, layers), or None when the model declares no
    slots at all, in which case the caller keeps whatever the role said.
    """
    cfg = model.get('rail_slots') or {}
    slots = cfg.get('slots') or {}
    if not slots:
        return None
    mapping = cfg.get('of') or {}
    name = (mapping.get(f'{category}.{subcategory}')
            or mapping.get(category)
            or cfg.get('default'))
    spec = slots.get(name)
    if not spec:
        return None
    return name, spec['arm'], spec.get('along', 'middle'), spec.get('layers', 1)


def resolve_taxonomy(type_, binding):
    """
    `category.subcategory` for a type, or None.

    Exact type first, then the service segment - one service routinely spans
    slots. `ec2` alone covers instances, block storage, firewall and routing,
    and collapsing all four into one row is what made a filter useless.
    """
    slot = ((binding.get('taxonomy_types') or {}).get(type_)
            or (binding.get('taxonomy') or {}).get(_service(type_)))
    if not slot or '.' not in slot:
        return None, None
    category, sub = slot.split('.', 1)
    return category, sub


def resolve_role(type_, raw, binding):
    """
    Role for one resource, by the binding's documented precedence:

        discriminators -> overrides -> services -> None

    Discriminators come first because the resource's own DATA beats a lookup
    table: two functions of the same type legitimately land in different boxes
    depending on whether their payload carried a network config. A lookup table
    cannot express that, and guessing one answer for both is how a diagram
    starts lying.
    """
    raw = raw or {}

    disc = (binding.get('discriminators') or {}).get(type_)
    if disc:
        value = _dig(raw, disc['field']) if disc.get('field') else None
        cases = disc.get('cases') or {}
        if isinstance(value, list):
            for item in value:
                if item in cases:
                    return cases[item]
            if value and 'non_empty' in cases:
                return cases['non_empty']
        elif value is not None:
            if value in cases:
                return cases[value]
            if 'non_empty' in cases and value:
                return cases['non_empty']
        if disc.get('default'):
            return disc['default']

    override = (binding.get('overrides') or {}).get(type_)
    if override:
        return override

    # What the name says it is, before what its service usually is. A snapshot
    # is a snapshot whichever database took it.
    for rule in (binding.get('suffixes') or []):
        if re.search(rule['match'], type_):
            return rule['role']

    return (binding.get('services') or {}).get(_service(type_))


def _is_entry_candidate(type_, raw, binding):
    """Whether this resource satisfies its binding's `entry_when` condition."""
    disc = (binding.get('discriminators') or {}).get(type_) or {}
    cond = disc.get('entry_when')
    if not cond:
        return False
    for field, expected in cond.items():
        value = _dig(raw or {}, field)
        if isinstance(expected, str) and expected.startswith('not '):
            if value == expected[4:]:
                return False
        elif expected == 'present':
            if not value:
                return False
        elif isinstance(value, list):
            if expected not in value:
                return False
        elif value != expected:
            return False
    return True


# ── stage 2: CLUSTER — ownership, with a fixed precedence ─────────────

# Edge types that mean "this node is governed by that rule". A rule can only
# be drawn AS a box round things it actually governs, and only these say so -
# `references` and `contained-in` say something else entirely.
GOVERNED_BY = frozenset({'protected-by', 'encrypted-by', 'accessible-by',
                         'constrained-by', 'routes-through'})


def _resolve_wraps(nodes, positions, edges, parent_of):
    """
    rule key -> the container it may be drawn AS a box around.

    A security group is conventionally drawn as a dashed box enclosing what it
    protects - it is how AWS's own icon set ships it, as a GROUP icon rather
    than a symbol. That only works when the members sit together: 27 of this
    estate's 31 security groups govern things inside a single container, and 4
    span between two and seven.

    So the data decides per rule. Contiguous, it wraps; scattered, it stays a
    chip on the scope rail, because a box drawn round members in seven
    different subnets would have to cross their borders to do it and would
    claim a containment that runs the wrong way.

    A member already inside a cluster box is left alone - see the cap in
    layout(): one wrap round a resident is a diagram, two is a maze.
    """
    members = defaultdict(set)
    for edge in edges:
        if edge.get('edge_type') not in GOVERNED_BY:
            continue
        source, target = edge.get('source_key'), edge.get('target_key')
        if target not in positions or positions[target].kind != 'rule':
            continue
        member = positions.get(source)
        # Only things that are DRAWN can be inside a drawn box. A security
        # group's `protected-by` edges come mostly from its own rules, which
        # are records living in a panel - counting them measured "all my rules
        # are in the region", which is true of every group and informative
        # about none.
        if member is not None and member.drawn and member.kind in ('resident', 'part'):
            members[target].add(source)

    wraps = {}
    for rule_key, member_keys in members.items():
        # A box round ONE thing is not a box, it is a tag — and that resource
        # already carries the rule's short code. A KMS key encrypting a single
        # database drew a frame around it saying "protects 1", next to a
        # `kms-1` chip on the database saying the same thing.
        if len(member_keys) < 2:
            continue
        containers = {parent_of.get(k) for k in member_keys}
        containers.discard(None)
        if len(containers) != 1:
            continue
        container = containers.pop()
        # The box has to be TIGHTER than where the rule already rides, or it
        # says nothing. A KMS key on the region rail whose members are all in
        # that region is contiguous and completely uninformative - eight of
        # them would draw eight boxes round the whole region. A security group
        # on the VPC rail whose members are all in one subnet is the case worth
        # drawing.
        scope = positions[rule_key].hoist_to or parent_of.get(rule_key)
        if container == scope:
            continue
        wraps[rule_key] = container
    return wraps


def _resolve_clusters(nodes, edges, binding, model):
    """
    node key -> owning cluster key.

    A workload can satisfy several claims at once - a Kubernetes node is also in
    an autoscaling group - so precedence is read from the MODEL and applied in
    order. Without it the winner depends on dict iteration and the diagram flips
    between runs for no reason.
    """
    specs = binding.get('clusters') or {}
    precedence = model.get('cluster_precedence') or list(specs)

    owners = defaultdict(list)          # owner type -> [node keys]
    for node in nodes.values():
        owners[node.type].append(node.key)

    # Containment edges into an owner are a claim too, not just tags.
    contained = defaultdict(list)       # (target type) -> [(source, target)]
    for edge in edges:
        target = nodes.get(edge.get('target_key'))
        if target is not None:
            contained[target.type].append((edge.get('source_key'), target.key))

    claimed = {}
    for kind in precedence:
        spec = specs.get(kind)
        if not spec:
            continue
        owner_types = spec.get('owner_types') or []
        by_name = {}
        for otype in owner_types:
            for key in owners.get(otype, []):
                by_name[nodes[key].name] = key
                by_name[nodes[key].id] = key

        for claim in spec.get('claims') or []:
            if 'tag_prefix' in claim or 'tag' in claim:
                prefix, exact = claim.get('tag_prefix'), claim.get('tag')
                for node in nodes.values():
                    if node.key in claimed:
                        continue
                    for key, value in _tags(node.raw).items():
                        hit = (prefix and key.startswith(prefix)) or (exact and key == exact)
                        if not hit:
                            continue
                        # Owner named by the tag's suffix, else by its value.
                        name = key[len(prefix):] if prefix else value
                        owner = by_name.get(name) or by_name.get(value)
                        if owner and owner != node.key:
                            claimed[node.key] = owner
                        break
            elif claim.get('edge') and claim.get('target_type'):
                for src, tgt in contained.get(claim['target_type'], []):
                    if src in nodes and src not in claimed and src != tgt:
                        claimed[src] = tgt
    return claimed


# ── stage 4: DERIVE — facts the data knows and no one should type ─────

def _segment_tiers(nodes, children, edges, model, spine):
    """
    segment key -> (tier, rank, derived)

    Tier comes from ROUTES, never from a name or a tag. A segment called
    "private" holding a default route to the internet gateway IS public, and the
    diagram has to say so - that contradiction is a finding, not a preference.

    When there is no routing data at all we return the tier as `unknown` and
    mark it NOT derived, so the renderer can show it as an assumption instead of
    quietly presenting a guess as a fact.
    """
    tiers = model.get('segment_tiers') or []
    rank_of = {t['tier']: t['rank'] for t in tiers}
    # Which edge kinds prove which tier, read from the model's own tests rather
    # than hardcoded here. The tests were declared and never consulted, so the
    # `isolated` tier was unreachable: a segment with routes but none to the
    # internet fell through to `unknown`, which the model explicitly says is an
    # ABSENCE of data and not a tier. Those are different facts and a reader
    # deserves to be told which one they are looking at.
    tested = {t['tier']: (t.get('test') or {}) for t in tiers}

    public, private, routed = set(), set(), set()
    for edge in edges:
        kind = edge.get('edge_type') or ''
        src, tgt = edge.get('source_key'), edge.get('target_key')
        if kind == 'routes-to-internet':
            public.update((src, tgt))
            routed.update((src, tgt))
        elif kind in ('routes-to', 'routes-through'):
            private.update((src, tgt))
            routed.update((src, tgt))

    def tier_of(members):
        """First tier whose declared test the members satisfy."""
        for spec in tiers:
            test = tested.get(spec['tier']) or {}
            if 'default_route_to' in test:
                # The destination decides it, and only one destination makes a
                # segment public. Both tests now name a `door.*` role after the
                # kind rename, so the prefix says nothing - it is `internet`
                # that separates `door.internet` from `door.egress`.
                destination = str(test['default_route_to'])
                if 'internet' in destination:
                    if members & public:
                        return spec
                elif members & private:
                    return spec
            elif test.get('no_default_route') and members & routed \
                    and not (members & public) and not (members & private):
                return spec
            elif test.get('no_route_data') and not (members & routed):
                return spec
        return None

    out = {}
    for node in nodes.values():
        if spine.get(node.key) != 'segment':
            continue
        members = set(children.get(node.key, [])) | {node.key}
        spec = tier_of(members)
        if spec is None:
            spec = next((t for t in tiers if t['tier'] == 'unknown'), None) or \
                {'tier': 'unknown', 'rank': 25, 'assumed': True}
        out[node.key] = (spec['tier'],
                         rank_of.get(spec['tier'], spec.get('rank', 25)),
                         not spec.get('assumed', False))
    return out


def _place_by_rule(nodes, positions, spine, model, roles):
    """
    The placement table in `model.yaml`, executed.

        cardinality  attached   ->  placement
        one          yes        ->  inside its host
        one          no         ->  its scope container's border
        many         (ignored)  ->  its scope container's border
        none         -          ->  inline, in its band

    Containment decides which BOX a node is in; this decides how it sits there.
    The two can disagree - a network ACL scoped to a VPC can carry a containment
    edge to one subnet - and when they do, the declared scope wins, because
    scope is a fact about the resource and the edge is an accident of what was
    collected.

    This used to be three passes. `_demote_unhosted`, `_dangle_unattached` and
    `_hoist_bindings` each answered "declared placement disagrees with
    containment, now what" in its own way, in an order that mattered and was
    never stated. Same question, so now one answer.
    """
    rule = model.get('attachment_rule') or {}
    demotion = model.get('demotion') or {}
    hosted_in = set(demotion.get('requires_container') or [])
    fallback = demotion.get('fallback') or {}

    def ancestors(key):
        seen, cur = [], getattr(nodes.get(key), 'parent', None)
        while cur and cur not in seen:
            seen.append(cur)
            cur = getattr(nodes.get(cur), 'parent', None)
        return seen

    for key, pos in positions.items():
        spec = roles.get(pos.role) or {}
        chain = ancestors(key)

        # ── none: a resident. Inline, unless it is not in a network at all,
        #    in which case its flow role is a claim it cannot support.
        #
        # A role's own containers COUNT, on top of the global list. The list was
        # [network, zone, segment], which agreed with three of the four
        # demotable roles and contradicted the fourth: `resident.ingress`
        # declares `container: [region, segment]`, so an API gateway sitting in
        # a region — exactly where its own role says it belongs — was demoted
        # out of it, and drew below the VPC in the services band instead of
        # above it as the L2 entry point it is. A rule that overrides the
        # declaration it is meant to enforce is not a rule.
        #
        # Additive, not a replacement: the global list stays the baseline every
        # role gets, so a role that declares FEWER containers than the list does
        # not thereby become stricter. Only the union is honoured.
        declared = spec.get('container') or ()
        allowed = hosted_in | {declared} if isinstance(declared, str) else hosted_in | set(declared)
        target = fallback.get(pos.role)
        if target and not any(spine.get(a) in allowed for a in chain):
            demoted = roles.get(target)
            if demoted:
                pos.role = target
                pos.band, pos.lane = demoted['band'], demoted['lane']
                pos.rank, pos.anchor = demoted['rank'], demoted['anchor']
                pos.kind = demoted.get('kind')
                pos.exposure = demoted.get('exposure')
                continue

        # ── one: with a host it nests; without one it goes to the border.
        if spec.get('cardinality') == 'one':
            parent = getattr(nodes.get(key), 'parent', None)
            attached = bool(parent and parent in nodes and spine.get(parent) is None)
            if attached:
                # `one_attached: host` means leave it where containment put it,
                # which is inside its host. Read rather than assumed, so the
                # table in the model is the thing being executed and not a
                # description of code that happens to agree with it.
                if rule.get('one_attached') != 'host':
                    raise ValueError(
                        f"attachment_rule.one_attached is "
                        f"{rule.get('one_attached')!r}; only 'host' is implemented")
                continue
            if rule.get('one_unattached') == 'scope_border':
                # No host to belong to, so it belongs to the container instead.
                # Still flagged: an interface attached to nothing is a finding
                # as much as it is a placement.
                pos.anchor, pos.band, pos.dangling = 'rail.s', None, True
            continue

        # ── artifact: its band's container, wherever containment put it. A
        #    spot request with a subnet edge is still provenance, not a
        #    resident of that subnet.
        # ── many: always the scope container's border, wherever containment
        #    happened to put it.
        if (spec.get('kind') == 'artifact' and rule.get('artifact') == 'band') or (
                spec.get('cardinality') == 'many'
                and rule.get('many') == 'scope_border'):
            want = spec.get('container')
            for ancestor in chain:
                if spine.get(ancestor) == want:
                    if ancestor != getattr(nodes.get(key), 'parent', None):
                        pos.hoist_to = ancestor
                    break
            continue

        # ── none: no host concept at all, so it stays in its band. The last
        #    row of the table, and the only one whose action is to do nothing -
        #    read anyway, so the table is executed rather than described.
        if rule.get('none') != 'inline':
            raise ValueError(
                f"attachment_rule.none is {rule.get('none')!r}; "
                f"only 'inline' is implemented")


def _zone_order(nodes, model, spine):
    """
    zone key -> rank, ordered by STABLE zone id.

    Several clouds shuffle the user-facing zone letter per account, so ordering
    by display name makes two accounts disagree about the same physical zone.
    Falls back to the name when no stable id was collected - wrong order beats
    no order, and it is at least deterministic.
    """
    key_field = model.get('ordering', {}).get('zone_order_by', 'zone_id')
    zones = [n for n in nodes.values() if spine.get(n.key) == 'zone']
    stable = {}
    for zone in zones:
        raw = zone.raw or {}
        stable[zone.key] = str(raw.get(key_field) or raw.get('ZoneId')
                               or zone.id or zone.key)
    return {key: (i + 1) * 10
            for i, key in enumerate(sorted(stable, key=lambda k: stable[k]))}


def _network_groups(nodes, edges, model, spine):
    """
    network key -> group id, by connectivity.

    Peered or transit-attached networks are LATERAL to one another (axiom A2),
    so they render as parallel lanes; unrelated ones stack. Union-find over the
    peering edges, then groups ordered by their lowest-sorting member so the
    result is a pure function of the data.
    """
    networks = [n.key for n in nodes.values() if spine.get(n.key) == 'network']
    parent = {k: k for k in networks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    lateral = set((model.get('network_grouping') or {}).get('lateral_edges') or [])
    for edge in edges:
        src, tgt = edge.get('source_key'), edge.get('target_key')
        if (edge.get('edge_type') in lateral
                and src in parent and tgt in parent):
            union(src, tgt)

    groups = defaultdict(list)
    for key in networks:
        groups[find(key)].append(key)
    ordered = sorted(groups.values(), key=lambda g: min(g))
    return {key: i for i, group in enumerate(ordered) for key in group}


# ── the pass ──────────────────────────────────────────────────────────

def layout(nodes, children, edges, binding, model=None):
    """
    Decorate a containment tree with placement.

    `nodes`    key -> node with .key .type .id .name .raw and, where the tree
               knows it, .layer_role naming the spine role it fills.
    `children` key -> [child keys], as the tree resolved them.
    `edges`    the non-containment edges, used only to DERIVE facts.
    `binding`  the provider's loaded topology_binding.yaml.

    Returns {node key: Position}. Never mutates the tree.
    """
    model = model or load_model()
    roles = _role_table()
    # Order among subcategories sharing a slot, from the order the model writes
    # them in. See taxonomy_ranks().
    sub_ranks = taxonomy_ranks(model)
    positions = {}

    # ── 1. INHERIT ────────────────────────────────────────────────────
    # Containment is the tree's; we only read which spine role each container
    # fills so the derive stages know a segment from a zone.
    spine = _spine_roles(nodes, binding)

    # ── 2. CLUSTER ────────────────────────────────────────────────────
    claimed = _resolve_clusters(nodes, edges, binding, model)

    # ── 3. CLASSIFY ───────────────────────────────────────────────────
    unplaced_cfg = model.get('unplaced') or {}
    attach_order = binding.get('attachment_order') or []

    containers = {c['role']: c for c in (model.get('containers') or [])}

    for node in nodes.values():
        # A container is a child too. It occupies a band in its PARENT's flow,
        # so it is placed by the spine rather than by a role lookup - asking the
        # role table where a VPC goes would send it to `unplaced`, because a VPC
        # is not a service that gets placed, it is a place.
        container_role = spine.get(node.key)
        if container_role and container_role in containers:
            spec = containers[container_role]
            pos = Position(role=container_role, band=spec.get('band'),
                           rank=spec.get('band_rank', spec.get('rank', 999)))
            # A boundary says so itself now. It used to emit no kind at all, so
            # the scene carried null for every VPC and subnet and the RENDERER
            # invented the word to fill the hole - a kind that existed on screen
            # and not in the model.
            pos.kind = spec.get('kind')
            pos.category, pos.subcategory = resolve_taxonomy(node.type, binding)
            pos.sub_rank = sub_ranks.get(f'{pos.category}.{pos.subcategory}', 999)
            pos.cluster = claimed.get(node.key)
            positions[node.key] = pos
            continue

        role = resolve_role(node.type, node.raw, binding)
        spec = roles.get(role)

        if spec is None:
            # Loud, not silent. A type with no binding gets a visible band
            # carrying its own name - silence is how thousands of types
            # accumulate unnoticed in one undifferentiated blob.
            pos = Position(role=role, band=unplaced_cfg.get('band', 'unplaced'),
                           rank=999)
            pos.derived = False
        else:
            anchor = spec['anchor']
            pos = Position(
                role=role,
                # A border or rail anchor takes the node OUT of band flow, so it
                # carries no band at all rather than a band it would not honour.
                band=None if anchor.startswith(_BORDER) else spec['band'],
                lane=spec['lane'],
                rank=spec['rank'],
                anchor=anchor,
            )
            pos.kind = spec.get('kind')
            pos.exposure = spec.get('exposure')
            pos.drawn = spec.get('drawn', True)
            pos.lane_rank = spec.get('lane_rank', 0)
            pos.edge_rank = spec.get('edge_rank', 50)
            pos.edge_align = spec.get('edge_align', 'centre')
            if role == 'part':
                pos.rank = _attachment_rank(node, attach_order)

        pos.category, pos.subcategory = resolve_taxonomy(node.type, binding)
        pos.sub_rank = sub_ranks.get(f'{pos.category}.{pos.subcategory}', 999)

        # The ARM comes from the domain, not the role. Role decides WHICH BOX a
        # rail hangs on (identity on the account, firewall on the network) and
        # that stays; it used to decide which SIDE too, and because role is
        # assigned per service the same domain landed on two arms depending on
        # which service carried it. Position and scope answer different
        # questions, so they are resolved from different things.
        if pos.anchor.startswith('rail.'):
            slot = resolve_slot(pos.category, pos.subcategory, model)
            if slot:
                pos.slot, arm, pos.slot_along, pos.slot_layers = slot
                pos.anchor = f'rail.{arm}'
            # Several domains, one tab. Display only: a flow log and an alarm
            # stay separate in the data so a filter can pick one, and read as
            # `observability` on the border so it does not carry five tabs
            # saying the same word.
            pos.rollup = (model.get('rollup') or {}).get(
                f'{pos.category}.{pos.subcategory}')

        pos.cluster = claimed.get(node.key)
        positions[node.key] = pos

    # ── 4. DERIVE ─────────────────────────────────────────────────────
    tiers = _segment_tiers(nodes, children, edges, model, spine)
    for key, (tier, rank, derived) in tiers.items():
        pos = positions[key]
        pos.tier, pos.rank, pos.derived = tier, rank, derived

    _place_by_rule(nodes, positions, spine, model, roles)

    # A rule may be drawn AS a box round what it governs, when they sit
    # together. Capped at one wrap per member: a resident already inside a
    # cluster box keeps that box and the rule stays a chip, because four nested
    # borders round one instance is a maze and not a diagram.
    parent_of = {c: k for k, kids in children.items() for c in kids}
    for rule_key, container in _resolve_wraps(nodes, positions, edges, parent_of).items():
        governed = {e['source_key'] for e in edges
                    if e.get('edge_type') in GOVERNED_BY
                    and e.get('target_key') == rule_key}
        if any(positions[k].cluster for k in governed if k in positions):
            continue
        positions[rule_key].wrap = container

    for key, rank in _zone_order(nodes, model, spine).items():
        positions[key].rank = rank

    for key, group in _network_groups(nodes, edges, model, spine).items():
        positions[key].lane = f'group-{group}'

    _resolve_entry(nodes, positions, binding, model)

    # ── 7. SPAN ───────────────────────────────────────────────────────
    _resolve_spans(nodes, children, positions, roles, spine)

    # ── 5. COLLAPSE + 6. ORDER ────────────────────────────────────────
    _collapse_and_order(nodes, children, positions)

    return positions


def _attachment_rank(node, attach_order):
    """Rank inside a workload box: root volume, data volumes, then interfaces."""
    raw = node.raw or {}
    for entry in attach_order:
        match = entry.get('match') or {}
        if match.get('type') and match['type'] != node.type:
            continue
        if match.get('root') and not _dig(raw, 'Attachments.DeleteOnTermination'):
            continue
        if match.get('primary') and not raw.get('Attachment', {}).get('DeviceIndex') == 0:
            continue
        return entry.get('rank', 50)
    return 50


def _resolve_entry(nodes, positions, binding, model):
    """
    Attach the front-door marker to the first entry role that EXISTS.

    Presence-collapsing (§5) applied to the top of the diagram: if the first
    candidate is absent we fall through to the next, so every estate gets an
    entry point without per-account configuration. Losers still draw in their
    own band - they are present, just not the front door.
    """
    for candidate in (model.get('entry_points') or []):
        role = candidate.get('role')
        hits = []
        for node in nodes.values():
            pos = positions[node.key]
            if pos.role != role and not (
                    role == 'resident.balancer' and pos.role == 'resident.balancer'):
                continue
            if candidate.get('conditional') and not _is_entry_candidate(
                    node.type, node.raw, binding):
                continue
            hits.append(node)
        if hits:
            winner = sorted(hits, key=lambda n: sort_key(n, positions[n.key]))[0]
            positions[winner.key].entry = True
            return


def _resolve_spans(nodes, children, positions, roles, spine):
    """
    Expand a spanning node across exactly the zone lanes it occupies.

    A balancer has one interface per zone it is enabled in, so drawing it inside
    a single segment is factually wrong. It spans - but never a lane it has no
    presence in, which is the difference between a span and a guess.
    """
    zone_of = {}
    for node in nodes.values():
        if spine.get(node.key) == 'segment':
            for child in children.get(node.key, []):
                zone_of[child] = getattr(node, 'parent', None)

    for node in nodes.values():
        pos = positions[node.key]
        spec = roles.get(pos.role) or {}
        if spec.get('spans') != 'zone':
            continue
        zones = set()
        raw = node.raw or {}
        for entry in (raw.get('AvailabilityZones') or []):
            if isinstance(entry, dict):
                zone = entry.get('ZoneName') or entry.get('ZoneId')
                if zone:
                    zones.add(zone)
            elif isinstance(entry, str):
                zones.add(entry)
        if not zones and node.key in zone_of:
            zones.add(zone_of[node.key])
        pos.span = sorted(z for z in zones if z)


def _collapse_and_order(nodes, children, positions):
    """
    Drop empty bands, close the gaps, then order within each cell.

    Rank is a RELATIVE order, not a coordinate. An estate with no egress tier
    does not draw an empty band - what follows moves up into its place. That is
    what lets one specification fit every account without per-account tuning.
    """
    for child_keys in children.values():
        visible = [k for k in child_keys if k in positions]
        if not visible:
            continue

        # Bands present in this container, in declared order. Border and rail
        # anchors sit outside band flow, so they never occupy a slot.
        #
        # The sort key carries the NAME as well as the rank. Two bands can
        # legitimately share a minimum rank, and a key that ties there would
        # fall back to set iteration order - which varies with the hash seed, so
        # the diagram would differ between runs on identical input. That is the
        # exact failure this module exists to remove, and it is easy to
        # reintroduce, so both keys below are deliberately total.
        def slots(attr):
            groups = defaultdict(list)
            for key in visible:
                value = getattr(positions[key], attr)
                if value and (attr == 'lane' or positions[key].anchor == 'in'):
                    groups[value].append(positions[key].rank)
            ordered = sorted(groups, key=lambda v: (min(groups[v]), v))
            return {value: i for i, value in enumerate(ordered)}

        slot, lane_slot = slots('band'), slots('lane')

        for key in sorted(visible, key=lambda k: sort_key(nodes[k], positions[k])):
            pos = positions[key]
            pos.order = slot.get(pos.band, lane_slot.get(pos.lane, 0))
