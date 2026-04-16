"""Console table reporter."""

from __future__ import annotations

import click

from ..models import EvaluationResult, Status


class ConsoleReporter:
    """Output findings as a formatted console table."""

    def report(self, result: EvaluationResult) -> None:
        click.echo(f"\n{'='*70}")
        click.echo(f"  Scan: {result.scan_id} | Provider: {result.provider}")
        click.echo(f"  Policies: {result.total_policies} | Rules: {result.total_rules}")
        click.echo(f"{'='*70}\n")

        failures = [f for f in result.findings if f.status == Status.FAIL]
        passes = [f for f in result.findings if f.status == Status.PASS]

        if failures:
            click.echo(click.style(f"  FAILURES ({len(failures)}):", fg="red", bold=True))
            click.echo(f"  {'-'*66}")
            for f in failures:
                sev_color = {
                    "critical": "red",
                    "high": "red",
                    "medium": "yellow",
                    "low": "cyan",
                    "info": "white",
                }.get(f.severity.value, "white")

                sev_label = f.severity.value.upper().rjust(8)
                res_label = f.resource_id.ljust(30)
                click.echo(
                    f"  {click.style(sev_label, fg=sev_color)} | "
                    f"{res_label} | {f.rule_description}"
                )
                if f.remediation:
                    click.echo(f"  {'':>8s}   Remediation: {f.remediation}")

        if passes:
            passed_msg = f"PASSED ({len(passes)})"
            click.echo(f"\n  {click.style(passed_msg, fg='green', bold=True)}")

        click.echo(f"\n{'='*70}")
        click.echo(
            f"  Summary: "
            f"{click.style(str(result.passed), fg='green')} passed, "
            f"{click.style(str(result.failed), fg='red')} failed, "
            f"{click.style(str(result.errors), fg='yellow')} errors"
        )
        click.echo(f"{'='*70}\n")
