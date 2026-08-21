"""
The verdict, and the ways it can flatter an estate.

Every test here defends one sentence: **a verdict may never be inferred from an
absence.** The failure it guards is not a crash — it is a report that says
"no internet-exposed resources" because half its rules could not run, which is
unfalsifiable and fails in the direction nobody investigates.
"""
import pytest

from engines.exposure import rules as R
from engines.exposure.evaluate import (
    EXPOSED, NOT_APPLICABLE, NOT_EXPOSED, UNDETERMINED,
    coverage, evaluate_all, evaluate_asset, evaluate_rule, parse_fields,
)


def rule(**kw):
    base = {"rule_id": "T-1", "tier": 2, "resource_type": "ec2.instance",
            "origin_type": "internet", "severity": "high",
            "required_emitted_fields": ["public_ip_address"],
            "exposure_conditions": [{"field": "public_ip_address", "operator": "not_null"}]}
    base.update(kw)
    return base


_seq = iter(range(1, 10_000))


def asset(kind="ec2.instance", **raw):
    """A distinct asset each call — see `test_a_duplicate_identity_is_refused`
    for why sharing one id is not a harmless test shortcut."""
    return {"asset_id": f"a-{next(_seq)}", "resource_key": kind, "raw": raw}


# ── the core rule ─────────────────────────────────────────────────────

def test_a_missing_required_field_is_undetermined_not_clean():
    """The whole module in one test. Absence is not innocence."""
    r = evaluate_rule(rule(), {})
    assert r.verdict == UNDETERMINED
    assert "public_ip_address" in r.reason


def test_a_present_field_that_fails_its_condition_is_not_exposed():
    r = evaluate_rule(rule(), {"PublicIpAddress": None})
    assert r.verdict == NOT_EXPOSED


def test_a_present_field_that_meets_its_condition_is_exposed():
    r = evaluate_rule(rule(), {"PublicIpAddress": "1.2.3.4"})
    assert r.verdict == EXPOSED
    assert r.fields_read["public_ip_address"] == "1.2.3.4"


def test_a_verdict_carries_the_values_that_produced_it():
    """A finding that cannot say what it read is an assertion, not evidence."""
    r = evaluate_rule(rule(), {"PublicIpAddress": "1.2.3.4"})
    assert r.fields_read
    assert r.origin_type == "internet" and r.severity == "high"


# ── declared optionality ──────────────────────────────────────────────

def test_a_bare_string_field_is_required():
    """The safe default: a port that says nothing must not clear anything."""
    assert parse_fields(["a"])[0].optional is False


def test_an_optional_field_declared_not_exposed_clears():
    """An ENI with no Association genuinely has none — absence IS the answer."""
    r = evaluate_rule(rule(required_emitted_fields=[
        {"name": "association", "optional": True, "absent_means": "not_exposed"}
    ], exposure_conditions=[{"field": "association", "operator": "not_null"}]), {})
    assert r.verdict == NOT_EXPOSED


def test_an_optional_field_declared_undetermined_does_not_clear():
    r = evaluate_rule(rule(required_emitted_fields=[
        {"name": "thing", "optional": True, "absent_means": "undetermined"}
    ]), {})
    assert r.verdict == UNDETERMINED


def test_a_rule_may_not_declare_that_absence_proves_exposure():
    """
    The inverse failure: letting a collection gap manufacture a finding. Just as
    wrong as letting one clear a resource, and easier to slip past review.
    """
    with pytest.raises(ValueError, match="may not prove exposure"):
        parse_fields([{"name": "x", "optional": True, "absent_means": "exposed"}])


def test_an_unreadable_field_declaration_is_an_error():
    with pytest.raises(ValueError):
        parse_fields([{"optional": True}])


# ── things that must not silently pass ────────────────────────────────

def test_an_unknown_operator_is_undetermined_not_false():
    """Treating it as false would clear a resource on a rule that never ran."""
    r = evaluate_rule(rule(exposure_conditions=[
        {"field": "public_ip_address", "operator": "teleports"}]),
        {"PublicIpAddress": "1.2.3.4"})
    assert r.verdict == UNDETERMINED


