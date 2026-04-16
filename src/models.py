"""Data models for policies, findings, and evaluation results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PolicyType(str, Enum):
    FINOPS = "finops"
    SECURITY = "security"


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


class Condition(BaseModel):
    field: str
    operator: str  # eq, ne, gt, lt, gte, lte, contains, not_contains, exists, regex
    value: Any


class Rule(BaseModel):
    id: str
    description: str
    severity: Severity = Severity.MEDIUM
    conditions: list[Condition]
    remediation: Optional[str] = None


class Policy(BaseModel):
    name: str
    version: str = "1.0"
    type: PolicyType
    provider: str  # aws, azure, gcp, all
    resource_type: str
    description: str
    rules: list[Rule]
    tags: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    policy_name: str
    rule_id: str
    rule_description: str
    severity: Severity
    status: Status
    resource_id: str
    resource_type: str
    provider: str
    region: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    remediation: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvaluationResult(BaseModel):
    scan_id: str
    provider: str
    total_policies: int = 0
    total_rules: int = 0
    findings: list[Finding] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @property
    def passed(self) -> int:
        return sum(1 for f in self.findings if f.status == Status.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for f in self.findings if f.status == Status.FAIL)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.status == Status.ERROR)
