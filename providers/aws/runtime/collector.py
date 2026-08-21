"""
The collector — the only module in this package that calls AWS.

Everything else takes dicts and returns dicts, which is what lets the whole
relation model be tested offline. That boundary is load-bearing: if anything
other than this file needs credentials, the layering has gone wrong.

Four properties the design is built around, each responding to something that
actually goes wrong at 1800+ resource types:

  read-only by construction   the verb is checked against a whitelist before the
                              call is made, and a violation raises rather than
                              being skipped. "We only listed read operations in
                              the catalog" is not a guarantee; this is.
  memoised by call signature  the same operation with the same arguments fires
                              once. Children of a shared parent would otherwise
                              re-list it per child.
  per-call error isolation    AccessDenied is normal, not exceptional - no role
                              can read 1800 types. One denial must never abort a
                              sweep, and every failure is recorded with its
                              reason rather than swallowed.
  throttling is expected      at this volume it is certain. It appears as
                              retries, never as missing assets, because a
                              silently short inventory is the worst outcome.

Three passes: roots, then children keyed on their parents' ids, then policy
documents. Cross-account signals are harvested from every payload as it arrives.
"""

import csv
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from providers.aws.runtime import accounts as accountlib
from providers.aws.runtime import arn as arnlib
from providers.aws.runtime import policy as policylib

CATALOG = os.path.join(os.path.dirname(__file__), '..', 'catalog')

# The only verbs allowed. Anything else is a bug in the catalog, and treating it
# as one is the point. `Search` is included because AWS uses it for reads -
# SearchContacts, SearchQuantumTasks - and omitting it would abort a full sweep
# on 18 perfectly safe operations.
READ_VERBS = ('Describe', 'List', 'Get', 'BatchGet', 'Search', 'Query',
              'Scan', 'Lookup', 'Preview', 'Check', 'Test', 'Validate',
              'Estimate', 'Simulate')

THROTTLE_CODES = {'Throttling', 'ThrottlingException', 'RequestLimitExceeded',
                  'TooManyRequestsException', 'RequestThrottled',
                  'RequestThrottledException', 'SlowDown'}
# Failures that mean "not available here", not "something broke".
BENIGN_CODES = {'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation',
                'AuthFailure', 'InvalidClientTokenId', 'OptInRequired',
                'SubscriptionRequiredException', 'InvalidAction',
                'UnsupportedOperation', 'NotFoundException',
                'ResourceNotFoundException', 'NoSuchEntity',
                'InvalidParameterValueException', 'ValidationException',
                'ServiceUnavailableException', 'EndpointConnectionError'}

# Refused, as opposed to absent. Kept apart from everything else because a run
# whose coverage is limited by our own permissions must say so rather than
# reporting the estate as empty.
DENIED_CODES = {'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation',
                'AuthFailure', 'InvalidClientTokenId'}

# An exact-code set cannot keep up: AWS gives each service its own spelling of
# "that does not exist" - NoSuchBucketPolicy, RepositoryPolicyNotFoundException,
# NoSuchOriginAccessControl, LifecyclePolicyNotFoundException, NamespaceNotFound.
# 317 failures in one sweep were that sentence in 30 different spellings, all
# counted as something having gone wrong.
#
# Shape catches them, and the shape carries WHY, which the boolean never did. A
# run report saying "1056 failures" is a number nobody can act on; the same run
# split into absent / unused / transient / the rest leaves a residue small
# enough to read.
FAILURE_SHAPES = (
    # The optional thing is simply not configured. A bucket with no bucket
    # policy is not a collection problem, it is a bucket with no bucket policy.
    ('absent', re.compile(
        r'NoSuch|NotFound|DoesNotExist|NotConfigured|NotRegistered|NoProgress|'
        r'NotBroadcasting|UnknownResource|EntityNotFound', re.I)),
    # The service is not switched on in this account or region.
    ('unused', re.compile(
        r'Uninitialized|NotSubscribed|InvalidAccess|UnsupportedRegion|OptInRequired|'
        r'NotAvailableInRegion|TemplatesNotAvailable|Forbidden|NotAuthorized|'
        r'UnknownOperation|NoAuthToken', re.I)),
    # Would likely succeed on another run.
    ('transient', re.compile(
        r'Throttl|TooManyRequests|Timeout|InternalFailure|ServiceUnavailable|'
        r'InternalServerError|RequestLimitExceeded|SlowDown', re.I)),
)


def classify_failure(code, message=''):
    """
    Why a call failed, in one word: absent, unused, transient, denied — or
    'error', which is the only one worth reading.

    A sixth, `unresolved`, is set directly at the call site rather than derived
    here: it means the call was never attempted because its parent could not be
    identified. That is a coverage gap, not a failure, and it dominated the
    `error` bucket until it was named — 711 of 972.

    `denied` stays separate from `unused`: being refused a call is a fact about
    our permissions, and a run whose coverage is limited by policy should say so
    rather than reporting the estate as empty.
    """
    if code in DENIED_CODES:
        return 'denied'
    for name, pattern in FAILURE_SHAPES:
        if pattern.search(code or ''):
            return name
    if code in BENIGN_CODES:
        return 'unused'
    return 'error'

PlannedCall = namedtuple('PlannedCall', 'resource_key service operation params pass_')


class ReadOnlyViolation(RuntimeError):
    """Raised when a non-read operation reaches the collector."""


# An unpaginated sweep is unbounded in two directions at once: a single
# paginator can grind through thousands of pages, and a single slow endpoint
# can stall the whole run. Both were observed - a sweep hung at 1375/1392
# types having accumulated 104k rows, and because nothing is written until the
# end, the hang cost all of them. Caps make a run finite and honest: what was
# cut is recorded as truncation rather than silently missing.
MAX_PAGES = 20
TYPE_DEADLINE = 90.0


# Parameter names that identify nothing on their own. 53 collectable child
# types ask for a parameter called `id`; matched against every asset that has
# one, that is a cross product rather than a lookup.
#
# Consulted only when a child has NO parent in its own service and must reach
# across to another one. Within a service these names are fine - `Name` scoped
# to `ssm` is the document - so the list is a guard on borrowing, not a ban on
# the spelling.
GENERIC_PARAMS = frozenset({
    'id', 'ids', 'name', 'names', 'arn', 'arns', 'key', 'type', 'status',
    'resourcearn', 'resourceid', 'resource', 'value', 'token', 'version',
})


