"""Policy evaluation engine - loads YAML policies and evaluates resources."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .models import (
    Condition,
    EvaluationResult,
    Finding,
    Policy,
    PolicyType,
    Rule,
    Severity,
    Status,
)


def load_policies(policy_dir: str | Path, policy_type: str | None = None) -> list[Policy]:
    """Load all YAML policy files from a directory tree."""
    policy_dir = Path(policy_dir)
    policies: list[Policy] = []

    for yaml_file in sorted(policy_dir.rglob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or "rules" not in data:
            continue
        policy = Policy(**data)
        if policy_type and policy.type.value != policy_type:
            continue
        policies.append(policy)

    return policies


def evaluate_condition(condition: Condition, resource: dict[str, Any]) -> bool:
    """Evaluate a single condition against a resource."""
    value = _resolve_field(resource, condition.field)
    expected = condition.value
    op = condition.operator

    if op == "exists":
        return value is not None if expected else value is None
    if value is None:
        return False

    ops = {
        "eq": lambda v, e: v == e,
        "ne": lambda v, e: v != e,
        "gt": lambda v, e: float(v) > float(e),
        "lt": lambda v, e: float(v) < float(e),
        "gte": lambda v, e: float(v) >= float(e),
        "lte": lambda v, e: float(v) <= float(e),
        "contains": lambda v, e: e in str(v),
        "not_contains": lambda v, e: e not in str(v),
        "regex": lambda v, e: bool(re.search(str(e), str(v))),
        "in": lambda v, e: v in e if isinstance(e, list) else False,
        "not_in": lambda v, e: v not in e if isinstance(e, list) else True,
    }

    fn = ops.get(op)
    if fn is None:
        raise ValueError(f"Unknown operator: {op}")
    return fn(value, expected)


def evaluate_rule(rule: Rule, resource: dict[str, Any]) -> Status:
    """Evaluate all conditions in a rule (AND logic)."""
    try:
        for condition in rule.conditions:
            if not evaluate_condition(condition, resource):
                return Status.FAIL
        return Status.PASS
    except Exception:
        return Status.ERROR


def evaluate_policies(
    policies: list[Policy],
    resources: list[dict[str, Any]],
    provider: str,
) -> EvaluationResult:
    """Run all policies against a set of resources."""
    scan_id = str(uuid.uuid4())[:12]
    result = EvaluationResult(
        scan_id=scan_id,
        provider=provider,
        total_policies=len(policies),
    )

    for policy in policies:
        if policy.provider not in (provider, "all"):
            continue
        result.total_rules += len(policy.rules)

        matching_resources = [
            r for r in resources if r.get("resource_type") == policy.resource_type
        ]

        for resource in matching_resources:
            for rule in policy.rules:
                status = evaluate_rule(rule, resource)
                result.findings.append(
                    Finding(
                        policy_name=policy.name,
                        rule_id=rule.id,
                        rule_description=rule.description,
                        severity=rule.severity,
                        status=status,
                        resource_id=resource.get("resource_id", "unknown"),
                        resource_type=policy.resource_type,
                        provider=provider,
                        region=resource.get("region"),
                        details={"resource": resource} if status == Status.FAIL else {},
                        remediation=rule.remediation,
                    )
                )

    result.completed_at = datetime.now(timezone.utc)
    return result


def _resolve_field(data: dict[str, Any], field_path: str) -> Any:
    """Resolve a dot-separated field path in a nested dict."""
    parts = field_path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
    return current
