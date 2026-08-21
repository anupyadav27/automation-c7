"""
Cross-account discovery — finding the other accounts from inside one.

Enterprise estates are not one account. A workload account runs in subnets owned
by a network account, reaches a shared appliance through an endpoint service in
a third, and trusts roles from a fourth. With credentials for only one of them,
a naive collection reports a VPC that appears to be missing and connections that
appear to dangle.

A great deal is visible anyway, because AWS puts the other account's id directly
in the data. Six independent signals, in rough order of how much they prove:

  arn_account      every ARN carries an account segment. Parsing every ARN in
                   every collected payload and comparing that segment to ours is
                   the general detector, and it needs no per-service knowledge.
  owner_id         `subnet.OwnerId` different from the scan account means the
                   subnet was shared to us via RAM - the central-network model.
  peering          VPC peering and TGW attachments name the far-side owner
                   outright (AccepterVpcInfo.OwnerId, ResourceOwnerId).
  endpoint_service a ServiceName beginning `com.amazonaws.vpce.` is a CUSTOMER
                   endpoint service, not an AWS one, so something on the far end
                   belongs to another account. This is the shared-F5 shape.
  policy           trust and resource policies name principals by account.
  organizations    ListAccounts gives the real names, when org read access
                   exists. The only signal that supplies a human name.

What this deliberately does NOT do is guess. Where a chain leaves the account,
it terminates with the owner recorded and is marked external. "Our VPC reaches
endpoint service vpce-svc-0abc owned by account 999..." is true and useful;
inventing what sits behind it would not be.
"""

import re
from collections import defaultdict

from providers.aws.runtime import arn as arnlib

ACCOUNT_RE = re.compile(r'^\d{12}$')

# Field names that carry another account's id. Checked by exact leaf name so a
# `ResourceOwnerId` is picked up but an `OwnerAlias` is not.
OWNER_FIELDS = {
    'OwnerId', 'ownerId', 'Owner', 'owner', 'OwnerAccount', 'OwnerAccountId',
    'ResourceOwnerId', 'AccountId', 'accountId', 'AwsAccountId',
    'SourceAccountId', 'TargetAccountId', 'PrincipalAccountId',
}

# A customer-owned endpoint service. AWS's own services are
# `com.amazonaws.<region>.<service>`; anything with the `vpce` marker was
# published by another account.
CUSTOMER_ENDPOINT_SERVICE = re.compile(r'^com\.amazonaws\.vpce\.')

# How the far account relates to us. Ordered by how much it implies - a peer or
# provider is a live network path, a mere reference is not.
RELATIONSHIP_RANK = {
    'owner': 0,          # owns a resource we are running inside
    'provider': 1,       # publishes a service we consume
    'consumer': 2,       # consumes a service we publish
    'peer': 3,           # network peering or transit attachment
    'trusted': 4,        # named in one of our policies
    'referenced': 5,     # its ARN appears somewhere in our data
}


class AccountGraph:
    """Accounts reachable from the scanned one, and the evidence for each."""

    def __init__(self, scan_account):
        self.scan_account = str(scan_account)
        self._accounts = {}
        # Endpoint services we know are customer-published but whose owner is
        # not in the payload. The external dependency is real even when the
        # account id is not available, so it is recorded rather than lost.
        self.unresolved_services = []

    def add(self, account_id, relationship, via, evidence='', name=None):
        """
        Record a sighting. Repeated sightings strengthen rather than replace:
        an account seen once as `referenced` and later as `owner` is an owner.
        """
        account_id = str(account_id or '').strip()
        if not ACCOUNT_RE.match(account_id) or account_id == self.scan_account:
            return None
        entry = self._accounts.setdefault(account_id, {
            'account_id': account_id, 'name': '', 'relationship': relationship,
            'signals': set(), 'evidence': [], 'sightings': 0,
        })
        entry['sightings'] += 1
        entry['signals'].add(via)
        if RELATIONSHIP_RANK.get(relationship, 9) < \
                RELATIONSHIP_RANK.get(entry['relationship'], 9):
            entry['relationship'] = relationship
        if evidence and len(entry['evidence']) < 5:
            entry['evidence'].append(evidence)
        if name:
            entry['name'] = name
        return entry

    def rows(self):
        out = []
        for entry in self._accounts.values():
            out.append({
                'account_id': entry['account_id'],
                'name': entry['name'],
                'relationship': entry['relationship'],
                'discovered_via': ','.join(sorted(entry['signals'])),
                'sightings': entry['sightings'],
                'evidence': ' | '.join(entry['evidence'])[:400],
            })
        return sorted(out, key=lambda r: (RELATIONSHIP_RANK.get(r['relationship'], 9),
                                          -r['sightings'], r['account_id']))

    def __len__(self):
        return len(self._accounts)

    def __contains__(self, account_id):
        return str(account_id) in self._accounts


