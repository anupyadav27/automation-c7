"""
The exposure rule catalog, and the ways it can fail without saying so.

Every test here guards the same defect from a different angle: a rule that
cannot fire is indistinguishable, in a report, from a rule that fired and found
nothing. "No internet-exposed resources" is the most dangerous sentence this
engine can produce, and a catalog that does not quite fit the inventory produces
it for free.
"""
import pytest

from engines.exposure import rules as R


@pytest.fixture(scope="module")
def catalog():
    return R.load_rules()


# ── the ported catalog binds against THIS inventory ───────────────────

def test_the_whole_catalog_binds(catalog):
    """The gate. Ported rules that name types we never collect are errors."""
    R.validate(catalog)


def test_catalog_has_all_three_tiers(catalog):
    tiers = {r["tier"] for r in catalog}
    assert tiers == {1, 2, 3}, f"expected three tiers, got {sorted(tiers)}"


def test_rule_ids_are_unique(catalog):
    ids = [r["rule_id"] for r in catalog]
    assert len(ids) == len(set(ids))


def test_load_order_is_stable(catalog):
    """
    Sorted by id, not by whatever order the filesystem returns. Two runs over
    one catalog must produce the same list or a report cannot be diffed.
    """
    assert [r["rule_id"] for r in catalog] == sorted(r["rule_id"] for r in catalog)
    assert [r["rule_id"] for r in R.load_rules()] == [r["rule_id"] for r in catalog]


# ── type normalisation ────────────────────────────────────────────────

@pytest.mark.parametrize("theirs,ours", [
    ("ec2_instance", "ec2.instance"),
    ("elbv2_load_balancer", "elbv2.load_balancer"),
    ("s3_bucket", "s3.bucket"),
    ("route53_hosted_zone", "route53.hosted_zone"),
    ("apigatewayv2_api", "apigatewayv2.api"),
])
def test_first_underscore_becomes_the_dot(theirs, ours):
    assert R.normalise_type(theirs) == ours


def test_only_the_first_underscore_is_replaced():
    """
    `lambda.function.url.config` resolves to nothing. The first underscore
    separates service from resource; the rest belong to the resource's name.
    """
    assert R.normalise_type("lambda_function_url_config") == "lambda.function_url_config"


@pytest.mark.parametrize("theirs,ours", [
    ("ec2_address", "ec2.eip"),
    ("ec2.securitygroup", "ec2.security_group"),
])
def test_the_two_names_that_do_not_follow_the_rule(theirs, ours):
    """
    Each alias is a place two teams named one thing differently. A silent
    fallback would turn each into a rule that never fires.
    """
    assert R.normalise_type(theirs) == ours


def test_an_already_dotted_type_is_left_alone():
    # threat-engine's own catalog is inconsistent — tiers 1-2 underscore,
    # tier 3 dots — so the normaliser has to accept both.
    assert R.normalise_type("ec2.subnet") == "ec2.subnet"


def test_a_rule_without_a_type_is_an_error():
    with pytest.raises(R.RuleError):
        R.normalise_type("")


# ── refusing to load quietly ──────────────────────────────────────────

def test_unknown_type_is_reported_not_skipped():
    fake = [{"rule_id": "X-1", "tier": 1, "resource_type": "ec2.does_not_exist",
             "required_emitted_fields": [], "traversal_steps": []}]
    assert R.unbound_types(fake, known={"ec2.instance"}) == [("X-1", "ec2.does_not_exist")]


def test_validate_raises_on_an_unbindable_rule():
    fake = [{"rule_id": "X-1", "tier": 1, "resource_type": "ec2.nope",
             "required_emitted_fields": [], "traversal_steps": []}]
    with pytest.raises(R.RuleError, match="does not produce|cannot match"):
        R.validate(fake, known={"ec2.instance"})


def test_traversal_targets_are_bound_too():
    """A chain is only as good as its hops. A step naming an unknown type
    breaks the chain in the middle, where it is hardest to notice."""
    fake = [{"rule_id": "X-1", "tier": 3, "resource_type": "ec2.instance",
             "required_emitted_fields": [],
             "traversal_steps": [{"target_type": "ec2.ghost"}]}]
    assert ("X-1", "ec2.ghost") in R.unbound_types(fake, known={"ec2.instance"})


def test_tier_2_must_declare_the_fields_it_needs():
    """Otherwise it is a tier 1 rule wearing the wrong label, and fires on
    every resource of its type unconditionally."""
    with pytest.raises(R.RuleError, match="required_emitted_fields"):
        R._bind({"rule_id": "X-1", "tier": 2, "resource_type": "ec2_instance"}, "t.yaml")


def test_tier_3_must_declare_its_traversal():
    with pytest.raises(R.RuleError, match="traversal_steps"):
        R._bind({"rule_id": "X-1", "tier": 3, "resource_type": "ec2_instance"}, "t.yaml")


def test_an_unknown_tier_is_an_error():
    with pytest.raises(R.RuleError, match="tier"):
        R._bind({"rule_id": "X-1", "tier": 9, "resource_type": "ec2_instance"}, "t.yaml")


def test_a_rule_without_an_id_is_an_error():
    with pytest.raises(R.RuleError, match="rule_id"):
        R._bind({"tier": 1, "resource_type": "ec2_instance"}, "t.yaml")


# ── what the catalog actually claims ──────────────────────────────────

def test_tier_1_rules_carry_no_conditions(catalog):
    """
    Tier 1 is 'public by construction'. A tier 1 rule with a field check is
    really a tier 2 rule, and mislabelling it means it is evaluated by the
    wrong evaluator and its condition never runs.
    """
    for rule in [r for r in catalog if r["tier"] == 1]:
        assert not rule["required_emitted_fields"], (
            f"{rule['rule_id']} is tier 1 but requires fields"
        )


def test_every_rule_names_an_origin(catalog):
    """`origin_type` is what makes a verdict a path rather than a label — it
    says where the reachability comes FROM, which Sprint 3 needs."""
    missing = [r["rule_id"] for r in catalog if not r.get("origin_type")]
    assert not missing, f"rules with no origin_type: {missing}"


def test_every_rule_carries_a_severity(catalog):
    missing = [r["rule_id"] for r in catalog if not r.get("severity")]
    assert not missing, f"rules with no severity: {missing}"
