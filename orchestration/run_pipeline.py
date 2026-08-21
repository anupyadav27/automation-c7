"""
DEPRECATED — kept for muscle memory.

The end-to-end flow now lives in `orchestration.pipeline`, one subcommand
per stage:

    python -m orchestration.pipeline all --region us-east-1

This wrapper maps the old flags onto the new CLI and forwards. The old
Postgres/K8s stage-1 path imported the hand-written AWSDiscoveryScanner,
which was dropped in the merge (superseded by the catalog-driven collector
in providers/aws). Cluster deployments drive the same stages through the
Discoveries and Inventory Engine APIs instead.
"""
import sys

from orchestration.pipeline import main as pipeline_main


def main():
    print(
        "run_pipeline.py is deprecated — forwarding to "
        "`python -m orchestration.pipeline all`.\n",
        file=sys.stderr,
    )
    argv = ["all"]
    passthrough = sys.argv[1:]
    region = "us-east-1"
    account_id = None
    skip = False
    for i, arg in enumerate(passthrough):
        if skip:
            skip = False
            continue
        if arg == "--region" and i + 1 < len(passthrough):
            region = passthrough[i + 1]
            skip = True
        elif arg == "--account-id" and i + 1 < len(passthrough):
            account_id = passthrough[i + 1]
            skip = True
        elif arg in ("--access-key", "--secret-key") and i + 1 < len(passthrough):
            print(f"  note: {arg} ignored — export AWS credentials as env vars",
                  file=sys.stderr)
            skip = True
    argv += ["--region", region]
    if account_id:
        argv += ["--account-id", account_id]
    return pipeline_main(argv)


if __name__ == "__main__":
    sys.exit(main())
