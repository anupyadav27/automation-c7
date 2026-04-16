#!/bin/bash
set -euo pipefail

# ==================================================================
# teardown.sh — Remove all AWS resources created by setup.sh
# ==================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="${SCRIPT_DIR}/.infra-state.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[teardown]${NC} $1"; }
warn() { echo -e "${YELLOW}[teardown]${NC} $1"; }
err()  { echo -e "${RED}[teardown]${NC} $1" >&2; }

if [ ! -f "${STATE_FILE}" ]; then
  err ".infra-state.env not found — nothing to tear down"
  exit 1
fi
source "${STATE_FILE}"

echo ""
echo -e "${RED}========================================${NC}"
echo -e "${RED} This will DELETE all c7n infrastructure${NC}"
echo -e "${RED}========================================${NC}"
echo ""
echo "  Region:   ${AWS_REGION}"
echo "  Lambda:   ${FUNCTION_NAME}"
echo "  API:      ${API_NAME} (${API_ID})"
echo "  ECR:      ${ECR_REPO_NAME}"
echo "  S3:       ${OUTPUT_BUCKET}"
echo "  SQS:      ${SQS_QUEUE_NAME}"
echo "  SNS:      ${SNS_TOPIC_ARN}"
echo "  IAM Role: ${IAM_ROLE_NAME}"
echo ""
read -p "Type 'yes' to confirm: " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

# ------------------------------------------------------------------
# 1. Delete API Gateway
# ------------------------------------------------------------------
log "Deleting API Gateway: ${API_ID}"
aws apigatewayv2 delete-api \
  --api-id "${API_ID}" \
  --region "${AWS_REGION}" 2>/dev/null || warn "API Gateway not found"

# ------------------------------------------------------------------
# 2. Delete Lambda function
# ------------------------------------------------------------------
log "Deleting Lambda: ${FUNCTION_NAME}"
aws lambda delete-function \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" 2>/dev/null || warn "Lambda not found"

# ------------------------------------------------------------------
# 3. Delete ECR repository (force — deletes all images)
# ------------------------------------------------------------------
log "Deleting ECR repository: ${ECR_REPO_NAME}"
aws ecr delete-repository \
  --repository-name "${ECR_REPO_NAME}" \
  --region "${AWS_REGION}" \
  --force 2>/dev/null || warn "ECR not found"

# ------------------------------------------------------------------
# 4. Empty and delete S3 bucket
# ------------------------------------------------------------------
log "Emptying and deleting S3 bucket: ${OUTPUT_BUCKET}"
aws s3 rm "s3://${OUTPUT_BUCKET}" --recursive 2>/dev/null || true
aws s3api delete-bucket \
  --bucket "${OUTPUT_BUCKET}" \
  --region "${AWS_REGION}" 2>/dev/null || warn "S3 bucket not found"

# ------------------------------------------------------------------
# 5. Delete SQS queue
# ------------------------------------------------------------------
log "Deleting SQS queue: ${SQS_QUEUE_NAME}"
aws sqs delete-queue \
  --queue-url "${SQS_QUEUE_URL}" \
  --region "${AWS_REGION}" 2>/dev/null || warn "SQS queue not found"

# ------------------------------------------------------------------
# 6. Delete SNS topic
# ------------------------------------------------------------------
log "Deleting SNS topic"
aws sns delete-topic \
  --topic-arn "${SNS_TOPIC_ARN}" \
  --region "${AWS_REGION}" 2>/dev/null || warn "SNS topic not found"

# ------------------------------------------------------------------
# 7. Delete IAM role (detach policies first)
# ------------------------------------------------------------------
log "Deleting IAM role: ${IAM_ROLE_NAME}"
aws iam delete-role-policy \
  --role-name "${IAM_ROLE_NAME}" \
  --policy-name "${IAM_POLICY_NAME}" 2>/dev/null || true
aws iam detach-role-policy \
  --role-name "${IAM_ROLE_NAME}" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true
aws iam delete-role \
  --role-name "${IAM_ROLE_NAME}" 2>/dev/null || warn "IAM role not found"

# ------------------------------------------------------------------
# 8. Delete CloudWatch log groups
# ------------------------------------------------------------------
log "Deleting CloudWatch log groups"
aws logs delete-log-group \
  --log-group-name "${LOG_GROUP}" \
  --region "${AWS_REGION}" 2>/dev/null || true
aws logs delete-log-group \
  --log-group-name "/aws/lambda/${FUNCTION_NAME}" \
  --region "${AWS_REGION}" 2>/dev/null || true

# ------------------------------------------------------------------
# 9. Clean up state file
# ------------------------------------------------------------------
rm -f "${STATE_FILE}"

echo ""
log "All resources deleted."
echo ""