def _walk(obj, path='', depth=0, max_depth=8):
    """Yield (leaf_name, path, value) for every scalar in a payload."""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk(value, f'{path}.{key}' if path else key,
                             depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, f'{path}[]', depth, max_depth)
    elif isinstance(obj, (str, int)):
        yield path.split('.')[-1].replace('[]', ''), path, obj


def scan_asset(graph, asset, raw=None):
    """
    Harvest every cross-account signal from one collected asset.

    Runs over the raw payload rather than the normalised record, because the
    account ids live in fields we do not otherwise keep.
    """
    payload = raw if raw is not None else asset.get('raw') or {}
    resource_key = asset.get('resource_key', '')

    # Specific signals first. The generic field walk below cannot tell a service
    # provider from a resource owner, and `owner` outranks `provider`, so
    # running it first would relabel every provider as an owner.
    service_name = payload.get('ServiceName') or payload.get('serviceName')
    if isinstance(service_name, str) and CUSTOMER_ENDPOINT_SERVICE.match(service_name):
        # On DescribeVpcEndpoints `Owner` is OUR account; the provider's id
        # appears on the endpoint SERVICE. Either payload may arrive here, so
        # take an Owner only when it is not us - add() drops our own id anyway.
        owner = payload.get('Owner') or payload.get('ServiceOwner')
        if owner and str(owner) != graph.scan_account:
            graph.add(owner, 'provider', 'endpoint_service',
                      f'{resource_key} -> {service_name}')
        else:
            graph.unresolved_services.append(service_name)

    for leaf, path, value in _walk(payload):
        text = str(value)

        # 1. any ARN naming another account
        if text.startswith('arn:'):
            parsed = arnlib.parse(text)
            if parsed and parsed.account:
                graph.add(parsed.account, 'referenced', 'arn_account',
                          f'{resource_key}.{path}')
            continue

        if not ACCOUNT_RE.match(text):
            continue

        # 2. an owner field on a resource we are using
        if leaf in OWNER_FIELDS:
            # `OwnerId` on an EC2 resource genuinely means the owning account,
            # so a subnet with a foreign OwnerId means we run inside another
            # account's network. A bare `Owner` is far vaguer - on a VPC
            # endpoint it is us - so it only counts as a reference.
            relationship = 'owner' if leaf in ('OwnerId', 'ownerId') else 'referenced'
            # 3. peering and transit attachments state the far side outright
            if 'Accepter' in path or 'Requester' in path or 'ResourceOwner' in leaf:
                relationship = 'peer'
            graph.add(text, relationship, 'owner_id', f'{resource_key}.{path}')

    return graph


def scan_policy_edges(graph, edges):
    """
    Harvest accounts from policy edges (mechanism B).

    A trust policy naming another account is the clearest statement of a
    relationship that exists: someone deliberately granted it.
    """
    for edge in edges:
        kind = edge.get('principal_kind')
        value = edge.get('source_id') or ''
        if kind == 'account':
            graph.add(value, 'trusted', 'policy',
                      f"{edge.get('edge_type')} -> {edge.get('target_id')}")
        elif kind == 'arn':
            parsed = arnlib.parse(value)
            if parsed and parsed.account:
                graph.add(parsed.account, 'trusted', 'policy',
                          f"{edge.get('edge_type')} -> {edge.get('target_id')}")
    return graph


def apply_organization(graph, org_accounts):
    """
    Attach real names from `organizations:ListAccounts`.

    Names are only available here, and only when org read access exists - so
    this enriches what the other signals found rather than replacing it. An org
    member we never otherwise saw is recorded too, marked so it is clear it was
    not reached through any resource.
    """
    for account in org_accounts or []:
        account_id = str(account.get('Id') or '')
        name = account.get('Name') or ''
        if account_id in graph:
            graph.add(account_id, 'referenced', 'organizations', '', name=name)
        else:
            graph.add(account_id, 'referenced', 'organizations',
                      'org member, no resource reference found', name=name)
    return graph


def external_owner(asset, scan_account):
    """
    The account owning this asset, when it is not the scanned one.

    A shared subnet is the case that matters: the workload is ours, the subnet
    is not, and a diagram that does not say so is misleading.
    """
    payload = asset.get('raw') or {}
    for field in ('OwnerId', 'ownerId', 'Owner', 'OwnerAccountId'):
        value = str(payload.get(field) or '')
        if ACCOUNT_RE.match(value) and value != str(scan_account):
            return value
    return None


def summarise(graph):
    """Counts by relationship, for a run report."""
    counts = defaultdict(int)
    for row in graph.rows():
        counts[row['relationship']] += 1
    return dict(counts)