def test_a_tier_2_rule_with_no_conditions_is_undetermined():
    r = evaluate_rule(rule(exposure_conditions=[]), {"PublicIpAddress": "1.2.3.4"})
    assert r.verdict == UNDETERMINED


def test_tier_3_is_not_decided_here():
    r = evaluate_rule(rule(tier=3), {"PublicIpAddress": "1.2.3.4"})
    assert r.verdict == UNDETERMINED
    assert "traversal" in r.reason


def test_tier_1_is_structural_and_needs_no_payload():
    r = evaluate_rule(rule(tier=1, required_emitted_fields=[], exposure_conditions=[]), {})
    assert r.verdict == EXPOSED


# ── the CIDR operator ─────────────────────────────────────────────────

def test_an_open_security_group_is_detected_in_the_shape_aws_returns():
    perms = [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]
    r = evaluate_rule(rule(
        required_emitted_fields=["ip_permissions"],
        exposure_conditions=[{"field": "ip_permissions",
                              "operator": "contains_cidr_any",
                              "value": ["0.0.0.0/0"]}]),
        {"IpPermissions": perms})
    assert r.verdict == EXPOSED


def test_a_closed_security_group_is_not_exposed():
    perms = [{"IpRanges": [{"CidrIp": "10.0.0.0/8"}]}]
    r = evaluate_rule(rule(
        required_emitted_fields=["ip_permissions"],
        exposure_conditions=[{"field": "ip_permissions",
                              "operator": "contains_cidr_any",
                              "value": ["0.0.0.0/0"]}]),
        {"IpPermissions": perms})
    assert r.verdict == NOT_EXPOSED


def test_a_cidr_mentioned_in_a_description_does_not_count():
    """
    `"0.0.0.0/0" in str(payload)` would match this. Walking the real shape is
    what stops a description turning into a critical finding.
    """
    perms = [{"IpRanges": [{"CidrIp": "10.0.0.0/8", "Description": "not 0.0.0.0/0"}]}]
    r = evaluate_rule(rule(
        required_emitted_fields=["ip_permissions"],
        exposure_conditions=[{"field": "ip_permissions",
                              "operator": "contains_cidr_any",
                              "value": ["0.0.0.0/0"]}]),
        {"IpPermissions": perms})
    assert r.verdict == NOT_EXPOSED


def test_ipv6_open_range_is_caught():
    perms = [{"Ipv6Ranges": [{"CidrIpv6": "::/0"}]}]
    r = evaluate_rule(rule(
        required_emitted_fields=["ip_permissions"],
        exposure_conditions=[{"field": "ip_permissions",
                              "operator": "contains_cidr_any",
                              "value": ["::/0"]}]),
        {"IpPermissions": perms})
    assert r.verdict == EXPOSED


# ── precedence across rules ───────────────────────────────────────────

def test_undetermined_beats_not_exposed():
    """
    One rule failing to run is not cancelled by another succeeding. The
    resource still has an unchecked way in, and collapsing to the cleaner
    answer is exactly the flattering failure.
    """
    rules = [rule(rule_id="A"), rule(rule_id="B", required_emitted_fields=["absent_field"])]
    r = evaluate_asset(asset(PublicIpAddress=None), rules)
    assert r.verdict == UNDETERMINED


def test_exposed_beats_everything():
    rules = [rule(rule_id="A", required_emitted_fields=["absent_field"]), rule(rule_id="B")]
    r = evaluate_asset(asset(PublicIpAddress="1.2.3.4"), rules)
    assert r.verdict == EXPOSED


def test_a_type_no_rule_covers_is_not_applicable_not_clean():
    """
    27 rules over 4,647 catalog types. Reporting the uncovered majority as
    'not exposed' would be the single biggest lie the tool could tell.
    """
    r = evaluate_asset(asset("xray.sampling_rule"), [rule()])
    assert r.verdict == NOT_APPLICABLE


# ── coverage ──────────────────────────────────────────────────────────

