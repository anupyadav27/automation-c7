"""Tests for the policy evaluation engine."""

from src.engine import evaluate_condition, evaluate_policies, evaluate_rule, load_policies
from src.models import Condition, EvaluationResult, Policy, PolicyType, Rule, Severity, Status


def _make_condition(field: str, operator: str, value) -> Condition:
    return Condition(field=field, operator=operator, value=value)


def _make_rule(conditions: list[Condition], rule_id: str = "TEST-001") -> Rule:
    return Rule(id=rule_id, description="test rule", severity=Severity.MEDIUM, conditions=conditions)


class TestEvaluateCondition:
    def test_eq_pass(self):
        assert evaluate_condition(_make_condition("name", "eq", "foo"), {"name": "foo"}) is True

    def test_eq_fail(self):
        assert evaluate_condition(_make_condition("name", "eq", "foo"), {"name": "bar"}) is False

    def test_ne(self):
        assert evaluate_condition(_make_condition("name", "ne", "foo"), {"name": "bar"}) is True

    def test_gt(self):
        assert evaluate_condition(_make_condition("size", "gt", 10), {"size": 20}) is True
        assert evaluate_condition(_make_condition("size", "gt", 10), {"size": 5}) is False

    def test_lt(self):
        assert evaluate_condition(_make_condition("size", "lt", 10), {"size": 5}) is True

    def test_gte(self):
        assert evaluate_condition(_make_condition("size", "gte", 10), {"size": 10}) is True

    def test_lte(self):
        assert evaluate_condition(_make_condition("size", "lte", 10), {"size": 10}) is True

    def test_contains(self):
        assert evaluate_condition(_make_condition("name", "contains", "oo"), {"name": "foobar"}) is True

    def test_not_contains(self):
        assert evaluate_condition(_make_condition("name", "not_contains", "xyz"), {"name": "foobar"}) is True

    def test_regex(self):
        assert evaluate_condition(_make_condition("name", "regex", r"^foo\d+"), {"name": "foo123"}) is True

    def test_exists_true(self):
        assert evaluate_condition(_make_condition("name", "exists", True), {"name": "val"}) is True

    def test_exists_false(self):
        assert evaluate_condition(_make_condition("name", "exists", False), {"other": "val"}) is True

    def test_in_operator(self):
        assert evaluate_condition(_make_condition("type", "in", ["a", "b"]), {"type": "a"}) is True
        assert evaluate_condition(_make_condition("type", "in", ["a", "b"]), {"type": "c"}) is False

    def test_nested_field(self):
        assert evaluate_condition(
            _make_condition("tags.Environment", "eq", "prod"),
            {"tags": {"Environment": "prod"}}
        ) is True

    def test_missing_field_returns_false(self):
        assert evaluate_condition(_make_condition("missing", "eq", "x"), {"name": "y"}) is False


class TestEvaluateRule:
    def test_all_conditions_pass(self):
        rule = _make_rule([
            _make_condition("name", "eq", "foo"),
            _make_condition("size", "gt", 5),
        ])
        assert evaluate_rule(rule, {"name": "foo", "size": 10}) == Status.PASS

    def test_one_condition_fails(self):
        rule = _make_rule([
            _make_condition("name", "eq", "foo"),
            _make_condition("size", "gt", 100),
        ])
        assert evaluate_rule(rule, {"name": "foo", "size": 10}) == Status.FAIL


class TestEvaluatePolicies:
    def test_basic_evaluation(self):
        policy = Policy(
            name="test",
            type=PolicyType.SECURITY,
            provider="aws",
            resource_type="s3_bucket",
            description="test policy",
            rules=[_make_rule([_make_condition("encrypted", "eq", True)])],
        )
        resources = [
            {"resource_id": "bucket-1", "resource_type": "s3_bucket", "encrypted": True},
            {"resource_id": "bucket-2", "resource_type": "s3_bucket", "encrypted": False},
        ]
        result = evaluate_policies([policy], resources, "aws")
        assert isinstance(result, EvaluationResult)
        assert result.passed == 1
        assert result.failed == 1

    def test_provider_filter(self):
        policy = Policy(
            name="test",
            type=PolicyType.SECURITY,
            provider="azure",
            resource_type="s3_bucket",
            description="test",
            rules=[_make_rule([_make_condition("x", "eq", True)])],
        )
        resources = [{"resource_id": "b1", "resource_type": "s3_bucket", "x": True}]
        result = evaluate_policies([policy], resources, "aws")
        assert len(result.findings) == 0

    def test_provider_all_matches_any(self):
        policy = Policy(
            name="test",
            type=PolicyType.FINOPS,
            provider="all",
            resource_type="ec2_instance",
            description="test",
            rules=[_make_rule([_make_condition("state", "eq", "running")])],
        )
        resources = [{"resource_id": "i-1", "resource_type": "ec2_instance", "state": "running"}]
        result = evaluate_policies([policy], resources, "aws")
        assert result.passed == 1


class TestLoadPolicies:
    def test_load_from_directory(self, tmp_path):
        policy_file = tmp_path / "test.yaml"
        policy_file.write_text("""
name: test policy
type: security
provider: aws
resource_type: s3_bucket
description: test
rules:
  - id: T-001
    description: test rule
    severity: high
    conditions:
      - field: encrypted
        operator: eq
        value: true
""")
        policies = load_policies(tmp_path)
        assert len(policies) == 1
        assert policies[0].name == "test policy"

    def test_filter_by_type(self, tmp_path):
        for name, ptype in [("sec.yaml", "security"), ("fin.yaml", "finops")]:
            (tmp_path / name).write_text(f"""
name: {name}
type: {ptype}
provider: aws
resource_type: ec2_instance
description: test
rules:
  - id: T-001
    description: test
    severity: medium
    conditions:
      - field: x
        operator: eq
        value: true
""")
        assert len(load_policies(tmp_path, "security")) == 1
        assert len(load_policies(tmp_path, "finops")) == 1
