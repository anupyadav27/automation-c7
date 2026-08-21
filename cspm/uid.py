"""
Resource identity, across providers.

`resource_uid` is the one field every engine joins on, so it has to mean the
same thing everywhere. Each cloud already has a canonical identifier, and they
look nothing alike:

    aws         arn:aws:s3:::my-bucket
    azure       /subscriptions/{sub}/resourceGroups/{rg}/providers/
                Microsoft.Compute/virtualMachines/{name}
    gcp         //compute.googleapis.com/projects/{p}/zones/{z}/instances/{i}
    oci         ocid1.instance.oc1.phx.aaaaaaaa...
    kubernetes  {cluster}/{namespace}/{kind}/{name}

Rather than inventing a synthetic key, each provider's native identifier *is*
the uid. That way a uid pasted from a console, a bill or an audit log resolves
without translation, which a synthetic key never would.

Kubernetes is the exception that proves the rule: it has no globally unique
identifier at all, so one is composed - and `quality` records that it was
composed rather than read.

**Quality matters as much as the value.** An identifier assembled from parts is
not the same evidence as one the API returned, and a join that silently mixes
the two produces confident wrong answers. Every uid carries how it was arrived
at:

    real       the provider returned it in a field
    derived    built from parts the provider returned, to a documented rule
    synthetic  composed by us because the provider has no identifier
    none       could not be established
"""
import re

QUALITIES = ('real', 'derived', 'synthetic', 'none')

# Enough to tell a well-formed identifier from a truncated or invented one.
# Deliberately loose about the internals: providers add resource kinds
# constantly, and a pattern tight enough to enumerate them would reject
# tomorrow's resources.
PATTERNS = {
    'aws': re.compile(r'^arn:[a-z0-9-]+:[a-z0-9-]*:[a-z0-9-]*:\d{0,12}:.+'),
    'azure': re.compile(r'^/subscriptions/[^/]+/', re.I),
    'gcp': re.compile(r'^//[a-z0-9.-]+/projects/[^/]+/'),
    'oci': re.compile(r'^ocid1\.[a-z0-9]+\.'),
    'ibm': re.compile(r'^crn:v\d+:[a-z0-9-]*:'),
    'kubernetes': re.compile(r'^[^/]+/[^/]*/[^/]+/[^/]+$'),
}


def looks_valid(provider, uid):
    """Whether a uid is well formed for its provider."""
    if not uid:
        return False
    pattern = PATTERNS.get(provider)
    return bool(pattern.match(uid)) if pattern else True


def account_of(provider, uid):
    """
    The owning account/subscription/project, read from the uid itself.

    This is how cross-account and cross-subscription sharing is detected
    without a second API call: an identifier whose account segment is not the
    one being scanned came from somewhere else.
    """
    if not uid:
        return ''
    try:
        if provider == 'aws':
            parts = uid.split(':', 5)
            return parts[4] if len(parts) > 4 else ''
        if provider == 'azure':
            parts = uid.strip('/').split('/')
            return parts[1] if len(parts) > 1 and parts[0].lower() == 'subscriptions' else ''
        if provider == 'gcp':
            match = re.search(r'/projects/([^/]+)', uid)
            return match.group(1) if match else ''
        if provider == 'oci':
            # An OCID names its tenancy only in the long form; the short form
            # carries no account at all, so say so rather than guess.
            return ''
        if provider == 'kubernetes':
            return uid.split('/', 1)[0]
    except (IndexError, AttributeError):
        return ''
    return ''


def region_of(provider, uid):
    """The region segment, where the provider's identifier carries one."""
    if not uid:
        return ''
    if provider == 'aws':
        parts = uid.split(':', 5)
        return parts[3] if len(parts) > 3 else ''
    if provider == 'gcp':
        match = re.search(r'/(?:zones|locations|regions)/([^/]+)', uid)
        return match.group(1) if match else ''
    # Azure resource IDs do not carry the region; it comes from the resource
    # body. OCIDs carry a region abbreviation that needs a lookup table.
    return ''


def kubernetes_uid(cluster, namespace, kind, name):
    """Compose an identifier for a provider that has none.

    Always `synthetic` - Kubernetes objects have a UID, but it changes when an
    object is recreated, so it cannot be the key that tracks a resource across
    scans.
    """
    return f'{cluster}/{namespace or ""}/{kind}/{name}'


def grade(provider, uid, source):
    """
    (uid, quality) for one resource.

    `source` is how the collector obtained it: 'field' when the provider
    returned it, 'construct'/'derive' when it was assembled, 'synthetic' when
    composed. An identifier that does not match its provider's shape is graded
    `none` however it was obtained - a malformed uid joins to nothing, and
    saying it is real would hide that.
    """
    if not uid:
        return '', 'none'
    if not looks_valid(provider, uid):
        return uid, 'none'
    if source == 'field':
        return uid, 'real'
    if source in ('construct', 'derive', 'parent'):
        return uid, 'derived'
    return uid, 'synthetic'
