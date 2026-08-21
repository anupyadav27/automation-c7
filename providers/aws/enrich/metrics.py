"""
CloudWatch metric enrichment.

The collector describes resources; some of the fields cost rules need are not
in any describe call — an S3 bucket's size and an instance's utilisation live
only in CloudWatch. This module is the one place that fetches them, keeping
the rule "only provider code calls AWS" intact.

    python -m providers.aws.enrich.metrics --region ap-southeast-1

Reads out/assets.json (the collector's output), adds metrics into each
asset's raw payload, writes it back. The assets stage then maps them into
canonical metadata as usual. Costs one CloudWatch call per bucket.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from cspm import paths

ASSETS = os.path.join(paths.OUT, "assets.json")


def _bucket_size_bytes(cw, bucket, storage_type="StandardStorage"):
    """Latest daily BucketSizeBytes datapoint, or None when the bucket is empty
    (CloudWatch publishes nothing for a bucket with no objects)."""
    end = datetime.now(timezone.utc)
    resp = cw.get_metric_statistics(
        Namespace="AWS/S3", MetricName="BucketSizeBytes",
        Dimensions=[{"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": storage_type}],
        StartTime=end - timedelta(days=3), EndTime=end,
        Period=86400, Statistics=["Average"],
    )
    points = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
    return points[-1]["Average"] if points else None


def enrich_s3(assets, region, verbose=True):
    import boto3

    cw = boto3.client("cloudwatch", region_name=region)
    buckets = [a for a in assets if a.get("resource_key") == "s3.bucket"]
    priced = 0
    for asset in buckets:
        name = asset.get("name") or asset.get("id")
        if not name:
            continue
        try:
            size = _bucket_size_bytes(cw, name)
        except Exception as exc:            # one bad bucket must not stop the sweep
            if verbose:
                print(f"  ! {name}: {str(exc)[:80]}", file=sys.stderr)
            continue
        raw = asset.setdefault("raw", {})
        if size is None:
            raw["SizeBytes"] = 0.0          # empty is a fact, not a gap
        else:
            raw["SizeBytes"] = float(size)
            priced += 1
    if verbose:
        print(f"s3: {len(buckets)} buckets, {priced} with data", file=sys.stderr)
    return priced


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--assets", default=ASSETS)
    args = parser.parse_args(argv)

    with open(args.assets) as fh:
        assets = json.load(fh)
    enrich_s3(assets, args.region)
    with open(args.assets, "w") as fh:
        json.dump(assets, fh, default=str)
    print(f"written {args.assets}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