def test_coverage_states_every_denominator():
    results = evaluate_all([
        asset(PublicIpAddress="1.2.3.4"),
        asset(PublicIpAddress=None),
        asset(),
        asset("xray.sampling_rule"),
    ], [rule()])
    c = coverage(results)
    assert c["exposed"] == 1 and c["not_exposed"] == 1
    assert c["undetermined"] == 1 and c["not_applicable"] == 1
    assert c["total"] == 4 and c["evaluated"] == 2
    assert c["coverage_pct"] == 50.0


def test_a_duplicate_identity_is_refused_not_merged():
    """
    Found by a fixture that reused one id: three of four resources silently
    vanished from the coverage report. Nothing was evaluated for them, no
    denominator counted them, and the total still looked authoritative.
    """
    from engines.exposure.evaluate import DuplicateAsset
    twins = [{"asset_id": "same", "resource_key": "ec2.instance", "raw": {}},
             {"asset_id": "same", "resource_key": "ec2.instance", "raw": {}}]
    with pytest.raises(DuplicateAsset, match="share the identity"):
        evaluate_all(twins, [rule()])


def test_an_asset_with_no_identity_is_refused():
    from engines.exposure.evaluate import DuplicateAsset
    with pytest.raises(DuplicateAsset, match="no asset_id"):
        evaluate_all([{"resource_key": "ec2.instance", "raw": {}}], [rule()])


def test_every_asset_reaches_the_coverage_total():
    """The invariant the duplicate bug broke: nothing may be lost in between."""
    estate = [asset(PublicIpAddress="1.2.3.4") for _ in range(5)]
    assert coverage(evaluate_all(estate, [rule()]))["total"] == len(estate)


def test_coverage_of_an_empty_estate_does_not_divide_by_zero():
    assert coverage({})["coverage_pct"] == 0.0


# ── determinism (2.10) ────────────────────────────────────────────────

def test_two_runs_over_one_estate_agree():
    catalog = R.load_rules()
    estate = [asset(PublicIpAddress="1.2.3.4"), asset("s3.bucket"), asset("xray.sampling_rule")]
    a = {k: v.as_dict() for k, v in evaluate_all(estate, catalog).items()}
    b = {k: v.as_dict() for k, v in evaluate_all(estate, catalog).items()}
    assert a == b


def test_the_real_catalog_evaluates_without_raising():
    catalog = R.load_rules()
    for a in (asset(PublicIpAddress="1.2.3.4"), asset("s3.bucket"), asset("elbv2.load_balancer")):
        assert evaluate_asset(a, catalog).verdict in (
            EXPOSED, NOT_EXPOSED, UNDETERMINED, NOT_APPLICABLE)


# ── the false-positive audit (2.11) ───────────────────────────────────

def test_a_rule_firing_on_everything_is_flagged_when_not_tier_1():
    """
    The check that would have caught 55 false S3 highs before a customer did.
    A condition-less rule and a genuinely-always-public type look identical at
    100%; only the tier declaration tells them apart.
    """
    from engines.exposure.evaluate import suspicious_rules
    estate = [asset(PublicIpAddress="1.2.3.4") for _ in range(5)]
    assert suspicious_rules(estate, [rule()]) == [("T-1", 5, 5)]


def test_tier_1_at_one_hundred_percent_is_not_suspicious():
    """Tier 1 IS the declaration that a type is always public. Firing on all of
    them is the rule working, not the rule broken."""
    from engines.exposure.evaluate import suspicious_rules
    estate = [asset() for _ in range(5)]
    t1 = rule(tier=1, required_emitted_fields=[], exposure_conditions=[])
    assert suspicious_rules(estate, [t1]) == []


def test_a_tiny_population_is_not_called_systemic():
    """One instance firing is not evidence of a mislabelled rule."""
    from engines.exposure.evaluate import suspicious_rules
    assert suspicious_rules([asset(PublicIpAddress="1.2.3.4")], [rule()]) == []


def test_firing_rates_report_both_numbers():
    from engines.exposure.evaluate import firing_rates
    estate = [asset(PublicIpAddress="1.2.3.4"), asset(PublicIpAddress=None)]
    assert firing_rates(estate, [rule()])["T-1"] == (1, 2)
