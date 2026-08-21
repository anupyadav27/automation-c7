#!/usr/bin/env bash
# End-to-end smoke: API contract + console routes.
#   scripts/smoke.sh [api_url] [console_url]
set -uo pipefail

API=${1:-http://localhost:8090}
CONSOLE=${2:-http://localhost:3100}
AUTH=${API_TOKEN:+-H "Authorization: Bearer $API_TOKEN"}
pass=0; fail=0

check() { # name, command
  if eval "$2" >/dev/null 2>&1; then
    echo "  ok   $1"; pass=$((pass+1))
  else
    echo "  FAIL $1"; fail=$((fail+1))
  fi
}

echo "API $API"
check "health"              "curl -sf $API/health"
for path in \
  "/api/v1/inventory/assets?limit=1" \
  "/api/v1/posture/findings?limit=1" \
  "/api/v1/finops/recommendations?limit=1" \
  "/api/v1/rules?kind=compliance&limit=1" \
  "/api/v1/rules?kind=cost&limit=1" \
  "/api/v1/pipeline/runs?limit=1" \
  "/api/v1/overview"; do
  check "GET $path" "curl -sf $AUTH '$API$path' | python3 -c 'import json,sys; json.load(sys.stdin)'"
done
check "envelope shape" \
  "curl -sf $AUTH '$API/api/v1/inventory/assets?limit=1' | python3 -c \"import json,sys; d=json.load(sys.stdin); assert 'data' in d and 'pagination' in d and 'meta' in d\""
check "csv export" \
  "curl -sf $AUTH '$API/api/v1/inventory/assets?limit=5&format=csv' | head -1 | grep -q resource_uid"
check "404 on unknown asset" \
  "test \$(curl -s -o /dev/null -w '%{http_code}' $AUTH '$API/api/v1/inventory/assets/nope') = 404"

echo "Console $CONSOLE"
for route in / /inventory /compliance /finops /policies /runs /architecture /settings; do
  check "GET $route" "test \$(curl -s -o /dev/null -w '%{http_code}' $CONSOLE$route) = 200"
done

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
