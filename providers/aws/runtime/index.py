"""
Triple index — the thing that stops edges dangling.

A path can yield any of three handles for the same resource:

    lambda -> KMSKeyArn                 an ARN
    ebs    -> KmsKeyId                  a key id
    ec2    -> Groups[].GroupName        a name

but kms-key nodes are keyed by KeyId and security-group nodes by GroupId. Index
each node under all three and every one of those paths resolves to the same
node instead of dangling.

`lookup_any` additionally types a value with no target hint at all, which is
what makes data-driven discovery possible: an ARN states its own service and
resource type, and an id prefix like `sg-` is unique across AWS.
"""

import csv
import os

from providers.aws.runtime import arn as arnlib

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')


class NodeIndex:
    """Registry of nodes, addressable by id, ARN or name."""

    def __init__(self, recipes=None):
        self.recipes = recipes if recipes is not None else load_recipes()
        self.nodes = {}
        self._typed = {}          # (type, value) -> node
        self._by_arn = {}         # arn -> node          (globally unique)
        self._by_id = {}          # bare id -> node      (only when unambiguous)
        self._ambiguous = set()
        # id_prefix -> resource type, for typing a bare id with no hint.
        self._prefix = {}
        for name, r in self.recipes.items():
            prefix = r.get('id_prefix')
            if prefix:
                # A prefix shared by two types cannot type anything on its own.
                self._prefix[prefix] = None if prefix in self._prefix else name

    def add(self, node):
        self.nodes[node.key] = node
        for value in (node.id, node.arn, node.name):
            if value:
                self._typed[(node.type, str(value))] = node

        if node.arn:
            self._by_arn[node.arn] = node

        if node.id:
            rid = str(node.id)
            if rid in self._by_id and self._by_id[rid].key != node.key:
                # Two resources share a bare id (an ECS cluster name and an EKS
                # cluster name, say). Untyped lookup must not guess between them.
                self._ambiguous.add(rid)
            else:
                self._by_id[rid] = node
        return node

    def lookup(self, type_, value):
        """Find a node of a known type by any of its handles."""
        if value is None:
            return None
        value = str(value)
        hit = self._typed.get((type_, value))
        if hit is not None:
            return hit
        # The path gave an ARN but the node was registered under its id (or the
        # reverse) - fall back to the global ARN map before giving up.
        if value.startswith('arn:'):
            hit = self._by_arn.get(value)
            if hit is not None and hit.type == type_:
                return hit
            parsed = arnlib.parse(value)
            if parsed and parsed.resource_id:
                return self._typed.get((type_, parsed.resource_id))
        return None

    def lookup_any(self, value):
        """
        Type a value with no target hint, for data-driven discovery.

        Only answers when the value types itself: an ARN, or a bare id whose
        prefix belongs to exactly one resource type. Anything ambiguous returns
        None rather than guessing - a wrong edge is worse than a missing one.
        """
        if not isinstance(value, str) or not value:
            return None

        if value.startswith('arn:'):
            hit = self._by_arn.get(value)
            if hit is not None:
                return hit
            parsed = arnlib.parse(value)
            if not parsed or not parsed.resource_id:
                return None
            if parsed.resource_id in self._ambiguous:
                return None
            hit = self._by_id.get(parsed.resource_id)
            # Confirm the ARN's service agrees with the node we matched.
            if hit is not None:
                recipe = self.recipes.get(hit.type, {})
                if recipe.get('service') and recipe['service'] != parsed.service:
                    return None
            return hit

        for prefix, type_ in self._prefix.items():
            if type_ and value.startswith(prefix):
                return self._typed.get((type_, value))
        return None

    def __len__(self):
        return len(self.nodes)


def load_recipes(path=None):
    path = path or os.path.join(CATALOG, 'arn_recipes.csv')
    if not os.path.exists(path):
        return {}
    return {r['resource']: r for r in csv.DictReader(open(path))}
