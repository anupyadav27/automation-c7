"""JSON reporter for machine-readable output."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..models import EvaluationResult


class JsonReporter:
    """Output findings as JSON."""

    def report(self, result: EvaluationResult) -> None:
        output = result.model_dump(mode="json")
        output["summary"] = {
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
        }
        click.echo(json.dumps(output, indent=2, default=str))

    def report_to_file(self, result: EvaluationResult, filepath: str) -> None:
        output = result.model_dump(mode="json")
        output["summary"] = {
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
        }
        Path(filepath).write_text(json.dumps(output, indent=2, default=str))
