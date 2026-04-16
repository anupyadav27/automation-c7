#!/usr/bin/env bash
# ---------------------------------------------------------------
# run-local.sh  — Start the local Cloud Custodian API server
#
# Usage (choose one):
#
#   1. Interactive prompts (safest — keys never appear in shell history):
#        ./run-local.sh
#
#   2. Pass via flags:
#        ./run-local.sh --access-key AKIA... --secret-key wJalr... --region ap-south-1
#
#   3. Already exported in shell:
#        export AWS_ACCESS_KEY_ID=AKIA...
#        export AWS_SECRET_ACCESS_KEY=wJalr...
#        ./run-local.sh
#
#   4. Use ~/.aws/credentials profile:
#        AWS_PROFILE=my-profile ./run-local.sh
#
# The server starts on http://localhost:8080
# Point your UI Settings to http://localhost:8080 or leave blank (default).
# ---------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults ---
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

# --- Parse flags ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --access-key)   AWS_ACCESS_KEY_ID="$2";     shift 2 ;;
    --secret-key)   AWS_SECRET_ACCESS_KEY="$2"; shift 2 ;;
    --region)       REGION="$2";               shift 2 ;;
    --port)         LOCAL_PORT="$2";            shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# --- Prompt if creds not in env and not in ~/.aws/credentials ---
if [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "${AWS_PROFILE:-}" && ! -f "$HOME/.aws/credentials" ]]; then
  echo ""
  echo "  Enter AWS credentials (input is hidden)"
  read -rsp "  AWS Access Key ID     : " AWS_ACCESS_KEY_ID; echo
  read -rsp "  AWS Secret Access Key : " AWS_SECRET_ACCESS_KEY; echo
  echo ""
fi

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"
export AWS_DEFAULT_REGION="$REGION"
export C7N_REGION="$REGION"
export POLICY_DIR="$HERE/policies"
export LOCAL_PORT="${LOCAL_PORT:-8080}"

# --- Check Python + c7n ---
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.9+."
  exit 1
fi

if ! python3 -c "import c7n" 2>/dev/null; then
  echo ""
  echo "  c7n not installed — installing into a venv..."
  python3 -m venv "$HERE/.venv-local" --prompt c7n-local
  # shellcheck disable=SC1091
  source "$HERE/.venv-local/bin/activate"
  pip install -q c7n==0.9.35 pyyaml boto3
  echo "  Done."
  echo ""
else
  # Activate venv if present
  if [[ -f "$HERE/.venv-local/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$HERE/.venv-local/bin/activate"
  fi
fi

echo ""
echo "  Starting local server → http://localhost:${LOCAL_PORT}"
echo "  Press Ctrl+C to stop."
echo ""

exec python3 "$HERE/local-server.py"