def _snake(name):
    """PascalCase operation name -> the snake_case boto3 method.

    Delegates to botocore's own converter. A hand-rolled regex got acronyms
    wrong - ListWebACLs became list_web_ac_ls, which is not a method, so every
    WAF web ACL in the account was silently uncollectable. boto3 builds its
    method names with this exact function, so it is the only thing guaranteed
    to agree with the client.
    """
    from botocore import xform_name
    return xform_name(name)


def _snake_to_pascal(name):
    return ''.join(part.capitalize() for part in name.split('_'))


def _load(name, key):
    path = os.path.join(CATALOG, name)
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return {r[key]: r for r in csv.DictReader(fh)}


def extract_items(response, items_for):
    """
    Pull the resource items out of a response using the catalog's items_for.

    `items_for` is a Jinja-ish marker from the vendored specs -
    `{{ response.Reservations[].Instances }}` - so the container path is walked
    rather than templated. A response whose container is absent yields nothing,
    which is normal for an empty account.
    """
    if not items_for:
        return []
    match = re.search(r'response\.([A-Za-z0-9_\[\]\.]+)', items_for)
    if not match:
        return []
    current = [response]
    for segment in match.group(1).split('.'):
        listy = segment.endswith('[]')
        key = segment[:-2] if listy else segment
        nxt = []
        for item in current:
            if not isinstance(item, dict):
                continue
            value = item.get(key)
            if value is None:
                continue
            nxt.extend(value) if isinstance(value, list) else nxt.append(value)
        current = nxt
    # Bare identifiers count. `eks.list_clusters` returns `{"clusters":
    # ["prod"]}` and `ecs.list_tasks` returns a list of ARNs - a list of names,
    # not of objects. Dropping non-dicts here meant every such type collected
    # zero, logged no failure, and was indistinguishable from an account that
    # owned none of them. EKS is running in this estate; it took three rounds
    # of "where is the cluster" to find that out.
    return [c for c in current if isinstance(c, (dict, str)) and c != '']


def load_collection_args(path=None):
    """
    Per-type arguments to pass on collection.

    Some AWS list operations default to a scope far wider than "this account".
    DescribeImages with no `Owners` returns every public AMI in the region;
    DescribeSnapshots behaves the same way; ListPolicies returns ~1600
    AWS-managed policies alongside the handful that are ours. Collecting those
    is not just noisy - it buries the actual estate and costs minutes per run.

    Kept as data rather than code so scoping a newly-noticed operation is a row.
    """
    path = path or os.path.join(CATALOG, 'collection_args.csv')
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            try:
                out[row['resource_key']] = json.loads(row['args_json'])
            except (ValueError, KeyError):
                continue
    return out


# Services whose resource policies decide exposure. At `core` scope only these
# are fetched, because a policy read costs one call PER RESOURCE and most
# services' policies say nothing about who can reach the estate.
CORE_POLICY_SERVICES = {
    'iam', 's3', 'kms', 'sqs', 'sns', 'lambda', 'secretsmanager', 'ecr',
    'efs', 'events', 'glacier', 'apigateway', 'elasticsearch', 'opensearch',
    'codeartifact', 'backup', 'organizations', 'ram',
}


def _load_policy_sources(path=None):
    """Where policy documents live, grouped by the operation that returns them."""
    path = path or os.path.join(CATALOG, 'policy_sources.csv')
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


def load_enrich_specs(path=None):
    """
    Types whose list operation returns identifiers rather than resources.

    `eks.list_clusters` gives `["onam-eks-cluster"]` and `ecs.list_services`
    gives ARNs. Keeping the bare id is enough to say the resource EXISTS - that
    fix already recovered five types - but not enough to say anything about it,
    and the fields that matter are exactly the ones that name other resources.
    An EKS node pool's `resources.autoScalingGroups` is the only collected link
    between a cluster and the EC2 instances that run it.

    So: one describe per item, declared in a catalog rather than in code, and
    only for the types that need it. This is the expensive path - N+1 calls by
    construction - which is why it is opt-in per type rather than automatic.

    A type may declare SEVERAL calls. S3 is the reason: encryption, versioning
    and the public-access block are three separate operations, none of which
    `list_buckets` returns and each of which is one field a reader asks for
    first. One spec per type silently kept the last row and dropped the rest.
    """
    path = path or os.path.join(CATALOG, 'enrich_specs.csv')
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('resource_key') and row.get('operation'):
                out.setdefault(row['resource_key'], []).append(row)
    return out


def load_collection_filters(path=None):
    """
    Client-side drop rules, for what an API cannot filter for us.

    `collection_args` narrows a call before it is made, which is always better.
    But some exclusions have no API parameter: ListRoles offers `PathPrefix`,
    which is inclusive only, so service-linked roles can be identified but not
    excluded at the source. Those are dropped here instead, and counted, so a
    filtered-out resource is visible in the run report rather than silently gone.
    """
    path = path or os.path.join(CATALOG, 'collection_filters.csv')
    if not os.path.exists(path):
        return {}
    out = defaultdict(list)
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[row['resource_key']].append(row)
    return dict(out)


FILTER_OPS = {
    'startswith': lambda v, t: str(v).startswith(t),
    'equals': lambda v, t: str(v) == t,
    'not_equals': lambda v, t: str(v) != t,
    'contains': lambda v, t: t in str(v),
    'in': lambda v, t: str(v) in t.split('|'),
}


def parse_args(required_args):
    """`resourceOwner=SELF,Scope=REGIONAL` -> {'resourceOwner': 'SELF', ...}."""
    out = {}
    for pair in (required_args or '').split(','):
        if '=' in pair:
            key, _, value = pair.partition('=')
            out[key.strip()] = value.strip()
    return out


