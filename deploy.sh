#!/bin/bash
set -euo pipefail

# ==================================================================
# deploy.sh — Rebuild & push container, update Lambda
# Run this after changing policies or handler code.
# (Run setup.sh first to create infrastructure)
# ==================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="${SCRIPT_DIR}/.infra-state.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
err() { echo -e "${RED}[error]${NC} $1" >&2; }

# Load infra state
if [ ! -f "${STATE_FILE}" ]; then
  err ".infra-state.env not found — run setup.sh first"
  exit 1
fi
source "${STATE_FILE}"

# Pre-flight
command -v aws >/dev/null 2>&1    || { err "aws CLI not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { err "docker not found"; exit 1; }

log "Account: ${AWS_ACCOUNT_ID}  Region: ${AWS_REGION}"
log "Function: ${FUNCTION_NAME}"

# ------------------------------------------------------------------
# 1. Build container
# ------------------------------------------------------------------
log "Building container image..."
docker build --platform linux/amd64 -t c7n-automation "${SCRIPT_DIR}"

# ------------------------------------------------------------------
# 2. Push to ECR
# ------------------------------------------------------------------
log "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

log "Pushing to ECR..."
docker tag c7n-automation:latest "${ECR_REPO_URI}:latest"
docker push "${ECR_REPO_URI}:latest"

# ------------------------------------------------------------------
# 3. Update Lambda
# ------------------------------------------------------------------
log "Updating Lambda function code..."
aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --image-uri "${ECR_REPO_URI}:latest" \
  --region "${AWS_REGION}" \
  --publish > /dev/null

log "Waiting for Lambda update..."
aws lambda wait function-updated-v2 \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
log "Deploy complete!"
echo ""
echo "  API endpoint:  ${API_ENDPOINT}/run"
echo ""
echo "  Test:"
echo "    curl -X POST '${API_ENDPOINT}/run' -H 'Content-Type: application/json' -d '{\"policy\": \"s3\", \"dryrun\": \"true\"}'"
echo ""
