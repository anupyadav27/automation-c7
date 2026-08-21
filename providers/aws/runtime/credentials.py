"""
Whose AWS account a scan runs against.

Until this existed the answer was "whoever the process is". `Collector` fell
back to a bare `boto3.Session()`, which resolves the ambient default chain — an
instance profile, a shared config file, whatever environment variables the pod
happened to inherit. That is correct for a single-tenant tool run by the account
owner and wrong for every other case: onboard three customers and all three
scans read the same estate, ours.

This module turns an onboarded account record into a session scoped to THAT
account, and nothing else in the pipeline needs to know how.

Two credential types, deliberately unequal:

- **`iam_role`** — the customer runs our CloudFormation, which creates a
  read-only role trusting our scanner principal, pinned to an `ExternalId` we
  derive from their tenant. We hold no long-lived customer secret at all; a
  compromise of our store yields a role ARN, which is useless without the trust
  policy on their side. This is the path to prefer and the one the console
  should lead with.
- **`access_key`** — a long-lived key pair, held in Secrets Manager. Offered
  because some accounts genuinely cannot run CloudFormation, and refusing them
  means they onboard by pasting keys into something worse. It is a fallback, is
  labelled as one, and is the reason `store_credentials` never writes a secret
  to our own database.

The confused-deputy problem is the whole reason `ExternalId` exists, and it is
worth stating plainly because getting it wrong is silent: without it, anyone who
learns a customer's role ARN can ask OUR scanner to assume it on their behalf.
The external ID is a shared secret between the trust policy and us, derived
rather than invented so the customer never has to transcribe one and we never
have to store one per account.
"""
import hashlib
import hmac
import json
import os
import re

# STS session lifetime. An hour is the ceiling for a role chained from another
# role, and a scan of a large estate takes minutes, not hours — so this is
# generous rather than tight, and short enough that a leaked session token
# expires before it is useful.
SESSION_SECONDS = 3600

SESSION_NAME = "cloud-estate-scan"

#: Where a credential lives, given a tenant and an account.
SECRET_PREFIX = os.getenv("SECRETS_MANAGER_PREFIX", "cloud-estate")

CREDENTIAL_TYPES = ("iam_role", "access_key")

_ACCOUNT_RE = re.compile(r"^\d{12}$")
_ROLE_ARN_RE = re.compile(r"^arn:aws[a-z\-]*:iam::(\d{12}):role/.+$")


class CredentialError(RuntimeError):
    """A credential could not be resolved into a usable session."""


def secret_name(tenant_id: str, account_id: str) -> str:
    """The Secrets Manager name for one account's credential."""
    return f"{SECRET_PREFIX}/account/{tenant_id}/{account_id}"


def derive_external_id(tenant_id: str, secret: str | None = None) -> str:
    """
    The external ID for a tenant — deterministic, unguessable, never stored.

    HMAC rather than a random value in a column, for three reasons. It cannot
    drift out of step with what the customer's trust policy pins, because both
    sides derive it from the same input. It survives losing our database. And
    there is no per-account secret to leak, because there is no per-account
    secret — one server-side key covers every tenant.

    Deriving it also means the customer is never asked to invent or transcribe
    one: the CloudFormation template arrives with it already filled in.

    Raises rather than falling back to a constant when the key is unset. A
    predictable external ID is the same as no external ID, and the failure mode
    of "quietly not protected" is exactly the one this guards against.
    """
    key = secret if secret is not None else os.getenv("EXTERNAL_ID_SECRET", "")
    if not key:
        raise CredentialError(
            "EXTERNAL_ID_SECRET is not set — refusing to derive a predictable "
            "external ID. Set it to a random 32+ byte value, the same one on "
            "every replica, and never rotate it without re-issuing every "
            "customer's trust policy."
        )
    if not tenant_id:
        raise CredentialError("cannot derive an external ID without a tenant")
    digest = hmac.new(key.encode(), f"tenant:{tenant_id}".encode(), hashlib.sha256)
    # 32 hex chars: comfortably beyond guessing, and short enough to read back
    # over a call when someone is debugging a trust policy.
    return digest.hexdigest()[:32]


def validate_role_arn(arn: str) -> str:
    """The account number a role ARN belongs to, or an error naming the fault."""
    match = _ROLE_ARN_RE.match((arn or "").strip())
    if not match:
        raise CredentialError(
            f"not an IAM role ARN: {arn!r} — expected "
            "arn:aws:iam::<12-digit account>:role/<name>"
        )
    return match.group(1)


def validate_account_id(account_id: str) -> str:
    if not _ACCOUNT_RE.match((account_id or "").strip()):
        raise CredentialError(f"not a 12-digit AWS account id: {account_id!r}")
    return account_id.strip()