def dedupe_by_arn(assets):
    """
    One ARN, one asset.

    A resource can be returned by several APIs. `docdb.db_instance`,
    `neptune.db_instance` and `rds.db_instance` all describe the SAME Postgres
    instance under the same ARN, because DocumentDB and Neptune are RDS-backed
    and each service lists it. Kept apart, the diagram drew three boxes in one
    subnet for one database — and the database, whose primary key is the ARN,
    silently collapsed them and reported 149 fewer rows than the collector
    found. Two components disagreeing about how many things exist.

    WHICH row survives, in order:

      1. the type whose service matches the ARN's own service segment. AWS
         states it: `arn:aws:rds:...` is an RDS thing, whatever else lists it.
      2. the richest payload. The RDS view of that instance carries 49 fields,
         Neptune's 39 and DocumentDB's 25 — the owning service tells you most.
      3. the type name, so the answer never depends on collection order.

    Returns (assets, merged) where `merged` records what was folded into what,
    so a run report can show it rather than the count quietly shrinking.
    """
    def service_of_arn(arn):
        parts = (arn or '').split(':')
        return parts[2] if len(parts) > 2 else ''

    def rank(asset):
        key = asset.get('resource_key') or ''
        service = key.split('.')[0]
        return (0 if service == service_of_arn(asset.get('arn')) else 1,
                -len(asset.get('raw') or {}),
                key)

    by_arn = defaultdict(list)
    out, merged = [], []
    for asset in assets:
        arn = asset.get('arn')
        if arn:
            by_arn[arn].append(asset)
        else:
            out.append(asset)          # no ARN, nothing to collide on

    for arn, group in by_arn.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        winner, *rest = sorted(group, key=rank)
        out.append(winner)
        merged.append({'arn': arn, 'kept': winner.get('resource_key'),
                       'folded': sorted({a.get('resource_key') for a in rest})})
    return out, merged


