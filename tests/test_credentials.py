"""
What a scan runs as.

The failure this file guards against is silent by nature: a session built from
the wrong credentials constructs perfectly well and only misbehaves later, deep
inside a collector, as an empty result or — far worse — as another tenant's
estate filed under this one's name.
"""
import json

import pytest

from providers.aws.runtime import credentials as cred


class FakeSTS:
    """An STS that hands back predictable keys and records what it was asked."""

    def __init__(self, account="111122223333", fail=None):
        self.calls = []
        self.account = account
        self.fail = fail

    def assume_role(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError(self.fail)
        return {"Credentials": {"AccessKeyId": "ASIA_TEST",
                                "SecretAccessKey": "secret",
                                "SessionToken": "token"}}

    def get_caller_identity(self):
        if self.fail:
            raise RuntimeError(self.fail)
        return {"Account": self.account, "Arn": f"arn:aws:sts::{self.account}:assumed-role/x/y",
                "UserId": "AROATEST:y"}


class FakeSecrets:
    def __init__(self, store=None, fail=None):
        self.store = dict(store or {})
        self.fail = fail
        self.written = {}

    def get_secret_value(self, SecretId):  # noqa: N803 — boto3's casing
        if self.fail:
            raise RuntimeError(self.fail)
        if SecretId not in self.store:
            raise RuntimeError(f"ResourceNotFoundException: {SecretId}")
        return {"SecretString": self.store[SecretId]}

    def create_secret(self, Name, SecretString, Tags=None):  # noqa: N803
        if Name in self.store:
            raise RuntimeError("ResourceExistsException")
        self.store[Name] = SecretString
        self.written[Name] = SecretString

    def put_secret_value(self, SecretId, SecretString):  # noqa: N803
        self.store[SecretId] = SecretString
        self.written[SecretId] = SecretString


# ── external id ───────────────────────────────────────────────────────

def test_external_id_is_stable_for_a_tenant():
    a = cred.derive_external_id("t-1", secret="k" * 32)
    b = cred.derive_external_id("t-1", secret="k" * 32)
    assert a == b


def test_external_id_differs_between_tenants():
    # Sharing one across tenants would let any customer assume any other's role
    # through us, which is the exact confused-deputy hole ExternalId closes.
    a = cred.derive_external_id("t-1", secret="k" * 32)
    b = cred.derive_external_id("t-2", secret="k" * 32)
    assert a != b


def test_external_id_changes_with_the_server_secret():
    assert cred.derive_external_id("t-1", secret="a" * 32) != \
           cred.derive_external_id("t-1", secret="b" * 32)


def test_external_id_refuses_to_be_predictable(monkeypatch):
    """A derivable-by-anyone external ID is the same as none at all."""
    monkeypatch.delenv("EXTERNAL_ID_SECRET", raising=False)
    with pytest.raises(cred.CredentialError, match="EXTERNAL_ID_SECRET"):
        cred.derive_external_id("t-1")


def test_external_id_needs_a_tenant():
    with pytest.raises(cred.CredentialError):
        cred.derive_external_id("", secret="k" * 32)


# ── shape checks ──────────────────────────────────────────────────────

def test_role_arn_yields_its_account():
    assert cred.validate_role_arn(
        "arn:aws:iam::111122223333:role/CloudEstateScan") == "111122223333"


@pytest.mark.parametrize("bad", [
    "", "not-an-arn", "arn:aws:iam::123:role/x",
    "arn:aws:iam::111122223333:user/x",
])
def test_bad_role_arns_are_named_not_guessed(bad):
    with pytest.raises(cred.CredentialError):
        cred.validate_role_arn(bad)


@pytest.mark.parametrize("bad", ["", "12345", "abcdefghijkl", "1111222233334"])
def test_bad_account_ids_are_rejected(bad):
    with pytest.raises(cred.CredentialError):
        cred.validate_account_id(bad)


# ── assume role ───────────────────────────────────────────────────────

def test_assume_role_passes_the_external_id():
    sts = FakeSTS()
    cred.session_from_role("arn:aws:iam::111122223333:role/R", "ext-123",
                           "ap-south-1", sts=sts)
    assert sts.calls[0]["ExternalId"] == "ext-123"
    assert sts.calls[0]["RoleArn"] == "arn:aws:iam::111122223333:role/R"


def test_assume_role_failure_names_the_likely_cause():
    sts = FakeSTS(fail="AccessDenied")
    with pytest.raises(cred.CredentialError, match="ExternalId mismatch|trust policy"):
        cred.session_from_role("arn:aws:iam::111122223333:role/R", "e",
                               "ap-south-1", sts=sts)


def test_assume_role_rejects_a_response_missing_keys():
    class Empty(FakeSTS):
        def assume_role(self, **kwargs):
            return {"Credentials": {"AccessKeyId": "A"}}

    with pytest.raises(cred.CredentialError, match="SecretAccessKey"):
        cred.session_from_role("arn:aws:iam::111122223333:role/R", "e",
                               "ap-south-1", sts=Empty())


# ── session_for: the one door from a record to a client ───────────────

def test_session_for_role_account_uses_assume_role():
    sts = FakeSTS()
    account = {"account_id": "111122223333", "tenant_id": "t-1",
               "credential_type": "iam_role",
               "role_arn": "arn:aws:iam::111122223333:role/R",
               "external_id": "ext", "region": "ap-south-1"}
    session = cred.session_for(account, sts=sts)
    assert session.region_name == "ap-south-1"
    assert sts.calls[0]["ExternalId"] == "ext"


def test_session_for_refuses_a_role_in_a_different_account():
    """
    The record says one account and the role belongs to another. Allowing it
    would file a whole estate under the wrong customer — the worst outcome this
    module has, and the one least likely to be noticed.
    """
    account = {"account_id": "111122223333", "tenant_id": "t-1",
               "credential_type": "iam_role",
               "role_arn": "arn:aws:iam::999988887777:role/R",
               "external_id": "ext", "region": "ap-south-1"}
    with pytest.raises(cred.CredentialError, match="belongs to account"):
        cred.session_for(account, sts=FakeSTS())


def test_session_for_access_key_reads_the_secret():
    name = cred.secret_name("t-1", "111122223333")
    secrets = FakeSecrets({name: json.dumps(
        {"access_key_id": "AKIA", "secret_access_key": "shh"})})
    account = {"account_id": "111122223333", "tenant_id": "t-1",
               "credential_type": "access_key", "credential_ref": name,
               "region": "ap-south-1"}
    session = cred.session_for(account, secrets=secrets)
    assert session.get_credentials().access_key == "AKIA"


def test_session_for_rejects_an_unknown_credential_type():
    account = {"account_id": "111122223333", "tenant_id": "t-1",
               "credential_type": "carrier_pigeon", "region": "ap-south-1"}
    with pytest.raises(cred.CredentialError, match="unknown credential type"):
        cred.session_for(account)


# ── secrets ───────────────────────────────────────────────────────────

def test_secret_name_is_scoped_by_tenant_and_account():
    name = cred.secret_name("t-1", "111122223333")
    assert "t-1" in name and "111122223333" in name


def test_write_secret_updates_when_it_already_exists():
    secrets = FakeSecrets({"n": "{}"})
    cred.write_secret("n", {"access_key_id": "AKIA"}, client=secrets)
    assert json.loads(secrets.store["n"])["access_key_id"] == "AKIA"


def test_write_secret_creates_when_absent():
    secrets = FakeSecrets()
    cred.write_secret("n", {"a": 1}, client=secrets)
    assert json.loads(secrets.store["n"]) == {"a": 1}


def test_read_secret_rejects_non_json():
    secrets = FakeSecrets({"n": "not json"})
    with pytest.raises(cred.CredentialError, match="not JSON"):
        cred.read_secret("n", client=secrets)


# ── whoami ────────────────────────────────────────────────────────────

def test_whoami_reports_the_account_reached():
    who = cred.whoami(None, sts=FakeSTS(account="111122223333"))
    assert who["account_id"] == "111122223333"


def test_whoami_turns_a_dead_credential_into_a_named_error():
    with pytest.raises(cred.CredentialError, match="does not work"):
        cred.whoami(None, sts=FakeSTS(fail="ExpiredToken"))
