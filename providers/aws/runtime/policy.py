"""
Mechanism B (`policy-document`) — relations from ARNs inside policy documents.

A (`field-pointer`) and C (`value-match`) read a value out of a field. This one
reads it out of a JSON document stored *inside* a field, which is why field-pointer mining is blind to
the entire permission graph: the ARN naming the resource a role can reach is a
substring of a serialised policy, not a member of any shape.

Three document kinds, each producing a different edge direction:

  trust      a role's AssumeRolePolicyDocument. Principal -> can assume -> role.
  identity   a policy attached to a role/user/group. Holder -> can access ->
             every ARN in Statement[].Resource.
  resource   a policy attached to a bucket/key/queue. Principal -> can access ->
             the resource holding the policy.

Everything here is pure: documents in, edge dicts out. Fetching them is the
collector's job.

Two properties of real policies drive most of the code:

  * almost every field is "string or list of strings". Statement, Action,
    Resource, Principal and Condition values all shift between the two, and code
    that assumes either one crashes on perfectly valid policies.
  * ARNs are frequently patterns, not identifiers. `arn:aws:s3:::bucket/*` names
    every object in a bucket and matches no resource exactly. Those are kept and
    flagged rather than dropped - a wildcard grant is usually the finding you
    most want - but they must never be presented as a resolved edge.
"""

import json
import re
from urllib.parse import unquote, unquote_plus

from providers.aws.runtime import arn as arnlib

# A principal that is an account root, an account id, or a service principal
# rather than a resource ARN.
_ACCOUNT_RE = re.compile(r'^\d{12}$')
_SERVICE_PRINCIPAL_RE = re.compile(r'^[a-z0-9.-]+\.amazonaws\.com(\.cn)?$')

# Condition keys whose values are ARNs. Cross-account access is usually
# constrained here rather than in Resource, so skipping them loses the edge that
# actually explains why the grant exists.
_ARN_CONDITION_KEYS = re.compile(
    r'(SourceArn|sourceArn|PrincipalArn|SourceOwner|EncryptionContext|'
    r'CalledVia|ResourceArn|TargetArn|SourceAccount)', re.I)


