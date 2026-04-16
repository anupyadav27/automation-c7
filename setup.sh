#!/bin/bash
set -euo pipefail

# ==================================================================
# setup.sh — Create all AWS infrastructure using AWS CLI
#
# Creates: ECR, S3 output bucket, SQS queue, SNS topic,
#          IAM role + policy, Lambda function, API Gateway (HTTP API)
# ==================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/config.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1" >&2; }
info() { echo -e "${CYAN}[info]${NC} $1"; }

# ------------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------------
command -v aws >/dev/null 2>&1    || { err "aws CLI not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { err "docker not found"; exit 1; }
command -v jq >/dev/null 2>&1     || { err "jq not found (brew install jq)"; exit 1; }

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "Account: ${AWS_ACCOUNT_ID}  Region: ${AWS_REGION}"

# Derived names
FUNCTION_NAME="${PROJECT_NAME}-${ENVIRONMENT}"
ECR_REPO_NAME="${PROJECT_NAME}-${ENVIRONMENT}"
OUTPUT_BUCKET="${PROJECT_NAME}-output-${AWS_ACCOUNT_ID}-${ENVIRONMENT}"
SQS_QUEUE_NAME="${PROJECT_NAME}-notifications-${ENVIRONMENT}"
SNS_TOPIC_NAME="${PROJECT_NAME}-notifications-${ENVIRONMENT}"
IAM_ROLE_NAME="${PROJECT_NAME}-lambda-${ENVIRONMENT}"
IAM_POLICY_NAME="${PROJECT_NAME}-c7n-permissions-${ENVIRONMENT}"
API_NAME="${PROJECT_NAME}-api-${ENVIRONMENT}"
LOG_GROUP="/aws/apigateway/${PROJECT_NAME}-${ENVIRONMENT}"

# ==================================================================
# 1. ECR Repository
# ==================================================================
log "Creating ECR repository: ${ECR_REPO_NAME}"
ECR_REPO_URI=$(aws ecr describe-repositories \
  --repository-names "${ECR_REPO_NAME}" \
  --region "${AWS_REGION}" \
  --query 'repositories[0].repositoryUri' \
  --output text 2>/dev/null || true)

if [ -z "${ECR_REPO_URI}" ] || [ "${ECR_REPO_URI}" = "None" ]; then
  ECR_REPO_URI=$(aws ecr create-repository \
    --repository-name "${ECR_REPO_NAME}" \
    --region "${AWS_REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --image-tag-mutability MUTABLE \
    --query 'repository.repositoryUri' \
    --output text)
  log "Created ECR: ${ECR_REPO_URI}"
else
  info "ECR already exists: ${ECR_REPO_URI}"
fi

# ECR lifecycle — keep last 5 images
aws ecr put-lifecycle-policy \
  --repository-name "${ECR_REPO_NAME}" \
  --region "${AWS_REGION}" \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "Keep last 5 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 5
      },
      "action": { "type": "expire" }
    }]
  }' > /dev/null
log "ECR lifecycle policy set (keep last 5)"

# ==================================================================
# 2. S3 Output Bucket
# ==================================================================
log "Creating S3 output bucket: ${OUTPUT_BUCKET}"
if aws s3api head-bucket --bucket "${OUTPUT_BUCKET}" 2>/dev/null; then
  info "S3 bucket already exists: ${OUTPUT_BUCKET}"
else
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${OUTPUT_BUCKET}" --region "${AWS_REGION}"
  else
    aws s3api create-bucket --bucket "${OUTPUT_BUCKET}" --region "${AWS_REGION}" \
      --create-bucket-configuration LocationConstraint="${AWS_REGION}"
  fi
  log "Created S3 bucket: ${OUTPUT_BUCKET}"
fi

# Encryption
aws s3api put-bucket-encryption --bucket "${OUTPUT_BUCKET}" \
  --server-side-encryption-configuration '{
    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
  }'

# Block public access
aws s3api put-public-access-block --bucket "${OUTPUT_BUCKET}" \
  --public-access-block-configuration '{
    "BlockPublicAcls": true,
    "IgnorePublicAcls": true,
    "BlockPublicPolicy": true,
    "RestrictPublicBuckets": true
  }'

# Lifecycle — expire results after 90 days
aws s3api put-bucket-lifecycle-configuration --bucket "${OUTPUT_BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "expire-old-results",
      "Filter": {"Prefix": ""},
      "Status": "Enabled",
      "Expiration": { "Days": 90 }
    }]
  }'
log "S3 bucket configured (encryption, public block, 90d expiry)"