class Collector:
    """Collects assets for one account and region."""

    def __init__(self, region, account_id=None, account_name=None,
                 session=None, catalog=None, assets_meta=None,
                 locations=None, layers=None, max_retries=5,
                 workers=12, progress=None):
        self.region = region
        self.session = session
        self.catalog = catalog if catalog is not None else _load(
            'resource_catalog.csv', 'key')
        self.assets_meta = assets_meta if assets_meta is not None else _load(
            'asset_types.csv', 'key')
        self.locations = locations if locations is not None else _load(
            'location_paths.csv', 'resource')
        self.layers = layers if layers is not None else _load(
            'layer_assignment.csv', 'key')
        self.collection_args = load_collection_args()
        self.collection_filters = load_collection_filters()
        self.enrich_specs = load_enrich_specs()
        self.enriched = 0
        self.filtered = defaultdict(int)
        # Three ways a type can produce nothing, kept apart on purpose: it
        # failed, it answered with nothing usable, or another type had already
        # made its exact call. Collapsing them into "0 assets" is what made
        # every absence look like an empty account.
        self.barren = []
        self.skipped_calls = []
        self.merged = []
        self.policy_sources = _load_policy_sources()
        self.policy_scope = 'core'
        # Mechanism B output. Kept separate from `assets` because a policy edge
        # is a grant, not a resource - it has no ARN and no place in the tree.
        self.policy_edges = []
        self.max_retries = max_retries
        # 1845 serial round-trips is 30-60 minutes of pure waiting; the calls
        # are independent, so they run in a pool. Kept modest on purpose -
        # more workers mainly buys more throttling, which costs the retries
        # back again.
        self.workers = max(1, int(workers))
        self.progress = progress
        self._lock = threading.Lock()
        self._client_lock = threading.Lock()
        self._done = 0

        self.account_id = account_id
        self.account_name = account_name or account_id
        self.assets = []
        self.failures = []
        self.truncated = []
        self.type_counts = defaultdict(int)
        self.max_pages = MAX_PAGES
        self.calls_made = 0
        self._seen_calls = set()
        # Answers, not just the fact that a question was asked - see call().
        self._call_cache = {}
        self._clients = {}
        self.graph = None
        # Root calls that turned out to need a parent after all. See
        # _retry_candidates: AWS has operations where several parameters are
        # individually optional but at least one is mandatory, and botocore's
        # model cannot express that.
        self._needs_parent = []

    # ── planning ──────────────────────────────────────────────────────

    def _in_scope(self, row, scope, only):
        if row.get('tier') == 'excluded' or not row.get('operation'):
            return False
        if only:
            # An explicit request overrides the tier filter. Junction types such
            # as elbv2.target_health are `secondary` only because they have no
            # id of their own, yet they carry the edge that says which instances
            # sit behind a load balancer - asking for one by name must get it.
            return row['key'] in only
        if scope == 'primary':
            return row.get('tier') == 'primary'
        if scope == 'all':
            return row.get('tier') in ('primary', 'secondary')
        return True

    def plan(self, scope='primary', only=None):
        """
        The calls a collection would make, without making any.

        Root calls are known up front; child calls are not, because their count
        depends on how many parents exist. They are reported as one planned
        entry per type so the shape of the run is visible before it is paid for.
        """
        only = set(only) if only else None
        roots, children = [], []
        for key, row in sorted(self.catalog.items()):
            if not self._in_scope(row, scope, only):
                continue
            meta = self.assets_meta.get(key, {})
            # Scoping args win over selector defaults: `Scope=Local` on
            # iam.policy is a deliberate narrowing, not a fallback.
            params = {**parse_args(meta.get('required_args')),
                      **self.collection_args.get(key, {})}
            call = PlannedCall(key, row['service'], row['operation'], params,
                               'child' if meta.get('parent_params') else 'root')
            (children if call.pass_ == 'child' else roots).append(call)
        return roots, children

    # ── the guard ─────────────────────────────────────────────────────

    @staticmethod
    def assert_read_only(operation):
        """
        Refuse anything that is not a read.

        Deliberately an exception rather than a skip: a write verb reaching here
        means the catalog is wrong, and that should stop the run and be fixed,
        not be quietly tolerated.
        """
        if not _snake_to_pascal(operation).startswith(READ_VERBS):
            raise ReadOnlyViolation(
                f'{operation} is not a read operation; refusing to call it')

    # ── calling ───────────────────────────────────────────────────────

    def _client(self, service):
        # botocore clients are safe to call from several threads, but creating
        # one is not, so only creation is serialised.
        client = self._clients.get(service)
        if client is not None:
            return client
        with self._client_lock:
            if service not in self._clients:
                session = self.session
                if session is None:
                    import boto3
                    session = boto3.Session()
                    self.session = session
                from botocore.config import Config
                self._clients[service] = session.client(
                    service, region_name=self.region,
                    config=Config(connect_timeout=10, read_timeout=30,
                                  retries={'max_attempts': 3, 'mode': 'adaptive'}))
        return self._clients[service]

    def call(self, service, operation, params=None, key=''):
        """
        One read call, paginated, retried on throttling, isolated on failure.

        Returns a list of response pages. An empty list means either no results
        or a recorded failure; the two are distinguished by `self.failures`.
        """
        params = params or {}
        self.assert_read_only(operation)

        signature = (service, operation, json.dumps(params, sort_keys=True, default=str))
        with self._lock:
            seen = signature in self._seen_calls
            cached = self._call_cache.get(signature, []) if seen else None
            if not seen:
                self._seen_calls.add(signature)
        if seen:
            # Two types can legitimately share one call and read different parts
            # of the answer: `describe_alarms` returns MetricAlarms AND
            # CompositeAlarms. Returning [] to the second caller was not a
            # cache, it was data loss - it hid metric alarms completely, because
            # both catalog keys pointed at the composite path and the dedup
            # silenced the one that would have been fixed.
            #
            # So the pages are memoised and handed to every caller; each applies
            # its own items_for. True duplicates - same call AND same path - are
            # removed from the catalog instead, which is where a duplicate
            # belongs.
            #
            # Recorded outside the lock above: _record_skipped_call takes the
            # same non-reentrant lock, and calling it from inside deadlocked
            # every worker in the pool.
            self._record_skipped_call(key, service, operation)
            return cached

        try:
            client = self._client(service)
        except Exception as exc:
            self._record_failure(service, operation, exc)
            return []

        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                with self._lock:
                    self.calls_made += 1
                if client.can_paginate(operation):
                    pages, deadline = [], time.monotonic() + TYPE_DEADLINE
                    for page in client.get_paginator(operation).paginate(**params):
                        pages.append(page)
                        if len(pages) >= self.max_pages:
                            self._record_truncation(service, operation,
                                                    'page cap', len(pages))
                            break
                        if time.monotonic() > deadline:
                            self._record_truncation(service, operation,
                                                    'deadline', len(pages))
                            break
                    return self._cache(signature, pages)
                return self._cache(signature, [getattr(client, operation)(**params)])
            except Exception as exc:                     # noqa: BLE001
                code = getattr(exc, 'response', {}).get('Error', {}).get('Code', '')
                if code in THROTTLE_CODES and attempt < self.max_retries - 1:
                    # Back off and retry. Throttling must surface as latency,
                    # never as an asset that quietly does not appear.
                    time.sleep(delay)
                    delay *= 2
                    continue
                self._record_failure(service, operation, exc, code)
                return []
        return []

    def _cache(self, signature, pages):
        """Remember an answer so a second type reading it gets the same one."""
        with self._lock:
            self._call_cache[signature] = pages
        return pages

    def _optional_params(self, service, operation):
        """Optional input members of an operation, for the retry fallback."""
        try:
            model = self._client(service).meta.service_model
            wanted = operation.replace('_', '').lower()
            opn = next((o for o in model.operation_names
                        if o.replace('_', '').lower() == wanted), None)
            op = model.operation_model(opn) if opn else None
            if op is None or op.input_shape is None:
                return set()
            return set(op.input_shape.members) - set(op.input_shape.required_members)
        except Exception:
            return set()

    def _record_truncation(self, service, operation, why, pages):
        """A capped result is a known unknown, not a silent undercount."""
        with self._lock:
            self.truncated.append({'service': service, 'operation': operation,
                                   'reason': why, 'pages': pages})

    def _record_barren(self, key, row, raw, why, pass_='root'):
        """
        The call worked and produced no resource.

        Distinct from a failure, because nothing went wrong at the API, and
        distinct from an empty account, because something DID come back. Three
        separate investigations in this project - "where is the EKS cluster",
        "why no load balancer", "is S3 collected" - each ended here, and each
        time the evidence was a number that was zero for two different reasons
        with no way to tell them apart.

        `pass_` matters more than it looks. A CHILD call that finds nothing is
        usually correct - most roles have no instance profile, so 102 empty
        answers are 102 true answers. A ROOT call that finds nothing is the
        suspicious one. Undifferentiated, 740 expected blanks buried the 36
        that were defects.
        """
        with self._lock:
            self.barren.append({
                'key': key, 'service': row.get('service', ''),
                'operation': row.get('operation', ''),
                'raw_items': raw, 'reason': why, 'pass': pass_,
            })

    def _record_skipped_call(self, key, service, operation):
        """A call another type already made. Recorded, never silent."""
        with self._lock:
            self.skipped_calls.append({
                'key': key, 'service': service, 'operation': operation,
            })

    def _record_failure(self, service, operation, exc, code=''):
        code = code or getattr(exc, 'response', {}).get('Error', {}).get(
            'Code', type(exc).__name__)
        why = classify_failure(code, str(exc))
        with self._lock:
            self.failures.append({
                'service': service, 'operation': operation, 'code': code,
                'why': why, 'benign': why != 'error',
                'message': str(exc)[:200],
            })

    # ── asset building ────────────────────────────────────────────────

    def _identity(self, key, item, parent_asset_id=None):
        """
        (asset_id, arn, arn_source, resource_id) for one raw item.

        `parent_asset_id` matters only when no ARN can be built. A child's id is
        often unique within its parent and nowhere else: two API gateways each
        have a stage called `$default`, and keyed on the name alone they
        collapsed into one node - two real resources drawn as one, with no
        error anywhere.
        """
        row = self.catalog.get(key, {})
        recipe = {
            'resource': key, 'service': row.get('service', ''),
            'id_field': row.get('id_field', ''),
            'arn_field': row.get('arn_field', ''),
            'arn_type': row.get('arn_type', ''),
            'arn_separator': row.get('arn_separator') or '/',
            'global_resource': row.get('global_resource', 'false'),
            'has_arn': 'false' if row.get('arn_strategy') == 'none' else 'true',
            'id_prefix': row.get('id_prefix', ''),
        }
        # Dotted, because some APIs wrap the resource: `xray.list_sampling_rules`
        # returns `{SamplingRule: {RuleName, RuleARN}, CreatedAt, ...}`, and a
        # flat lookup finds nothing at all - the same silent no-asset-built
        # failure that lost 228 security group rules.
        rid = self._field(item, row['id_field']) if row.get('id_field') else None
        try:
            arn = arnlib.build(recipe, item, self.region, self.account_id)
        except arnlib.NoArnForResource:
            arn = None

        if arn:
            return arn, arn, row.get('arn_strategy', ''), rid
        if rid is not None:
            # No ARN obtainable: a synthetic key keeps the asset addressable and
            # is flagged so nothing mistakes it for a real AWS ARN.
            scope = f'{parent_asset_id}/' if parent_asset_id else ''
            synthetic = (f'aws:{row.get("service", "")}:{self.region}:'
                         f'{self.account_id}:{key}/{scope}{rid}')
            return synthetic, None, 'synthetic', rid
        return None, None, '', None

    def _name(self, item, row):
        tags = item.get('Tags') or item.get('tags') or []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict) and tag.get('Key') in ('Name', 'name'):
                    return tag.get('Value')
        elif isinstance(tags, dict) and tags.get('Name'):
            return tags['Name']
        name_field = row.get('name_field') or ''
        if name_field and item.get(name_field):
            return item[name_field]
        # Not every type declares a name field, so fall back to the obvious
        # spellings before giving up and showing an opaque id.
        stem = (row.get('resource_name') or '').replace('_', '')
        for candidate in (f'{stem}Name', 'Name', 'name', 'DisplayName', 'Title'):
            value = item.get(candidate)
            if isinstance(value, str) and value:
                return value
        return None

    def _tags(self, item):
        tags = item.get('Tags') or item.get('tags') or []
        if isinstance(tags, list):
            return {t['Key']: t.get('Value', '') for t in tags
                    if isinstance(t, dict) and 'Key' in t}
        return tags if isinstance(tags, dict) else {}

    def _zone(self, key, item):
        rule = self.locations.get(self.catalog.get(key, {}).get('c7n_name', ''))
        if not rule or not rule.get('az_path'):
            return None
        from providers.aws.runtime.resolver import resolve_path
        found = resolve_path(item, rule['az_path'])
        return found[0] if found else None

    def build_asset(self, key, item, discovered_by='', parent_asset_id=None):
        """One raw response item -> one asset record. None if unidentifiable."""
        row = self.catalog.get(key, {})
        asset_id, arn, arn_source, rid = self._identity(key, item, parent_asset_id)
        if not asset_id:
            return None
        layer = self.layers.get(key, {})
        return {
            'asset_id': asset_id, 'arn': arn, 'arn_source': arn_source,
            'resource_key': key, 'resource_name': row.get('resource_name', ''),
            'service': row.get('service', ''), 'cfn_type': row.get('cfn_type', ''),
            'id': str(rid) if rid is not None else '',
            'name': self._name(item, row) or (str(rid) if rid is not None else ''),
            'account_id': self.account_id, 'account_name': self.account_name,
            'region': '' if row.get('global_resource') == 'true' else self.region,
            'availability_zone': self._zone(key, item) or '',
            'tags': self._tags(item),
            'layer_id': layer.get('layer_id', ''),
            'layer_name': layer.get('layer_name', ''),
            'overlay_group': layer.get('overlay_group', ''),
            # A foreign owner is the signal that this resource is shared to us
            # rather than ours - the central-network model depends on it.
            'owner_account': accountlib.external_owner({'raw': item}, self.account_id) or '',
            'parent_asset_id': parent_asset_id or '',
            'discovered_by': discovered_by,
            'raw': item,
        }

    # ── the passes ────────────────────────────────────────────────────

    @staticmethod
    def _field(item, path):
        """
        Read a possibly-dotted field out of a payload.

        Lifecycle state is nested on several types - an instance carries
        `State.Name`, not `State` - and a flat lookup silently returned None for
        those, so the rule never fired and the filter looked like it worked.
        """
        value = item
        for part in path.split('.'):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _filtered_out(self, key, item):
        """True when a drop rule matches. Counted so nothing vanishes silently."""
        for rule in self.collection_filters.get(key, ()):
            value = self._field(item, rule['field'])
            if value is None:
                continue
            test = FILTER_OPS.get(rule['op'])
            if test and test(value, rule['value']) and rule['action'] == 'drop':
                self.filtered[f"{key}:{rule['field']} {rule['op']} {rule['value']}"] += 1
                return True
        return False

    def _as_item(self, key, value):
        """
        A bare identifier, as the item the rest of the pipeline expects.

        `list_clusters` gives a name and `list_tasks` gives an ARN, so which
        field it belongs in is decided by the value, not by the operation - an
        `arn:` prefix is unambiguous and nothing else is. The catalog already
        says which field carries the id for this type, so the wrap uses that
        rather than inventing a key the ARN recipe would not find.

        This is deliberately minimal. It records that the resource EXISTS, which
        is the difference between a diagram missing a cluster and a diagram
        missing a cluster's tags. Enriching it needs a describe call per item -
        real work, tracked separately.
        """
        if isinstance(value, dict):
            return value
        row = self.catalog.get(key, {})
        if str(value).startswith('arn:'):
            return {row.get('arn_field') or 'arn': value, 'name': str(value).rsplit('/', 1)[-1]}
        field = row.get('id_field') or 'name'
        return {field: value, 'name': value} if field != 'name' else {'name': value}

    def _collect_type(self, key, params=None, parent_asset_id=None):
        row = self.catalog[key]
        # Scoping args apply on every path into this type, including the child
        # retry - otherwise a type narrowed at plan time widens again on retry.
        scoped = self.collection_args.get(key)
        if scoped:
            params = {**scoped, **(params or {})}
        before = len(self.failures)
        pages = self.call(row['service'], row['operation'], params, key=key)

        # A validation error on a call we made with no arguments means the
        # operation needs one after all. `DescribeListeners` accepts either
        # ListenerArns or LoadBalancerArn, each optional on its own but not
        # together - a shape botocore has no way to declare. Rather than
        # hardcode the exception, note it and retry the type as a child once
        # its potential parents have been collected.
        if not params and len(self.failures) > before:
            failure = self.failures[-1]
            if 'Validation' in failure['code'] or 'MissingParameter' in failure['code']:
                self._needs_parent.append(key)
        found, raw = [], 0
        for page in pages:
            for item in extract_items(page, row.get('items_for')):
                raw += 1
                item = self._as_item(key, item)
                if self._filtered_out(key, item):
                    continue
                asset = self.build_asset(
                    key, item, f"{row['service']}.{row['operation']}",
                    parent_asset_id)
                if asset:
                    found.append(asset)
        # A call that answered and yielded nothing usable is NOT an empty
        # account. Recorded so it shows up in the run summary, because this is
        # the failure mode that hides an entire service without ever raising.
        self._enrich(key, found, parent_asset_id)
        pass_ = 'child' if parent_asset_id else 'root'
        if pages and raw and not found:
            self._record_barren(key, row, raw,
                                'items extracted but no asset built', pass_)
        elif pages and not raw:
            self._record_barren(key, row, 0,
                                f"items_for {row.get('items_for')!r} matched nothing", pass_)
        return found

    def _readdress(self, key, asset):
        """
        Adopt the real ARN once enrichment has produced it.

        A type can declare an `arn_field` its LIST call never returns. `arn.build`
        says so itself — "the field is declared but some responses omit it" — and
        falls through to constructing one from the id. For SQS that id is a queue
        URL, so the constructed ARN came out as
        `arn:aws:sqs:region:account:https://sqs.../my-queue`: a string that is not
        an ARN, used as the identity key and shown on the panel.

        The describe now returns the field for real, and this runs before the
        asset joins `self.assets` or any child points at it, so the correction is
        free. Only ever upgrades a constructed ARN to a declared one.
        """
        arn_field = (self.catalog.get(key) or {}).get('arn_field')
        if not arn_field:
            return
        real = asset['raw'].get(arn_field)
        if not real or not str(real).startswith('arn:') or real == asset['arn']:
            return
        if asset['asset_id'] == asset['arn']:
            asset['asset_id'] = real
        asset['arn'] = real
        asset['arn_source'] = 'field'

    def _enrich(self, key, assets, parent_asset_id=None):
        """
        Fill in a type whose list gave only identifiers.

        One describe per asset, so this is N+1 by construction and deliberately
        opt-in per type. A failure enriches nothing and loses nothing: the
        asset keeps the id it already had, which is still the truth that it
        exists.
        """
        specs = self.enrich_specs.get(key)
        if not specs or not assets:
            return
        parent_id = ''
        if parent_asset_id:
            # Children are keyed by their parent's own id, not its ARN: EKS
            # wants `clusterName`, and the ARN is not a name.
            parent = next((a for a in self.assets
                           if a['asset_id'] == parent_asset_id), None)
            parent_id = (parent or {}).get('id', '')
        for spec in specs:
         for asset in assets:
             # Explicit substitution, not str.format: the params ARE JSON, so
             # their own braces would be read as format placeholders.
             params = spec['params']
             for token, value in (('{id}', asset['id']),
                                  ('{parent_id}', parent_id),
                                  ('{arn}', asset.get('arn') or '')):
                 params = params.replace(token, str(value))
             try:
                 pages = self.call(self.catalog[key]['service'],
                                   spec['operation'], json.loads(params), key=key)
             except Exception as exc:                         # noqa: BLE001
                 # Enriching is best-effort by design: the asset keeps the id
                 # that identified it, which is still the truth that it exists.
                 self._record_failure(self.catalog[key]['service'],
                                      spec['operation'], exc)
                 continue
             for page in pages:
                 items = extract_items(page, spec['items_for']) or \
                         ([page] if spec['items_for'].strip('{} ') == 'response' else [])
                 for item in items:
                     if isinstance(item, dict):
                         # The list result is the skeleton; describe fills it in
                         # without overwriting the id that identified it.
                         before = set(asset['raw'])
                         asset['raw'] = {**item, **asset['raw']} \
                             if len(asset['raw']) > 2 else {**asset['raw'], **item}
                         # Which call earned which field. Once merged the payload
                         # is flat and a reader cannot tell a free field from one
                         # that cost a second API call — but the panel catalog
                         # has to cite a source, so record it while it is known.
                         gained = sorted(set(asset['raw']) - before)
                         if gained:
                             asset.setdefault('enriched_by', {})[spec['operation']] = gained
                         self._readdress(key, asset)
                         self.enriched += 1
                     break
                 break

    def collect(self, scope='primary', only=None, with_children=True):
        """Run the collection. Returns self so callers can read the results."""
        if self.account_id is None:
            self._resolve_identity()
        self.graph = accountlib.AccountGraph(self.account_id)

        roots, children = self.plan(scope, only)

        self._run_pool(roots, len(roots), 'roots')

        self._collect_policies()

        if with_children:
            self._collect_children(children)
            # Types that failed as roots because they needed a parameter. Their
            # parents exist by now, so they can be attempted properly.
            if self._needs_parent:
                self._collect_children(self._retry_candidates())
        self.assets, self.merged = dedupe_by_arn(self.assets)
        return self

    def _run_pool(self, calls, total, label):
        """Execute a batch of type collections concurrently."""
        if not calls:
            return
        self._done = 0

        def one(call):
            found = self._collect_type(call.resource_key, call.params)
            with self._lock:
                self.type_counts[call.resource_key] += len(found)
                for asset in found:
                    self.assets.append(asset)
                    accountlib.scan_asset(self.graph, asset)
                self._done += 1
                done = self._done
            self._report(label, done, total)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(as_completed(pool.submit(one, c) for c in calls))

    def _report(self, label, done, total):
        """Progress to stderr. A 30-minute silent run is indistinguishable from a hang."""
        if self.progress is False:
            return
        if done % 25 and done != total:
            return
        line = (f'  {label}: {done}/{total} · {len(self.assets)} assets · '
                f'{self.calls_made} calls · {len(self.failures)} failures')
        if self.barren:
            line += f' · {len(self.barren)} barren'
        if callable(self.progress):
            self.progress(line)
        else:
            print(line, file=sys.stderr, flush=True)

    def _collect_policies(self):
        """
        Fetch and parse policy documents — mechanism B.

        Two shapes. A source with no required parameters is a single call whose
        response carries many documents (GetAccountAuthorizationDetails returns
        every role, user and group with their inline and trust policies). One
        with required parameters is per-resource, so it is driven from the
        assets already collected.

        Edges are emitted even when the referenced ARN is not in this account:
        a grant to something we did not collect is a finding, not noise.
        """
        if self.policy_scope == 'none':
            return
        sources = self.policy_sources
        if self.policy_scope == 'core':
            sources = [s for s in sources if s['service'] in CORE_POLICY_SERVICES]

        # Root-level sources first: one call each, and
        # GetAccountAuthorizationDetails alone returns every role, user and
        # group with their inline and trust policies.
        for source in sources:
            required = [p for p in (source.get('requires_params') or '').split(',') if p]
            kind, encoding = source['kind'], source['encoding']

            if not required:
                pages = self.call(source['service'], _snake(source['operation']))
                for page in pages:
                    self._parse_policy_payload(page, source, kind, encoding)
                continue

            # Per-resource: match the required parameter against collected ids.
            if len(required) != 1:
                continue
            param = required[0]

            targets = []
            for asset in list(self.assets):
                row = self.catalog.get(asset['resource_key'], {})
                value = None
                if param in ('Bucket', 'BucketName') and asset['resource_key'] == 's3.bucket':
                    value = asset['id']
                elif param.endswith('Arn') and asset.get('arn'):
                    if row.get('service') == source['service']:
                        value = asset['arn']
                elif row.get('id_field') == param:
                    value = asset['id']
                if value:
                    targets.append((asset, value))
            if not targets:
                continue

            # One call per resource, run in the pool. Serially this is the
            # single slowest thing the collector does - it scales with asset
            # count, not with type count.
            def fetch(pair, _src=source, _param=param, _kind=kind, _enc=encoding):
                asset, value = pair
                pages = self.call(_src['service'], _snake(_src['operation']),
                                  {_param: value})
                return [(page, _src, _kind, _enc, asset) for page in pages]

            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                for future in as_completed(pool.submit(fetch, t) for t in targets):
                    for page, src, knd, enc, holder in future.result():
                        self._parse_policy_payload(page, src, knd, enc, holder=holder)
            self._report(f"policies:{source['service']}", len(targets), len(targets))

    def _parse_policy_payload(self, page, source, kind, encoding, holder=None):
        """Pull documents out of one response and turn each into edges."""
        from providers.aws.runtime.resolver import resolve_path

        documents = resolve_path(page, source['document_path'])
        if not documents and holder is not None:
            # Single-document responses (GetBucketPolicy) put it at the root.
            leaf = source['document_path'].split('.')[-1].replace('[]', '')
            if page.get(leaf):
                documents = [page[leaf]]

        for document in documents:
            key = holder['resource_key'] if holder else source['service']
            ident = holder['id'] if holder else source['operation']
            edges = policylib.derive_edges(key, ident, document, kind,
                                           raw_encoding=encoding)
            for edge in edges:
                edge['holder_asset_id'] = holder['asset_id'] if holder else ''
                edge['policy_source'] = f"{source['service']}.{source['operation']}"
                with self._lock:
                    self.policy_edges.append(edge)
        if self.graph and self.policy_edges:
            accountlib.scan_policy_edges(self.graph, self.policy_edges)

    def _retry_candidates(self):
        """
        Turn root types that demanded a parameter into child calls.

        The parameter to use is chosen from the operation's optional members by
        matching against ids we have actually collected, so no per-service
        knowledge is needed and a type with no viable parent is simply reported.
        """
        collected_fields = set()
        for asset in self.assets:
            row = self.catalog.get(asset['resource_key'], {})
            if row.get('id_field'):
                collected_fields.add(row['id_field'])
            if asset.get('arn'):
                collected_fields.add(f"{row.get('resource_name', '')}Arn")

        out = []
        for key in self._needs_parent:
            row = self.catalog[key]
            options = self._optional_params(row['service'], row['operation'])
            match = sorted(options & collected_fields)
            if not match:
                self.failures.append({
                    'service': row['service'], 'operation': row['operation'],
                    'code': 'NoParentAvailable', 'benign': True, 'why': 'unresolved',
                    'message': f'needs one of {sorted(options)[:4]}; none collected',
                })
                continue
            self.assets_meta.setdefault(key, {})
            self.assets_meta[key] = {**self.assets_meta.get(key, {}),
                                     'parent_params': match[0]}
            out.append(PlannedCall(key, row['service'], row['operation'], {}, 'child'))
        self._needs_parent = []
        return out

    def _collect_children(self, children):
        """
        Fetch child types once their parents are known.

        A child's required parameter is matched against the ids already
        collected: the parameter name is looked up among every asset's id and
        ARN fields, so `TargetGroupArn` finds target groups without any
        per-service wiring.
        """
        # Keys are matched case-insensitively and by convention, because AWS
        # spells the same idea three ways: `eks.list_nodegroups` wants
        # `clusterName`, the cluster's own id field is `name`, and nothing
        # connects the two by string equality. `<Resource>Arn` was already
        # handled this way; `<Resource>Name` and `<Resource>Id` are the same
        # convention and were missing, which is why two real EKS nodegroups
        # never collected and nothing said so.
        by_param = defaultdict(list)

        def register(name, value, asset_id, service, qualified=True):
            # Every asset is indexed WITH the service that owns it, because the
            # service is what makes a generic name safe. `Name` on its own is
            # meaningless - 80 services declare an id_field of `Name` - but
            # "`Name`, from ssm" is exactly the document an
            # `ssm.list_document_versions` call is asking for. The scoping is
            # applied at lookup, not here, so a generic name is still available
            # to its own service.
            if not name or not value:
                return
            by_param[name.lower() if qualified else name].append((value, asset_id, service))

        for asset in self.assets:
            row = self.catalog.get(asset['resource_key'], {})
            noun = row.get('resource_name', '')
            svc = row.get('service') or asset['resource_key'].split('.')[0]
            register(row.get('id_field'), asset['id'], asset['asset_id'], svc, qualified=False)
            register(f'{noun}Id', asset['id'], asset['asset_id'], svc)
            register(f'{noun}Name', asset.get('name') or asset['id'], asset['asset_id'], svc)
            if asset.get('arn'):
                register(f'{noun}Arn', asset['arn'], asset['asset_id'], svc)
                register(f'{noun}ResourceArn', asset['arn'], asset['asset_id'], svc)

        child_done = 0
        for call in children:
            meta = self.assets_meta.get(call.resource_key, {})
            wanted = [p for p in (meta.get('parent_params') or '').split(',') if p]
            if len(wanted) != 1:
                # Two or more parent ids means a cross product we will not guess
                # at. Recorded so the gap is visible rather than silent.
                self.failures.append({
                    'service': call.service, 'operation': call.operation,
                    'code': 'UnresolvedParent', 'benign': True, 'why': 'unresolved',
                    'message': f'needs {wanted or "unknown"}; not attempted',
                })
                child_done += 1
                continue
            param = wanted[0]
            # Exact spelling first, then the noun-qualified convention.
            candidates = [c for c in
                          (by_param.get(param) or by_param.get(param.lower()) or [])
                          if c[0]]
            # A child belongs to its parent's service, and that is what makes a
            # generic parameter name usable. `ssm.list_document_versions` asks
            # for `Name`; scoped to `ssm` that is the document, and unscoped it
            # was the name of anything in the account that had one - 136 calls
            # for documents SSM had never heard of. `fms.list_compliance_status`
            # asked for `PolicyId` and was fed 21-character ids where FMS wants
            # 36, and `connect.traffic_distribution` asked for `Id`, which 101
            # services declare.
            same = [c for c in candidates if c[2] == call.service]
            if same:
                targets = [(v, pid) for v, pid, _ in same]
            else:
                # No parent in this service. Cross-service parents are real - a
                # Glacier vault is keyed on an `accountId` nothing in `glacier`
                # provides - but only where the name identifies one thing. Two
                # conditions: exactly ONE service offers it, and the name is not
                # one of the bare forms that identify nothing anywhere.
                offering = {c[2] for c in candidates}
                unambiguous = len(offering) == 1 and param.lower() not in GENERIC_PARAMS
                targets = [(v, pid) for v, pid, _ in candidates] if unambiguous else []
                if candidates and not targets:
                    self.failures.append({
                        'service': call.service, 'operation': call.operation,
                        'code': 'AmbiguousParent', 'benign': True, 'why': 'unresolved',
                        'message': f'{param!r} is offered by {len(offering)} service(s), '
                                   f'none of them {call.service}; not attempted',
                    })
            if not targets:
                # No parent carries this value. Sometimes true - no clusters
                # means no nodegroups - and sometimes a naming mismatch, which
                # is exactly what hid the EKS nodegroups. Either way it is a
                # type that produced nothing, so it is recorded as one.
                self._record_barren(call.resource_key,
                                    {'service': call.service, 'operation': call.operation},
                                    0, f'no collected asset carries {param!r}', 'child')
                child_done += 1
                continue

            def fetch(pair, _call=call, _param=param):
                value, parent_id = pair
                params = {**_call.params, _param: value}
                return self._collect_type(_call.resource_key, params, parent_id)

            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                for future in as_completed(pool.submit(fetch, t) for t in targets):
                    try:
                        produced = future.result()
                    except Exception as exc:               # noqa: BLE001
                        # One bad parent must not end the pass.
                        self._record_failure(call.service, call.operation, exc)
                        continue
                    with self._lock:
                        self.type_counts[call.resource_key] += len(produced)
                        for asset in produced:
                            self.assets.append(asset)
                            accountlib.scan_asset(self.graph, asset)
            child_done += 1
            self._report('children', child_done, len(children))

    def _resolve_identity(self):
        """Account id from STS, and the account name where it is readable."""
        try:
            self.account_id = self._client('sts').get_caller_identity()['Account']
        except Exception as exc:
            self._record_failure('sts', 'GetCallerIdentity', exc)
            self.account_id = 'unknown'
        if self.account_name:
            return
        try:
            aliases = self._client('iam').list_account_aliases().get(
                'AccountAliases') or []
            self.account_name = aliases[0] if aliases else self.account_id
        except Exception:
            self.account_name = self.account_id

    # ── reporting ─────────────────────────────────────────────────────

    def summary(self):
        by_type = defaultdict(int)
        by_arn_source = defaultdict(int)
        for asset in self.assets:
            by_type[asset['resource_key']] += 1
            by_arn_source[asset['arn_source'] or 'none'] += 1
        by_code = defaultdict(int)
        for failure in self.failures:
            by_code[failure['code']] += 1
        return {
            'account_id': self.account_id, 'account_name': self.account_name,
            'region': self.region,
            'assets': len(self.assets),
            'types_with_assets': len(by_type),
            'calls_made': self.calls_made,
            'failures': len(self.failures),
            'benign_failures': sum(1 for f in self.failures if f['benign']),
            # Why they failed, not just how many. `error` is the only bucket
            # that means something is wrong with us rather than with the estate.
            'failures_by_reason': dict(sorted(Counter(
                f.get('why', 'error') for f in self.failures).items())),
            'accounts_discovered': len(self.graph) if self.graph else 0,
            'filtered_out': dict(self.filtered),
            'policy_edges': len(self.policy_edges),
            'public_grants': sum(1 for e in self.policy_edges if e.get('public')),
            'by_arn_source': dict(by_arn_source),
            'failures_by_code': dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
            'top_types': dict(sorted(by_type.items(), key=lambda kv: -kv[1])[:20]),
            # Where a cap bit. Any type listed here is an undercount, and
            # saying so is the difference between a bounded run and a wrong one.
            'truncated': len(self.truncated),
            'truncated_types': sorted({f"{t['service']}.{t['operation']}"
                                       for t in self.truncated}),
            # A type that answered and produced nothing usable. Every one of
            # these is a service that looks absent and is not, so it belongs in
            # the summary next to the counts, not in a log nobody opens.
            'barren': len(self.barren),
            # Root blanks are the ones worth looking at. A child call that
            # finds nothing is usually just a parent that has none.
            'barren_root': sum(1 for b in self.barren if b['pass'] == 'root'),
            'barren_root_types': sorted({b['key'] for b in self.barren
                                         if b['pass'] == 'root'}),
            'barren_types': sorted({b['key'] for b in self.barren}),
            # A call another type already made. Harmless in itself; the point
            # is that it is now countable rather than presenting as zero.
            'skipped_calls': len(self.skipped_calls),
            # One ARN returned by several services. Reported rather than left to
            # be noticed as a shrinking count.
            'merged_arns': len(getattr(self, 'merged', []) or []),
            'skipped_types': sorted({c['key'] for c in self.skipped_calls if c['key']}),
        }
