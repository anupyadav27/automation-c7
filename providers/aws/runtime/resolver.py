"""
Path resolution and edge derivation.

Two ways to find an edge, used together:

  derive_edges()    table-driven. Walk the paths in relations.csv - the 275 we
                    extracted from c7n, CloudFormation, ASFF and docstrings -
                    and look each value up in the index. This is the prior: it
                    says *where to look*.

  discover_edges()  data-driven. Scan every string in a resource for something
                    that types itself: an ARN names its own service and resource
                    type, and `vpc-0a1b2c` can only be a VPC. This confirms the
                    table and finds edges nobody ever declared.

Neither costs an API call. Every path reads a field already present in the
response we fetched to create the node.
"""

import re

from providers.aws.runtime import arn as arnlib

# The five shapes a path can take, as classified in relations.csv:
#   scalar       VpcId
#   dotted       DBSubnetGroup.VpcId
#   list_scalar  VpcConfig.SubnetIds[]
#   list_dict    VpcSecurityGroups[].VpcSecurityGroupId
#   list_nested  NetworkInterfaces[].Groups[].GroupId
# One walker handles all five, because they differ only in where `[]` appears.


def attribute_container(path):
    """
    The path prefix holding a pointer's sibling fields.

    A relation is a pointer, but whether it *means* anything usually depends on
    its neighbours: `Routes[].NatGatewayId` says a route table uses a NAT
    gateway, while `Routes[].DestinationCidrBlock` alongside it says whether
    that route is the default route to the internet. The siblings live in the
    same list element, so the container is everything up to the last `[]`.

    Returns '' when the path has no list element and therefore no siblings of
    interest.
    """
    if '[]' not in path:
        return ''
    return path[:path.rindex('[]') + 2]


# A field that holds a document rather than a value. A Step Functions
# definition is 20 KB of JSON with the resources it invokes named inside it, and
# a path can address the field but not what is buried in it.
_ARN = re.compile(r'arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{0,12}:[^\s",\\\]}]+')
# `arn:aws:states:::aws-sdk:ec2:runInstances` is an API CALL, not a resource -
# an account number is what separates a thing you own from a thing you invoke.
_INTEGRATION = re.compile(r'^arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*::')


def arns_in(text):
    """
    Every resource ARN named inside a document, integrations excluded.

    Used for fields that carry a whole JSON document: a state machine's
    definition, a policy, a task definition. Returns nothing rather than
    guessing when the document only names service integrations, which is what
    a workflow calling AWS APIs directly looks like.
    """
    if not isinstance(text, str) or 'arn:' not in text:
        return []
    seen, out = set(), []
    for arn in _ARN.findall(text):
        arn = arn.rstrip('."\'')
        if arn in seen or _INTEGRATION.match(arn):
            continue
        seen.add(arn)
        out.append(arn)
    return out


def resolve_with_attributes(obj, path):
    """
    Yield (value, attributes) pairs for a path.

    `attributes` are the other scalar fields of the element the value came from,
    which is what lets an edge be judged rather than merely drawn. Without them
    `route_table -> nat_gateway` cannot answer "for which destination?", and no
    reachability question can be settled.
    """
    container = attribute_container(path)
    if not container:
        out = []
        for value in resolve_path(obj, path):
            # A field holding a whole document names its resources inside
            # itself. Yielded as separate values so each becomes its own edge,
            # which is what makes a workflow's members findable.
            inner = arns_in(value)
            out.extend((arn, {'via': 'document'}) for arn in inner) if inner \
                else out.append((value, {}))
        return out

    leaf = path[len(container):].lstrip('.')
    out = []
    for element in _walk_container(obj, container):
        # `subnets[]` — a list of plain strings. The elements ARE the values,
        # there is no leaf field to read and no siblings to carry. This fell
        # through `resolve_path(element, leaf) if leaf else []` and returned
        # nothing, so every rule whose path ended in a bare `[]` scored zero
        # hits and was written back as `absent` — a node group that names three
        # subnets looked like it named none, and the catalog recorded the rule
        # as unexercised rather than broken.
        if not leaf:
            if isinstance(element, (str, int, float)) and not isinstance(element, bool):
                out.append((str(element), {}))
            continue
        if not isinstance(element, dict):
            continue
        for value in resolve_path(element, leaf) if leaf else []:
            attributes = {k: v for k, v in element.items()
                          if isinstance(v, (str, int, float, bool))
                          and k != leaf.split('.')[0]}
            out.append((value, attributes))
    return out


def _walk_container(obj, container):
    """Every element of a `[]`-terminated container path."""
    current = [obj]
    for segment in container.split('.'):
        listy = segment.endswith('[]')
        key = segment[:-2] if listy else segment
        nxt = []
        for item in current:
            if not isinstance(item, dict):
                continue
            value = item.get(key)
            if value is None:
                continue
            nxt.extend(value) if listy and isinstance(value, list) else nxt.append(value)
        current = nxt
    return current