# ==================================================================
# 3. SQS Queue
# ==================================================================
log "Creating SQS queue: ${SQS_QUEUE_NAME}"
SQS_QUEUE_URL=$(aws sqs get-queue-url \
  --queue-name "${SQS_QUEUE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'QueueUrl' --output text 2>/dev/null || true)

if [ -z "${SQS_QUEUE_URL}" ]; then
  SQS_QUEUE_URL=$(aws sqs create-queue \
    --queue-name "${SQS_QUEUE_NAME}" \
    --region "${AWS_REGION}" \
    --attributes '{
      "MessageRetentionPeriod": "1209600",
      "VisibilityTimeout": "300"
    }' \
    --query 'QueueUrl' --output text)
  log "Created SQS queue: ${SQS_QUEUE_URL}"
else
  info "SQS queue already exists: ${SQS_QUEUE_URL}"
fi

SQS_QUEUE_ARN=$(aws sqs get-queue-attributes \
  --queue-url "${SQS_QUEUE_URL}" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' --output text)

# ==================================================================
# 4. SNS Topic + Email Subscription
# ==================================================================
log "Creating SNS topic: ${SNS_TOPIC_NAME}"
SNS_TOPIC_ARN=$(aws sns create-topic \
  --name "${SNS_TOPIC_NAME}" \
  --region "${AWS_REGION}" \
  --query 'TopicArn' --output text)
log "SNS topic: ${SNS_TOPIC_ARN}"

# Subscribe email (idempotent — won't duplicate)
aws sns subscribe \
  --topic-arn "${SNS_TOPIC_ARN}" \
  --protocol email \
  --notification-endpoint "${NOTIFICATION_EMAIL}" \
  --region "${AWS_REGION}" > /dev/null
warn "Check ${NOTIFICATION_EMAIL} inbox to CONFIRM the SNS subscription"

# ==================================================================
# 5. IAM Role for Lambda
# ==================================================================
log "Creating IAM role: ${IAM_ROLE_NAME}"
ROLE_ARN=$(aws iam get-role \
  --role-name "${IAM_ROLE_NAME}" \
  --query 'Role.Arn' --output text 2>/dev/null || true)

if [ -z "${ROLE_ARN}" ]; then
  ROLE_ARN=$(aws iam create-role \
    --role-name "${IAM_ROLE_NAME}" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": { "Service": "lambda.amazonaws.com" },
        "Action": "sts:AssumeRole"
      }]
    }' \
    --query 'Role.Arn' --output text)
  log "Created IAM role: ${ROLE_ARN}"

  # Wait for role propagation
  info "Waiting 10s for IAM role propagation..."
  sleep 10
else
  info "IAM role already exists: ${ROLE_ARN}"
fi

# Attach basic Lambda execution (CloudWatch logs)
aws iam attach-role-policy \
  --role-name "${IAM_ROLE_NAME}" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

