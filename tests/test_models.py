"""Tests for data models."""

from src.models import (
    Condition,
    EvaluationResult,
    Finding,
    Policy,
    PolicyType,
    Rule,
    Severity,
    Status,
)


class TestModels:
    def test_condition(self):
        c = Condition(field="name", operator="eq", value="test")
        assert c.field == "name"

    def test_rule(self):
        r = Rule(
            id="R-001",
            description="test",
            severity=Severity.HIGH,
            conditions=[Condition(field="x", operator="eq", value=True)],
        )
        assert r.id == "R-001"
        assert r.severity == Severity.HIGH

    def test_policy(self):
        p = Policy(
            name="test",
            type=PolicyType.SECURITY,
            provider="aws",
            resource_type="s3_bucket",
            description="test policy",
            rules=[
                Rule(
                    id="R-001",
                    description="test",
                    conditions=[Condition(field="x", operator="eq", value=True)],
                )
            ],
        )
        assert p.type == PolicyType.SECURITY
        assert len(p.rules) == 1

    def test_finding(self):
        f = Finding(
            policy_name="test",
            rule_id="R-001",
            rule_description="test",
            severity=Severity.HIGH,
            status=Status.FAIL,
            resource_id="bucket-1",
            resource_type="s3_bucket",
            provider="aws",
        )
        assert f.status == Status.FAIL

    def test_evaluation_result_properties(self):
        r = EvaluationResult(scan_id="test", provider="aws")
        r.findings = [
            Finding(
                policy_name="p",
                rule_id="r1",
                rule_description="d",
                severity=Severity.HIGH,
                status=Status.PASS,
                resource_id="a",
                resource_type="t",
                provider="aws",
            ),
            Finding(
                policy_name="p",
                rule_id="r2",
                rule_description="d",
                severity=Severity.HIGH,
                status=Status.FAIL,
                resource_id="b",
                resource_type="t",
                provider="aws",
            ),
            Finding(
                policy_name="p",
                rule_id="r3",
                rule_description="d",
                severity=Severity.LOW,
                status=Status.ERROR,
                resource_id="c",
                resource_type="t",
                provider="aws",
            ),
        ]
        assert r.passed == 1
        assert r.failed == 1
        assert r.errors == 1
