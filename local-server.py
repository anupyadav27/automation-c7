"""
Local development server — runs Cloud Custodian policies directly
using your local AWS credentials (env vars or ~/.aws/credentials).

Usage:
  export AWS_ACCESS_KEY_ID=...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_DEFAULT_REGION=ap-south-1   # optional, defaults to ap-south-1
  python local-server.py

  OR use the helper script:
  ./run-local.sh

Listens on http://localhost:8080
Same API as the Lambda — the UI works against both without changes.
"""

import json
import os
import sys
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc)

# Point to policies relative to this file (moved under engines/ in the merge)
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("POLICY_DIR", os.path.join(HERE, "engines", "compliance", "policies"))
os.environ.setdefault("C7N_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))

# Reuse all logic from handler.py
sys.path.insert(0, HERE)
import handler as h

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("local-server")

PORT = int(os.environ.get("LOCAL_PORT", 8080))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def _send(self, status, body: dict):
        data = json.dumps(body, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # CORS — lets the UI on :3001 talk to this server on :8080
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/health"):
            info = {"status": "ok", "mode": "local",
                    "region": os.environ.get("C7N_REGION"),
                    "policy_dir": os.environ.get("POLICY_DIR")}
            try:
                import boto3
                sts = boto3.client("sts")
                identity = sts.get_caller_identity()
                info["account_id"] = identity["Account"]
                info["arn"] = identity["Arn"]
            except Exception as e:
                info["account_id"] = "unknown"
                info["arn_error"] = str(e)
            self._send(200, info)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            params = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return

        from datetime import datetime

        # ── /build endpoint (dynamic policy) ─────────────────
        if self.path == "/build":
            spec   = params.get("spec")
            dryrun = str(params.get("dryrun", "true")).lower() == "true"
            region = params.get("region") or os.environ.get("C7N_REGION")
            if not spec or not isinstance(spec, dict) or not spec.get("resource"):
                self._send(400, {"error": "spec.resource is required"})
                return
            log.info("build  resource=%s  filters=%d  dryrun=%s",
                     spec.get("resource"), len(spec.get("filters", [])), dryrun)
            result = h._run_policy_from_spec(spec, dryrun, region)
            log.info("  %-45s  %s  resources=%s",
                     result["policy"], result["status"], result.get("resources_found", {}))
            self._send(200, result)
            return

        # ── /action endpoint ───────────────────────────────
        if self.path == "/action":
            policy_name  = params.get("policy")
            resource_ids = params.get("resource_ids", [])
            action_type  = params.get("action")
            region       = params.get("region") or os.environ.get("C7N_REGION")
            if not policy_name or not action_type:
                self._send(400, {"error": "policy and action are required"})
                return
            log.info("action  policy=%s  action=%s  ids=%s", policy_name, action_type, resource_ids)
            result = h._run_action_on_resources(policy_name, resource_ids, action_type, region)
            self._send(200, result)
            return

        # ── /run endpoint ──────────────────────────────────
        region = params.get("region") or os.environ.get("C7N_REGION")
        dryrun = str(params.get("dryrun", "true")).lower() == "true"

        # Rebuild index on every list call so YAML edits are picked up
        policy_input  = params.get("policy", "all")
        policies_list = params.get("policies")

        if policy_input == "list":
            h.POLICY_INDEX.clear()
            h.POLICY_INDEX.update(h._build_policy_index())
            self._send(200, h._list_policies())
            return

        # Resolve: array of names  OR  single name/group
        if isinstance(policies_list, list) and policies_list:
            resolved = []
            for name in policies_list:
                r = h._resolve_policies(name, region)
                if r:
                    resolved.extend(r)
            if not resolved:
                self._send(400, {"error": "No valid policies found in the provided list"})
                return
            requested_label = f"{len(policies_list)} policies"
            log.info("policies=%s  dryrun=%s  region=%s", policies_list, dryrun, region)
        else:
            resolved = h._resolve_policies(policy_input, region)
            if resolved is None:
                self._send(400, {
                    "error": f"Unknown policy or group: '{policy_input}'",
                    "hint": 'Use {"policy": "list"} to see all available policies',
                })
                return
            requested_label = policy_input
            log.info("policy=%s  dryrun=%s  region=%s", policy_input, dryrun, region)

        # One custodian invocation for the whole selection — policies sharing
        # a resource type reuse a single API sweep (see handler.CACHE_PERIOD).
        results = h._run_policies_grouped(resolved, dryrun, region)
        for result in results:
            log.info("  %-45s  %s  resources=%s",
                     result["policy"], result["status"],
                     result.get("resources_found", {}))

        try:
            import boto3
            identity = boto3.client("sts").get_caller_identity()
            account_info = {"account_id": identity["Account"], "arn": identity["Arn"], "region": region}
        except Exception:
            account_info = {"account_id": "unknown", "region": region}

        self._send(200, {
            "execution_time":    _now().isoformat(),
            "dryrun":            dryrun,
            "region":            region,
            "account":           account_info,
            "requested":         requested_label,
            "policies_executed": len(results),
            "results":           results,
        })


if __name__ == "__main__":
    # Validate AWS credentials exist before starting
    has_env_creds = (
        os.environ.get("AWS_ACCESS_KEY_ID") and
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    has_profile = os.path.exists(os.path.expanduser("~/.aws/credentials"))

    if not has_env_creds and not has_profile:
        print("ERROR: No AWS credentials found.")
        print("Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, or configure ~/.aws/credentials")
        sys.exit(1)

    region = os.environ.get("C7N_REGION")
    cred_source = "env vars" if has_env_creds else "~/.aws/credentials"
    print(f"\n  Cloud Custodian — local server")
    print(f"  Listening : http://localhost:{PORT}")
    print(f"  Region    : {region}")
    print(f"  Credentials: {cred_source}")
    print(f"  Policies  : {os.environ.get('POLICY_DIR')}")
    print(f"  Dry-run   : controlled per request (default true)\n")

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