# Inline policy for c7n permissions
log "Attaching c7n permissions policy"
cat > /tmp/c7n-policy.json <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ReadAndTag",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:GetBucketTagging",
        "s3:GetBucketLifecycleConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:GetMetricsConfiguration",
        "s3:GetBucketNotification",
        "s3:ListAllMyBuckets",
        "s3:ListBucket",
        "s3:PutBucketTagging",
        "s3:PutBucketVersioning",
        "s3:PutEncryptionConfiguration",
        "s3:GetBucketVersioning",
        "s3:GetBucketLogging",
        "s3:GetBucketPolicy",
        "s3:GetBucketAcl",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketReplication",
        "s3:GetAccelerateConfiguration"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2EBSReadAndManage",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeVolumeStatus",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeImages",
        "ec2:DescribeLaunchTemplates",
        "ec2:DescribeLaunchTemplateVersions",
        "ec2:DescribeSnapshots",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeAddresses",
        "ec2:CreateSnapshot",
        "ec2:CreateTags",
        "ec2:DeleteTags",
        "ec2:DeleteVolume",
        "ec2:DeleteNetworkInterface",
        "ec2:ReleaseAddress",
        "ec2:DeregisterImage",
        "ec2:DeleteSnapshot",
        "ec2:ModifyInstanceMetadataOptions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AutoScaling",
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeLaunchConfigurations",
        "autoscaling:DescribeAutoScalingGroups"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SQSSend",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:GetQueueUrl"
      ],
      "Resource": "${SQS_QUEUE_ARN}"
    },
    {
      "Sid": "S3OutputBucket",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::${OUTPUT_BUCKET}/*"
    }
  ]
}
POLICY

aws iam put-role-policy \
  --role-name "${IAM_ROLE_NAME}" \
  --policy-name "${IAM_POLICY_NAME}" \
  --policy-document file:///tmp/c7n-policy.json
rm -f /tmp/c7n-policy.json
log "IAM policy attached"

# ==================================================================
# 6. Build & Push Container Image
# ==================================================================
log "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

log "Building container image..."
docker build --platform linux/amd64 -t c7n-automation "${SCRIPT_DIR}"

log "Pushing to ECR..."
docker tag c7n-automation:latest "${ECR_REPO_URI}:latest"
docker push "${ECR_REPO_URI}:latest"
log "Image pushed: ${ECR_REPO_URI}:latest"

# ==================================================================
# 7. Lambda Function
# ==================================================================
log "Creating Lambda function: ${FUNCTION_NAME}"
LAMBDA_EXISTS=$(aws lambda get-function \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" 2>/dev/null && echo "yes" || echo "no")

if [ "${LAMBDA_EXISTS}" = "no" ]; then
  aws lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --region "${AWS_REGION}" \
    --package-type Image \
    --code "ImageUri=${ECR_REPO_URI}:latest" \
    --role "${ROLE_ARN}" \
    --memory-size "${LAMBDA_MEMORY}" \
    --timeout "${LAMBDA_TIMEOUT}" \
    --environment "Variables={POLICY_DIR=/app/policies,OUTPUT_BUCKET=${OUTPUT_BUCKET},C7N_REGION=${AWS_REGION}}" \
    > /dev/null
  log "Created Lambda function"
else
  info "Lambda function already exists — updating code..."
  aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --image-uri "${ECR_REPO_URI}:latest" \
    --region "${AWS_REGION}" \
    --publish > /dev/null
  log "Lambda function code updated"
fi

# Wait for Lambda to be active
log "Waiting for Lambda to become active..."
aws lambda wait function-active-v2 \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"

LAMBDA_ARN=$(aws lambda get-function \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Configuration.FunctionArn' --output text)

# ==================================================================
# 8. API Gateway (HTTP API)
# ==================================================================
log "Creating API Gateway: ${API_NAME}"

# Check if API already exists
API_ID=$(aws apigatewayv2 get-apis \
  --region "${AWS_REGION}" \
  --query "Items[?Name=='${API_NAME}'].ApiId" \
  --output text 2>/dev/null || true)

if [ -z "${API_ID}" ] || [ "${API_ID}" = "None" ]; then
  API_ID=$(aws apigatewayv2 create-api \
    --name "${API_NAME}" \
    --protocol-type HTTP \
    --region "${AWS_REGION}" \
    --cors-configuration '{
      "AllowOrigins": ["*"],
      "AllowMethods": ["GET", "POST", "OPTIONS"],
      "AllowHeaders": ["Content-Type", "X-Api-Key"],
      "MaxAge": 300
    }' \
    --query 'ApiId' --output text)
  log "Created API: ${API_ID}"
else
  info "API Gateway already exists: ${API_ID}"
fi

API_ENDPOINT=$(aws apigatewayv2 get-api \
  --api-id "${API_ID}" \
  --region "${AWS_REGION}" \
  --query 'ApiEndpoint' --output text)

# Integration (Lambda proxy)
log "Creating Lambda integration..."
INTEGRATION_ID=$(aws apigatewayv2 get-integrations \
  --api-id "${API_ID}" \
  --region "${AWS_REGION}" \
  --query "Items[?IntegrationUri=='${LAMBDA_ARN}'].IntegrationId" \
  --output text 2>/dev/null || true)

if [ -z "${INTEGRATION_ID}" ] || [ "${INTEGRATION_ID}" = "None" ]; then
  INTEGRATION_ID=$(aws apigatewayv2 create-integration \
    --api-id "${API_ID}" \
    --integration-type AWS_PROXY \
    --integration-uri "${LAMBDA_ARN}" \
    --payload-format-version "2.0" \
    --region "${AWS_REGION}" \
    --query 'IntegrationId' --output text)
  log "Created integration: ${INTEGRATION_ID}"
else
  info "Integration already exists: ${INTEGRATION_ID}"
fi

# Routes: POST /run and GET /run
for METHOD in POST GET; do
  ROUTE_EXISTS=$(aws apigatewayv2 get-routes \
    --api-id "${API_ID}" \
    --region "${AWS_REGION}" \
    --query "Items[?RouteKey=='${METHOD} /run'].RouteId" \
    --output text 2>/dev/null || true)

  if [ -z "${ROUTE_EXISTS}" ] || [ "${ROUTE_EXISTS}" = "None" ]; then
    aws apigatewayv2 create-route \
      --api-id "${API_ID}" \
      --route-key "${METHOD} /run" \
      --target "integrations/${INTEGRATION_ID}" \
      --region "${AWS_REGION}" > /dev/null
    log "Created route: ${METHOD} /run"
  else
    info "Route ${METHOD} /run already exists"
  fi
done

# Default stage with auto-deploy
STAGE_EXISTS=$(aws apigatewayv2 get-stages \
  --api-id "${API_ID}" \
  --region "${AWS_REGION}" \
  --query "Items[?StageName=='\$default'].StageName" \
  --output text 2>/dev/null || true)

if [ -z "${STAGE_EXISTS}" ] || [ "${STAGE_EXISTS}" = "None" ]; then
  # Create CloudWatch log group for API
  aws logs create-log-group \
    --log-group-name "${LOG_GROUP}" \
    --region "${AWS_REGION}" 2>/dev/null || true
  aws logs put-retention-policy \
    --log-group-name "${LOG_GROUP}" \
    --retention-in-days 30 \
    --region "${AWS_REGION}"

  LOG_GROUP_ARN=$(aws logs describe-log-groups \
    --log-group-name-prefix "${LOG_GROUP}" \
    --region "${AWS_REGION}" \
    --query "logGroups[0].arn" --output text)

  aws apigatewayv2 create-stage \
    --api-id "${API_ID}" \
    --stage-name '$default' \
    --auto-deploy \
    --region "${AWS_REGION}" \
    --access-log-settings "{
      \"DestinationArn\": \"${LOG_GROUP_ARN}\",
      \"Format\": \"{\\\"requestId\\\":\\\"\\\$context.requestId\\\",\\\"ip\\\":\\\"\\\$context.identity.sourceIp\\\",\\\"method\\\":\\\"\\\$context.httpMethod\\\",\\\"status\\\":\\\"\\\$context.status\\\"}\"
    }" > /dev/null
  log "Created \$default stage with auto-deploy"
else
  info "\$default stage already exists"
fi

# Lambda permission for API Gateway
log "Adding API Gateway invoke permission to Lambda..."
aws lambda add-permission \
  --function-name "${FUNCTION_NAME}" \
  --statement-id "AllowAPIGatewayInvoke" \
  --action "lambda:InvokeFunction" \
  --principal "apigateway.amazonaws.com" \
  --source-arn "arn:aws:execute-api:${AWS_REGION}:${AWS_ACCOUNT_ID}:${API_ID}/*/*" \
  --region "${AWS_REGION}" 2>/dev/null || info "Permission already exists"

# SQS queue policy — allow Lambda to send
log "Setting SQS queue policy..."
cat > /tmp/sqs-policy.json <<SQSPOLICY
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowLambdaSend",
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sqs:SendMessage",
    "Resource": "${SQS_QUEUE_ARN}",
    "Condition": {
      "ArnEquals": { "aws:SourceArn": "${LAMBDA_ARN}" }
    }
  }]
}
SQSPOLICY

