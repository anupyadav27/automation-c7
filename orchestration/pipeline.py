"""
pipeline — the platform's flow as a command.

    discover → build assets → build architecture

Run everything:

    python -m orchestration.pipeline all --region ap-south-1

Or any stage alone (each reads the previous stage's artifact from out/):

    python -m orchestration.pipeline discover     --region ap-south-1 [--scope scenario|primary|all] [--dry-run]
    python -m orchestration.pipeline assets       [--tenant-id local]
    python -m orchestration.pipeline architecture [--region ap-south-1]

`all --offline` replays every stage against the last collection without a
single cloud call — the same path CI uses.

Compliance scoping examples:

    # one policy, all resources
    # the whole pack, two specific resources
    # everything
"""
import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def _banner(step: str, title: str) -> None:
    print(f"\n{'─' * 60}\n  {step}  {title}\n{'─' * 60}", file=sys.stderr)


def _csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def cmd_discover(args):
    from orchestration.stages import discover

    _banner("1/3", "discover — collect raw resources")
    return discover.run(
        region=args.region,
        account=args.account,
        scope=args.scope,
        types=args.types,
        dry_run=args.dry_run,
        offline=args.offline,
    )


def cmd_assets(args):
    import uuid

    from orchestration.stages import build_assets

    # A run needs its own id even when the stage is invoked alone. Defaulting to
    # "adhoc" meant every row ever written carried the same one, so the rows for
    # resources that no longer exist were indistinguishable from current ones
    # and the table could only grow.
    if not args.scan_run_id:
        args.scan_run_id = f"scan_{uuid.uuid4().hex[:8]}"

    _banner("2/3", "build assets — canonical cspm_asset records")
    return build_assets.run(tenant_id=args.tenant_id, scan_run_id=args.scan_run_id,
                            keep_raw=not args.no_raw)


def cmd_architecture(args):
    from orchestration.stages import build_architecture

    _banner("3/3", "build architecture — layered account diagram")
    # `ui/` is retired — the console reads out/scene.json directly. The flag
    # stays so an old invocation does not fail, and now does nothing.
    return build_architecture.run(region=args.region, ui=False)




def cmd_all(args):
    import time
    import uuid

    from store import pipeline as run_store

    if not args.scan_run_id:
        args.scan_run_id = f"scan_{uuid.uuid4().hex[:8]}"
    run_store.start_run(
        args.scan_run_id,
        tenant_id=args.tenant_id,
        trigger="manual",
        providers=[args.provider],
        regions=[args.region] if args.region else [],
    )

    stages = [
        ("discover", cmd_discover),
        ("assets", cmd_assets),
        ("architecture", cmd_architecture),
        ("compliance", cmd_compliance),
        ("finops", cmd_finops),
    ]
    results = {}
    args.dry_run = False
    args.list = False
    failed = None
    for stage_name, fn in stages:
        started = time.monotonic()
        try:
            result = fn(args)
            results[stage_name] = result
            records = next((result[k] for k in
                            ("assets", "findings", "recommendations", "canonical")
                            if isinstance(result, dict) and k in result
                            and isinstance(result[k], int)), None)
            run_store.record_stage(args.scan_run_id, stage_name, "success",
                                   records=records,
                                   duration_seconds=time.monotonic() - started)
        except Exception as exc:
            run_store.record_stage(args.scan_run_id, stage_name, "failed",
                                   error=exc,
                                   duration_seconds=time.monotonic() - started)
            failed = stage_name
            break

    totals = {
        "assets": results.get("assets", {}).get("canonical"),
        "findings": results.get("compliance", {}).get("findings"),
        "findings_by_domain": results.get("compliance", {}).get("by_domain"),
        "recommendations": results.get("finops", {}).get("recommendations"),
    }
    run_store.complete_run(args.scan_run_id,
                           "failed" if failed else "success", totals)
    if failed:
        raise RuntimeError(f"pipeline stopped at stage '{failed}' "
                           f"(run {args.scan_run_id})")

    print(f"\n{'═' * 60}\n  pipeline complete — run {args.scan_run_id}\n{'═' * 60}",
          file=sys.stderr)
    print(json.dumps(results, indent=2, default=str))
    return results


def _add_common_compliance(p):
    p.add_argument("--policies", help="comma-separated policy names (default: all)")
    p.add_argument("--resources", help="comma-separated resource ids/ARNs (default: all)")
    p.add_argument("--skip-run", action="store_true",
                   help="reuse the last custodian output (no AWS calls)")
    p.add_argument("--list", action="store_true", help="list available policies")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="1. collect raw resources from AWS")
    p.add_argument("--region", required=True)
    p.add_argument("--account")
    p.add_argument("--scope", default="scenario", choices=["scenario", "primary", "all"])
    p.add_argument("--types", help="comma-separated resource keys, overrides scope")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--offline", action="store_true", help="reuse the last collection")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("assets", help="2. normalise into cspm_asset records")
    p.add_argument("--tenant-id", default="local")
    p.add_argument("--scan-run-id", default="")
    # The full payload is kept by default. It was dropped for years, and the
    # cost was paid twice: a field nobody had declared was unavailable without
    # re-scanning the account, and S3 needed four new API calls to recover
    # values the collector had already fetched and thrown away. Storage is
    # cheaper than a re-scan, and a column can be added by re-reading.
    p.add_argument("--no-raw", action="store_true",
                   help="drop the raw payload, keeping only declared fields")
    p.set_defaults(func=cmd_assets)

    p = sub.add_parser("architecture", help="3. build the layered account diagram")
    p.add_argument("--region")
    # Kept so an old invocation does not fail; `ui/` is retired and this is
    # now a no-op.
    p.add_argument("--no-ui", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_architecture)



    p = sub.add_parser("all", help="run every stage in order")
    p.add_argument("--region", required=True)
    p.add_argument("--account")
    p.add_argument("--account-id", help="finops account (default: from assets)")
    p.add_argument("--scope", default="scenario", choices=["scenario", "primary", "all"])
    p.add_argument("--types")
    p.add_argument("--tenant-id", default="local")
    p.add_argument("--scan-run-id", default="")
    p.add_argument("--provider", default="aws", choices=["aws", "azure", "gcp"])
    p.add_argument("--pricing", action="store_true")
    p.add_argument("--no-ui", action="store_true")
    p.add_argument("--offline", action="store_true",
                   help="replay all stages from the last collection, no cloud calls")
    _add_common_compliance(p)
    p.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    if getattr(args, "offline", False) and args.command == "all":
        args.skip_run = True
    try:
        args.func(args)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