def resolve_path(obj, path):
    """
    Walk a path and return every scalar it reaches.

    Always returns a list - a path may legitimately yield zero values (the field
    is absent), one, or many (any segment ending in `[]` fans out). Missing keys
    are skipped rather than raising: a field being absent on some resources is
    normal, not an error.
    """
    if not path:
        return []
    current = [obj]
    for segment in path.split('.'):
        is_list = segment.endswith('[]')
        key = segment[:-2] if is_list else segment
        nxt = []
        for item in current:
            if not isinstance(item, dict):
                continue
            value = item.get(key)
            if value is None:
                continue
            if is_list:
                if isinstance(value, list):
                    nxt.extend(value)
                else:
                    nxt.append(value)
            else:
                nxt.append(value)
        current = nxt
        if not current:
            return []
    out = []
    for value in current:
        if not isinstance(value, (str, int, float)) or value == '':
            continue
        out.extend(_split_id_list(value) if isinstance(value, str) else [value])
    return out


# A comma-joined list of bare ids, e.g. an autoscaling group's
# `VPCZoneIdentifier`: "subnet-a,subnet-b,subnet-c". AWS returns several of
# these as one string, and resolving the whole blob matches nothing - the
# subnets are there, they just never reach the index.
_ID_LIST = re.compile(r'^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)+$')


def _split_id_list(value):
    """
    One value, or the several a comma-joined id list really carries.

    Deliberately narrow: only splits when EVERY part is a bare token. A
    description, an ARN or anything with a space keeps its commas, so this can
    never chop a legitimate value in half.
    """
    return value.split(',') if _ID_LIST.match(value) else [value]


def derive_edges(node, relations, index, recipes=None):
    """
    Apply the relation table to one node.

    Yields dicts with `resolved` set when the target was found in the index and
    False when it dangled. Dangling edges are kept deliberately - they are the
    signal that a path is wrong, or that the target type was not collected, and
    discarding them would hide both.
    """
    recipes = recipes or {}
    for rel in relations.get(node.type, ()):
        path = rel.get('source_path')
        if not path:
            continue
        target_type = rel['target_resource']
        for value in resolve_path(node.raw, path):
            value = str(value)
            target = index.lookup(target_type, value)
            yield {
                'source_type': node.type,
                'source_id': node.id,
                'source_key': node.key,
                'target_type': target_type,
                'target_id': target.id if target else value,
                'target_key': target.key if target else None,
                'edge_type': rel.get('edge_type', 'references'),
                'via': path,
                'source': rel.get('source', ''),
                'confidence': rel.get('confidence', ''),
                'resolved': target is not None,
                # Ladder levels 2 and 3, evaluated inline. None means the check
                # does not apply (no prefix declared, or the value is not an ARN).
                'prefix_ok': arnlib.matches_prefix(value, recipes.get(target_type, {})),
                'arn_ok': arnlib.matches_type(value, recipes.get(target_type, {})),
            }


def _walk_strings(obj, path='', depth=0, max_depth=8):
    """Yield (path, string) for every string in a nested structure."""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f'{path}.{k}' if path else k, depth + 1, max_depth)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, f'{path}[]', depth, max_depth)
    elif isinstance(obj, str) and obj:
        yield path, obj


def discover_edges(node, index, declared=None):
    """
    Find edges from the data itself, with no table.

    An ARN carries its service and resource type; an id prefix like `sg-` is
    unique across AWS. Either is enough to type a value and point an edge at it,
    so this both corroborates the table and surfaces relations nobody declared.

    `declared` is the set of (path, target_type) pairs already produced by
    derive_edges, so the same edge is not emitted twice.
    """
    declared = declared or set()
    seen = set()
    for path, value in _walk_strings(node.raw):
        # Strip list markers so `Groups[].GroupId` and `Groups.GroupId` dedupe.
        norm = path.replace('[]', '')
        target = index.lookup_any(value)
        if target is None or target.key == node.key:
            continue
        if (norm, target.type) in declared or (norm, target.key) in seen:
            continue
        seen.add((norm, target.key))
        yield {
            'source_type': node.type,
            'source_id': node.id,
            'source_key': node.key,
            'target_type': target.type,
            'target_id': target.id,
            'target_key': target.key,
            'edge_type': 'references',
            'via': path,
            'source': 'discovered',
            'confidence': 'observed',
            'resolved': True,
            'prefix_ok': None,
            'arn_ok': None,
        }


def load_relations(path):
    """Read relations.csv into {source_resource: [rows]} for fast per-node lookup."""
    import csv
    from collections import defaultdict
    out = defaultdict(list)
    for row in csv.DictReader(open(path)):
        out[row['source_resource']].append(row)
    return dict(out)