aws sqs set-queue-attributes \
  --queue-url "${SQS_QUEUE_URL}" \
  --attributes "Policy=$(cat /tmp/sqs-policy.json | jq -c .)" \
  --region "${AWS_REGION}"
rm -f /tmp/sqs-policy.json

# ==================================================================
# 9. Save resource IDs for deploy.sh and teardown.sh
# ==================================================================
cat > "${SCRIPT_DIR}/.infra-state.env" <<STATE
# Auto-generated by setup.sh — do not edit manually
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID}
AWS_REGION=${AWS_REGION}
ECR_REPO_URI=${ECR_REPO_URI}
ECR_REPO_NAME=${ECR_REPO_NAME}
FUNCTION_NAME=${FUNCTION_NAME}
OUTPUT_BUCKET=${OUTPUT_BUCKET}
SQS_QUEUE_URL=${SQS_QUEUE_URL}
SQS_QUEUE_NAME=${SQS_QUEUE_NAME}
SQS_QUEUE_ARN=${SQS_QUEUE_ARN}
SNS_TOPIC_ARN=${SNS_TOPIC_ARN}
IAM_ROLE_NAME=${IAM_ROLE_NAME}
IAM_POLICY_NAME=${IAM_POLICY_NAME}
ROLE_ARN=${ROLE_ARN}
LAMBDA_ARN=${LAMBDA_ARN}
API_ID=${API_ID}
API_ENDPOINT=${API_ENDPOINT}
API_NAME=${API_NAME}
LOG_GROUP=${LOG_GROUP}
STATE

log "Infrastructure state saved to .infra-state.env"

# ==================================================================
# Done
# ==================================================================
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} Setup complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  API endpoint:  ${API_ENDPOINT}/run"
echo ""
echo "  Test (dry run):"
echo "    curl -X POST '${API_ENDPOINT}/run' \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"policy\": \"s3\", \"dryrun\": \"true\"}'"
echo ""
echo "  Other policies: ebs, ami, all"
echo ""
warn "Remember to confirm the SNS email subscription in ${NOTIFICATION_EMAIL}"
echo ""
