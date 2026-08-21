"""
Reading a rule's field out of an AWS payload.

The defect these guard is quiet and expensive: on this estate a naive flat
lookup reported `block_public_acls` as unresolvable across 55 buckets. The
evaluator would have recorded "no rule could run" and a reader would have read
"no public buckets". The field was present the whole time, one level down.
"""
import pytest

from engines.exposure.fields import resolvable, resolve, snake


# ── acronyms ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("aws,rule", [
    ("DNSName", "dns_name"),
    ("PublicIpAddress", "public_ip_address"),
    ("MapPublicIpOnLaunch", "map_public_ip_on_launch"),
    ("BlockPublicAcls", "block_public_acls"),
    ("IpPermissions", "ip_permissions"),
    ("VpcId", "vpc_id"),
    ("SecurityGroups", "security_groups"),
    ("KmsKeyId", "kms_key_id"),
    ("EndpointPublicAccess", "endpoint_public_access"),
])
def test_aws_keys_snake_the_way_the_rules_spell_them(aws, rule):
    assert snake(aws) == rule


def test_an_initialism_does_not_shatter():
    """
    The bug this masking exists for. A plain `(?<!^)(?=[A-Z])` split treats
    every capital as a word boundary, so `DNSName` becomes `d_n_s_name` and
    every AWS initialism — DNS, IP, VPC, ARN, ACL — stops matching.
    """
    assert snake("DNSName") == "dns_name"
    assert "d_n_s" not in snake("DNSName")


def test_snake_is_stable_on_an_already_snake_key():
    assert snake("public_ip_address") == "public_ip_address"


def test_snake_handles_an_empty_key():
    assert snake("") == ""


# ── nesting ───────────────────────────────────────────────────────────

def test_a_top_level_field_resolves():
    assert resolve({"PublicIpAddress": "1.2.3.4"}, "public_ip_address") == (True, "1.2.3.4")


def test_a_nested_field_resolves():
    """The 55-bucket case: AWS groups settings that came from a separate API
    call into a sub-object, so a flat rule name is a leaf several levels down."""
    payload = {"Name": "b", "PublicAccessBlockConfiguration": {"BlockPublicAcls": False}}
    assert resolve(payload, "block_public_acls") == (True, False)


def test_a_field_inside_a_list_of_objects_resolves():
    payload = {"Instances": [{"State": {"Name": "running"}}]}
    found, _ = resolve(payload, "state")
    assert found


def test_a_shallow_field_wins_over_a_deeper_one_of_the_same_name():
    """
    Breadth-first, deliberately. A top-level `Status` must not be shadowed by
    `SomeConfig.Status` — the two mean different things and the shallow one is
    the resource's own.
    """
    payload = {"Status": "top", "Config": {"Status": "nested"}}
    assert resolve(payload, "status") == (True, "top")


def test_depth_is_bounded():
    deep = {"a": {"b": {"c": {"d": {"Target": 1}}}}}
    assert resolve(deep, "target", max_depth=2) == (False, None)


# ── absent vs false ───────────────────────────────────────────────────

def test_a_false_value_is_found_not_missed():
    """
    `False`, `0` and `None` are legitimate findings. A resolver that returns a
    bare value cannot tell "absent" from "false", and a rule that cannot tell
    them apart will clear a resource it should have flagged — `block_public_acls:
    false` is exactly the finding that matters.
    """
    assert resolve({"BlockPublicAcls": False}, "block_public_acls") == (True, False)
    assert resolve({"Count": 0}, "count") == (True, 0)
    assert resolve({"Thing": None}, "thing") == (True, None)


def test_a_genuinely_absent_field_reports_absent():
    assert resolve({"Name": "b"}, "block_public_acls") == (False, None)


def test_a_non_dict_payload_is_absent_not_an_error():
    for junk in (None, [], "string", 7):
        assert resolve(junk, "anything") == (False, None)


# ── the audit helper ──────────────────────────────────────────────────

def test_resolvable_names_only_what_is_missing():
    payload = {"DNSName": "x", "Scheme": "internet-facing"}
    assert resolvable(payload, ["dns_name", "scheme"]) == []
    assert resolvable(payload, ["dns_name", "vpc_id"]) == ["vpc_id"]
