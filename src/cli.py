"""CLI entry point for automation-c7."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .engine import evaluate_policies, load_policies
from .models import PolicyType, Status
from .providers import get_provider
from .reporters.console import ConsoleReporter
from .reporters.json_reporter import JsonReporter


@click.group()
@click.version_option(__version__, prog_name="c7")
def cli() -> None:
    """automation-c7: FinOps & Security as Policy engine."""


@cli.command()
@click.option("--provider", "-p", required=True, type=click.Choice(["aws", "azure", "gcp"]))
@click.option("--policy-dir", "-d", default="policies", help="Path to policy YAML directory")
@click.option("--policy-type", "-t", type=click.Choice(["finops", "security"]), help="Filter by policy type")
@click.option("--output", "-o", type=click.Choice(["console", "json"]), default="console")
@click.option("--output-file", "-f", type=click.Path(), help="Write JSON output to file")
@click.option("--region", "-r", help="Cloud region to scan")
def scan(
    provider: str,
    policy_dir: str,
    policy_type: str | None,
    output: str,
    output_file: str | None,
    region: str | None,
) -> None:
    """Scan cloud resources against FinOps and security policies."""
    policy_path = Path(policy_dir)
    if not policy_path.exists():
        click.echo(f"Error: policy directory '{policy_dir}' not found", err=True)
        sys.exit(1)

    click.echo(f"Loading policies from {policy_path}...")
    policies = load_policies(policy_path, policy_type)
    if not policies:
        click.echo("No matching policies found.", err=True)
        sys.exit(1)
    click.echo(f"Loaded {len(policies)} policies")

    click.echo(f"Fetching {provider} resources...")
    cloud_provider = get_provider(provider)
    resources = cloud_provider.fetch_resources(region=region)
    click.echo(f"Found {len(resources)} resources")

    click.echo("Evaluating policies...")
    result = evaluate_policies(policies, resources, provider)

    if output == "json":
        reporter = JsonReporter()
    else:
        reporter = ConsoleReporter()

    reporter.report(result)

    if output_file:
        json_reporter = JsonReporter()
        json_reporter.report_to_file(result, output_file)
        click.echo(f"Results written to {output_file}")

    if result.failed > 0:
        sys.exit(1)


@cli.command()
@click.option("--policy-dir", "-d", default="policies", help="Path to policy YAML directory")
@click.option("--policy-type", "-t", type=click.Choice(["finops", "security"]), help="Filter by policy type")
def list_policies(policy_dir: str, policy_type: str | None) -> None:
    """List available policies."""
    policies = load_policies(policy_dir, policy_type)
    if not policies:
        click.echo("No policies found.")
        return

    for p in policies:
        click.echo(f"  [{p.type.value:8s}] {p.name} ({len(p.rules)} rules) - {p.provider}")


@cli.command()
@click.option("--policy-dir", "-d", default="policies", help="Path to policy YAML directory")
def validate(policy_dir: str) -> None:
    """Validate policy YAML files."""
    policy_path = Path(policy_dir)
    errors = 0
    total = 0

    for yaml_file in sorted(policy_path.rglob("*.yaml")):
        total += 1
        try:
            policies = load_policies(yaml_file.parent, None)
            click.echo(f"  OK  {yaml_file.relative_to(policy_path)}")
        except Exception as e:
            errors += 1
            click.echo(f"  ERR {yaml_file.relative_to(policy_path)}: {e}")

    click.echo(f"\n{total} files checked, {errors} errors")
    if errors:
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