def session_from_role(role_arn, external_id, region, *, sts=None,
                      duration=SESSION_SECONDS, session_name=SESSION_NAME):
    """
    Assume a customer's read-only role and return a session scoped to it.

    `sts` is injectable so the assume-role path can be tested without a network
    or a real account — the arithmetic of turning a response into a session is
    exactly where a mistake would be silent, because a session built from the
    wrong keys still constructs fine and only fails later, deep in a collector.
    """
    import boto3

    client = sts if sts is not None else boto3.client("sts", region_name=region)
    try:
        assumed = client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            ExternalId=external_id,
            DurationSeconds=duration,
        )
    except Exception as exc:  # noqa: BLE001 — re-raised with the cause named
        raise CredentialError(
            f"could not assume {role_arn}: {exc}. The usual causes are a trust "
            "policy that does not name our scanner principal, or an ExternalId "
            "mismatch — both surface as AccessDenied and look identical."
        ) from exc

    creds = assumed.get("Credentials") or {}
    missing = [k for k in ("AccessKeyId", "SecretAccessKey", "SessionToken") if not creds.get(k)]
    if missing:
        raise CredentialError(f"assume-role returned no {', '.join(missing)}")
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def session_from_keys(access_key_id, secret_access_key, region, session_token=None):
    """A session from a long-lived key pair. The fallback path — see the header."""
    import boto3

    if not access_key_id or not secret_access_key:
        raise CredentialError("access_key credentials need both an id and a secret")
    return boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token or None,
        region_name=region,
    )


def read_secret(name, *, client=None, region=None):
    """One credential blob out of Secrets Manager."""
    import boto3

    sm = client if client is not None else boto3.client("secretsmanager", region_name=region)
    try:
        payload = sm.get_secret_value(SecretId=name)
    except Exception as exc:  # noqa: BLE001
        raise CredentialError(f"could not read credential {name}: {exc}") from exc
    raw = payload.get("SecretString")
    if not raw:
        raise CredentialError(f"credential {name} has no SecretString")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialError(f"credential {name} is not JSON") from exc


def write_secret(name, credentials, *, client=None, region=None, tags=None):
    """
    Store a credential blob, creating or updating as needed.

    Secrets Manager, never our own database. A credential in a table we own is a
    credential in every backup, every replica and every `SELECT *` a support
    engineer runs; the account row keeps only a REFERENCE, so the blast radius
    of a database compromise is a list of role ARNs rather than a set of keys.
    """
    import boto3

    sm = client if client is not None else boto3.client("secretsmanager", region_name=region)
    body = json.dumps(credentials)
    try:
        sm.create_secret(Name=name, SecretString=body, Tags=tags or [])
    except Exception:  # noqa: BLE001 — already exists is the common case
        try:
            sm.put_secret_value(SecretId=name, SecretString=body)
        except Exception as exc:  # noqa: BLE001
            raise CredentialError(f"could not store credential {name}: {exc}") from exc
    return name


def session_for(account, *, region=None, sts=None, secrets=None):
    """
    The session a scan of this account should run as.

    `account` is a row from `cloud_accounts`: it carries the credential TYPE and
    a REFERENCE, never the credential itself. Resolving the reference is this
    function's whole job, and it is the one place in the codebase that turns an
    onboarded customer into an AWS client.
    """
    account_id = validate_account_id(account.get("account_id", ""))
    tenant_id = account.get("tenant_id") or ""
    scan_region = region or account.get("region") or os.getenv("AWS_REGION")
    kind = account.get("credential_type") or "iam_role"

    if kind == "iam_role":
        role_arn = account.get("role_arn") or ""
        owner = validate_role_arn(role_arn)
        if owner != account_id:
            # A role in a different account than the one we think we are
            # scanning means the record is wrong, and every asset the scan
            # returns would be filed under the wrong customer.
            raise CredentialError(
                f"role {role_arn} belongs to account {owner}, "
                f"but this record is for {account_id}"
            )
        return session_from_role(
            role_arn,
            account.get("external_id") or derive_external_id(tenant_id),
            scan_region,
            sts=sts,
        )

    if kind == "access_key":
        blob = read_secret(
            account.get("credential_ref") or secret_name(tenant_id, account_id),
            client=secrets,
            region=scan_region,
        )
        return session_from_keys(
            blob.get("access_key_id"),
            blob.get("secret_access_key"),
            scan_region,
            blob.get("session_token"),
        )

    raise CredentialError(
        f"unknown credential type {kind!r} — expected one of {CREDENTIAL_TYPES}"
    )


def whoami(session, *, sts=None):
    """
    Who the session actually is, straight from STS.

    The validation that matters, and the only one that cannot be faked by a
    well-formed record: a role ARN that parses, an external ID that derives and
    a secret that decodes still prove nothing about whether the credential
    works. `GetCallerIdentity` needs no permissions beyond existing, so it
    cannot fail for reasons unrelated to the credential itself.
    """
    client = sts if sts is not None else session.client("sts")
    try:
        ident = client.get_caller_identity()
    except Exception as exc:  # noqa: BLE001
        raise CredentialError(f"credential does not work: {exc}") from exc
    return {"account_id": ident.get("Account"), "arn": ident.get("Arn"),
            "user_id": ident.get("UserId")}