def decode_document(raw, encoding='json'):
    """
    Turn a stored policy into a dict.

    IAM percent-encodes its documents; most other services return raw JSON; a
    few return an already-parsed object. Returns None rather than raising - a
    malformed policy on one resource must not abort a whole collection.
    """
    if raw is None or raw == '':
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None

    text = raw
    if encoding == 'url' or (text.startswith('%7B') or text.startswith('%7b')):
        # unquote_plus first: IAM encodes spaces as '+' in some documents, and
        # plain unquote leaves them, producing invalid JSON.
        text = unquote_plus(text)
        if not text.lstrip().startswith('{'):
            text = unquote(raw)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def as_list(value):
    """Normalise AWS's string-or-list fields. `None` yields an empty list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def iter_statements(document):
    """Yield each statement. A document may hold one dict or a list of them."""
    if not isinstance(document, dict):
        return
    for statement in as_list(document.get('Statement')):
        if isinstance(statement, dict):
            yield statement


def classify_principal(value):
    """
    Describe one principal entry: (kind, value).

    kind is one of wildcard | account | service | federated | arn | unknown.
    The distinction matters downstream - a wildcard principal is public access,
    an account principal is cross-account trust, and only an `arn` can become an
    edge to a specific node.
    """
    if value == '*':
        return 'wildcard', '*'
    if not isinstance(value, str):
        return 'unknown', str(value)
    if _ACCOUNT_RE.match(value):
        return 'account', value
    if _SERVICE_PRINCIPAL_RE.match(value):
        return 'service', value
    parsed = arnlib.parse(value)
    if parsed:
        # arn:aws:iam::123456789012:root names an account, not a principal.
        if parsed.service == 'iam' and parsed.resource_id == 'root':
            return 'account', parsed.account
        return 'arn', value
    return 'unknown', value


def iter_principals(statement):
    """
    Yield (kind, value) for every principal in a statement.

    Principal takes four shapes in the wild: "*", a bare string, a dict keyed by
    AWS/Service/Federated/CanonicalUser, or lists inside that dict. NotPrincipal
    is deliberately ignored - it denies rather than grants, so treating it as a
    grant would invert the meaning.
    """
    principal = statement.get('Principal')
    if principal is None:
        return
    if isinstance(principal, str):
        yield classify_principal(principal)
        return
    if isinstance(principal, dict):
        for key, value in principal.items():
            for entry in as_list(value):
                if key == 'Service':
                    yield 'service', entry
                elif key == 'Federated':
                    yield 'federated', entry
                elif key == 'CanonicalUser':
                    yield 'canonical_user', entry
                else:
                    yield classify_principal(entry)
        return
    for entry in as_list(principal):
        yield classify_principal(entry)


def iter_condition_arns(statement):
    """Yield ARNs buried in Condition blocks, where cross-account limits live."""
    condition = statement.get('Condition')
    if not isinstance(condition, dict):
        return
    for tests in condition.values():
        if not isinstance(tests, dict):
            continue
        for key, value in tests.items():
            if not _ARN_CONDITION_KEYS.search(key):
                continue
            for entry in as_list(value):
                if isinstance(entry, str) and entry.startswith('arn:'):
                    yield key, entry


# Condition keys that narrow a wildcard principal to something specific. A
# statement carrying one of these is not public no matter what Principal says -
# AWS's own default SNS topic policy is `Principal: *` plus
# `Condition: {StringEquals: {AWS:SourceOwner: <account>}}`, and reading that as
# public reports every account's default topics as world-readable.
RESTRICTING_CONDITION_KEYS = re.compile(
    r'(SourceOwner|SourceAccount|SourceArn|SourceVpce?|SourceVpcE|PrincipalOrgID|'
    r'PrincipalOrgPaths|PrincipalAccount|PrincipalArn|ResourceOrgID|'
    r'ResourceAccount|SourceIp|VpcSourceIp|userid|username)', re.I)


def has_restricting_condition(statement):
    """
    True when a statement's Condition narrows who the principal can be.

    Only keys that constrain the *caller* count. A condition on, say,
    s3:prefix limits what may be done, not by whom, and leaves a wildcard
    principal every bit as public.
    """
    condition = statement.get('Condition')
    if not isinstance(condition, dict):
        return False
    for tests in condition.values():
        if not isinstance(tests, dict):
            continue
        for key in tests:
            if RESTRICTING_CONDITION_KEYS.search(str(key)):
                return True
    return False


def is_pattern(value):
    """True when an ARN contains a wildcard and so names a set, not a resource."""
    return isinstance(value, str) and ('*' in value or '?' in value)


def concrete_prefix(value):
    """The wildcard-free prefix of a pattern ARN, for prefix matching."""
    if not isinstance(value, str):
        return ''
    cut = min((i for i in (value.find('*'), value.find('?')) if i >= 0), default=-1)
    return value if cut < 0 else value[:cut]


def _reference(role, value, statement, extra=None):
    effect = statement.get('Effect', 'Allow')
    ref = {
        'role': role,
        'value': value,
        'effect': effect,
        'actions': [a for a in as_list(statement.get('Action')) if isinstance(a, str)],
        'is_pattern': is_pattern(value),
        'prefix': concrete_prefix(value) if is_pattern(value) else value,
        'sid': statement.get('Sid', ''),
        'restricted': has_restricting_condition(statement),
    }
    if extra:
        ref.update(extra)
    return ref


def extract_references(document, kind='resource'):
    """
    Pull every ARN-bearing reference out of a document.

    Returns a list of dicts describing what was referenced and how, without
    deciding what the edge means - `kind` governs that, and the caller supplies
    it from policy_sources.csv.
    """
    refs = []
    for statement in iter_statements(document):
        for resource in as_list(statement.get('Resource')):
            if isinstance(resource, str) and (resource == '*' or resource.startswith('arn:')):
                refs.append(_reference('resource', resource, statement))
        for principal_kind, value in iter_principals(statement):
            refs.append(_reference('principal', value, statement,
                                   {'principal_kind': principal_kind}))
        for key, value in iter_condition_arns(statement):
            refs.append(_reference('condition', value, statement, {'condition_key': key}))
    return refs


def derive_edges(holder_key, holder_id, document, kind, index=None, raw_encoding='json'):
    """
    Turn one policy document into edges.

    `holder_*` identify the resource the document is attached to. Direction
    follows the document kind:

        trust      principal -> assumes    -> holder (the role)
        identity   holder    -> can-access -> each Resource ARN
        resource   principal -> can-access -> holder

    Unresolved references are still emitted, with `resolved=False`. A grant to
    an ARN that does not exist in this account is exactly the sort of thing an
    audit wants to see, and silently dropping it would hide it.
    """
    parsed = decode_document(document, raw_encoding)
    if parsed is None:
        return []

    edges = []
    for ref in extract_references(parsed, kind):
        target = None
        if index is not None and not ref['is_pattern'] and ref['value'] != '*':
            target = index.lookup_any(ref['value'])

        if kind == 'trust' and ref['role'] == 'principal':
            source_key, source_id = None, ref['value']
            target_key, target_id = holder_key, holder_id
            edge_type = 'assumes'
        elif kind == 'identity' and ref['role'] == 'resource':
            source_key, source_id = holder_key, holder_id
            target_key, target_id = (target.key if target else None), ref['value']
            edge_type = 'can-access'
        elif kind == 'resource' and ref['role'] == 'principal':
            source_key, source_id = None, ref['value']
            target_key, target_id = holder_key, holder_id
            edge_type = 'accessible-by'
        elif ref['role'] == 'condition':
            source_key, source_id = holder_key, holder_id
            target_key, target_id = (target.key if target else None), ref['value']
            edge_type = 'constrained-by'
        else:
            continue

        edges.append({
            'source_key': source_key, 'source_id': source_id,
            'target_key': target_key, 'target_id': target_id,
            'edge_type': edge_type,
            'effect': ref['effect'],
            'actions': ref['actions'],
            'is_pattern': ref['is_pattern'],
            'prefix': ref['prefix'],
            'principal_kind': ref.get('principal_kind', ''),
            'condition_key': ref.get('condition_key', ''),
            'sid': ref['sid'],
            'source': 'policy',
            'resolved': target is not None,
            # A public grant - wildcard principal with Allow - is the single
            # most important thing this mechanism finds, so it is surfaced as a
            # property of the edge rather than left to be recomputed later.
            # Public means anyone can reach it. A wildcard principal that is
            # narrowed by a condition on the caller is not that, so the
            # condition is consulted rather than only the Principal.
            'public': (ref.get('principal_kind') == 'wildcard'
                       and ref['effect'] == 'Allow'
                       and kind in ('trust', 'resource')
                       and not ref['restricted']),
            'restricted_by_condition': ref['restricted'],
        })
    return edges
