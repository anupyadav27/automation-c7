-- Migration: Seed Relationship Templates
-- Version: 2.0
-- Date: 2026-01-23
-- Description: Load predefined relationship templates for AWS resources

-- ============================================================================
-- EC2 RELATIONSHIPS
-- ============================================================================

-- EC2 Instance relationships
INSERT INTO resource_relationship_templates 
(source_resource_type, relation_type, target_resource_type, source_field, source_field_item, target_uid_pattern, is_array, conditional, priority, description) 
VALUES
('ec2.instance', 'attached_to', 'ec2.security-group', '["SecurityGroups"]', 'GroupId', 'arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}', TRUE, NULL, 10, 'Instance security group attachment'),
('ec2.instance', 'contained_by', 'ec2.subnet', '["SubnetId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}', FALSE, NULL, 10, 'Instance in subnet'),
('ec2.instance', 'uses', 'iam.instance-profile', '["IamInstanceProfile", "Arn"]', NULL, '{Arn}', FALSE, 'IamInstanceProfile IS NOT NULL', 20, 'Instance uses IAM profile'),
('ec2.instance', 'attached_to', 'ec2.volume', '["BlockDeviceMappings"]', 'Ebs.VolumeId', 'arn:aws:ec2:{region}:{account_id}:volume/{VolumeId}', TRUE, NULL, 15, 'Instance EBS volumes'),
('ec2.instance', 'runs_on', 'ec2.host', '["Placement", "HostId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:dedicated-host/{HostId}', FALSE, 'Placement.Tenancy == "host"', 30, 'Instance on dedicated host'),

-- EC2 Subnet relationships
('ec2.subnet', 'contained_by', 'ec2.vpc', '["VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, NULL, 10, 'Subnet in VPC'),
('ec2.subnet', 'attached_to', 'ec2.network-acl', '["NetworkAclId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:network-acl/{NetworkAclId}', FALSE, 'NetworkAclId IS NOT NULL', 20, 'Subnet NACL'),
('ec2.subnet', 'attached_to', 'ec2.route-table', '["RouteTableId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:route-table/{RouteTableId}', FALSE, 'RouteTableId IS NOT NULL', 20, 'Subnet route table'),

-- EC2 Security Group relationships
('ec2.security-group', 'contained_by', 'ec2.vpc', '["VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, NULL, 10, 'Security group in VPC'),
('ec2.security-group', 'attached_to', 'ec2.security-group', '["IpPermissions"]', 'UserIdGroupPairs.GroupId', 'arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}', TRUE, NULL, 30, 'SG rule references'),

-- EC2 Route Table relationships
('ec2.route-table', 'contained_by', 'ec2.vpc', '["VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, NULL, 10, 'Route table in VPC'),
('ec2.route-table', 'routes_to', 'ec2.internet-gateway', '["Routes"]', 'GatewayId', 'arn:aws:ec2:{region}:{account_id}:internet-gateway/{GatewayId}', TRUE, 'GatewayId LIKE "igw-%"', 15, 'Routes to IGW'),
('ec2.route-table', 'routes_to', 'ec2.nat-gateway', '["Routes"]', 'NatGatewayId', 'arn:aws:ec2:{region}:{account_id}:natgateway/{NatGatewayId}', TRUE, 'NatGatewayId IS NOT NULL', 15, 'Routes to NAT'),
('ec2.route-table', 'routes_to', 'ec2.transit-gateway', '["Routes"]', 'TransitGatewayId', 'arn:aws:ec2:{region}:{account_id}:transit-gateway/{TransitGatewayId}', TRUE, 'TransitGatewayId IS NOT NULL', 15, 'Routes to TGW'),
('ec2.route-table', 'routes_to', 'ec2.vpc-peering-connection', '["Routes"]', 'VpcPeeringConnectionId', 'arn:aws:ec2:{region}:{account_id}:vpc-peering-connection/{VpcPeeringConnectionId}', TRUE, 'VpcPeeringConnectionId IS NOT NULL', 15, 'Routes to VPC peering'),

-- EC2 Volume & Snapshot encryption
('ec2.volume', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, 'arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}', FALSE, 'Encrypted = TRUE AND KmsKeyId IS NOT NULL', 10, 'Volume encryption'),
('ec2.snapshot', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, 'arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}', FALSE, 'Encrypted = TRUE AND KmsKeyId IS NOT NULL', 10, 'Snapshot encryption'),

-- ============================================================================
-- LAMBDA RELATIONSHIPS
-- ============================================================================

('lambda.function', 'uses', 'iam.role', '["Role"]', NULL, '{Role}', FALSE, NULL, 10, 'Lambda execution role'),
('lambda.function', 'contained_by', 'ec2.vpc', '["VpcConfig", "VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, 'VpcConfig IS NOT NULL', 20, 'Lambda in VPC'),
('lambda.function', 'attached_to', 'ec2.subnet', '["VpcConfig", "SubnetIds"]', NULL, 'arn:aws:ec2:{region}:{account_id}:subnet/{item}', TRUE, 'VpcConfig IS NOT NULL', 20, 'Lambda subnets'),
('lambda.function', 'attached_to', 'ec2.security-group', '["VpcConfig", "SecurityGroupIds"]', NULL, 'arn:aws:ec2:{region}:{account_id}:security-group/{item}', TRUE, 'VpcConfig IS NOT NULL', 20, 'Lambda security groups'),
('lambda.function', 'encrypted_by', 'kms.key', '["KMSKeyArn"]', NULL, '{KMSKeyArn}', FALSE, 'KMSKeyArn IS NOT NULL', 15, 'Lambda environment encryption'),
('lambda.function', 'logging_enabled_to', 'logs.group', '["FunctionName"]', NULL, 'arn:aws:logs:{region}:{account_id}:log-group:/aws/lambda/{FunctionName}', FALSE, NULL, 5, 'Implicit CloudWatch Logs'),

-- Lambda Event Source Mappings
('lambda.event-source-mapping', 'triggers', 'lambda.function', '["FunctionArn"]', NULL, '{FunctionArn}', FALSE, NULL, 10, 'ESM triggers function'),
('lambda.event-source-mapping', 'subscribes_to', 'dynamodb.stream', '["EventSourceArn"]', NULL, '{EventSourceArn}', FALSE, 'EventSourceArn LIKE "%dynamodb%"', 15, 'Lambda polls DynamoDB stream'),
('lambda.event-source-mapping', 'subscribes_to', 'kinesis.stream', '["EventSourceArn"]', NULL, '{EventSourceArn}', FALSE, 'EventSourceArn LIKE "%kinesis%"', 15, 'Lambda polls Kinesis'),
('lambda.event-source-mapping', 'subscribes_to', 'sqs.queue', '["EventSourceArn"]', NULL, '{EventSourceArn}', FALSE, 'EventSourceArn LIKE "%sqs%"', 15, 'Lambda polls SQS'),

-- ============================================================================
-- RDS RELATIONSHIPS
-- ============================================================================

('rds.instance', 'contained_by', 'ec2.vpc', '["DBSubnetGroup", "VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, 'DBSubnetGroup IS NOT NULL', 10, 'RDS in VPC'),
('rds.instance', 'attached_to', 'ec2.security-group', '["VpcSecurityGroups"]', 'VpcSecurityGroupId', 'arn:aws:ec2:{region}:{account_id}:security-group/{VpcSecurityGroupId}', TRUE, NULL, 10, 'RDS security groups'),
('rds.instance', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, '{KmsKeyId}', FALSE, 'StorageEncrypted = TRUE', 10, 'RDS encryption'),
('rds.instance', 'member_of', 'rds.cluster', '["DBClusterIdentifier"]', NULL, 'arn:aws:rds:{region}:{account_id}:cluster:{DBClusterIdentifier}', FALSE, 'DBClusterIdentifier IS NOT NULL', 15, 'RDS cluster member'),

('rds.cluster', 'contained_by', 'ec2.vpc', '["DBSubnetGroup", "VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, 'DBSubnetGroup IS NOT NULL', 10, 'RDS cluster in VPC'),
('rds.cluster', 'attached_to', 'ec2.security-group', '["VpcSecurityGroups"]', 'VpcSecurityGroupId', 'arn:aws:ec2:{region}:{account_id}:security-group:{VpcSecurityGroupId}', TRUE, NULL, 10, 'RDS cluster SGs'),
('rds.cluster', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, '{KmsKeyId}', FALSE, 'StorageEncrypted = TRUE', 10, 'RDS cluster encryption'),

-- ============================================================================
-- ELB RELATIONSHIPS
-- ============================================================================

('elbv2.load-balancer', 'contained_by', 'ec2.vpc', '["VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}', FALSE, NULL, 10, 'ALB/NLB in VPC'),
('elbv2.load-balancer', 'attached_to', 'ec2.subnet', '["AvailabilityZones"]', 'SubnetId', 'arn:aws:ec2:{region}:{account_id}:subnet:{SubnetId}', TRUE, NULL, 10, 'ALB/NLB subnets'),
('elbv2.load-balancer', 'attached_to', 'ec2.security-group', '["SecurityGroups"]', NULL, 'arn:aws:ec2:{region}:{account_id}:security-group:{item}', TRUE, 'Type = "application"', 10, 'ALB security groups'),

('elbv2.target-group', 'contained_by', 'ec2.vpc', '["VpcId"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc:{VpcId}', FALSE, NULL, 10, 'Target group in VPC'),
('elbv2.listener', 'serves_traffic_for', 'elbv2.target-group', '["DefaultActions"]', 'TargetGroupArn', '{TargetGroupArn}', TRUE, 'DefaultActions.Type = "forward"', 15, 'Listener forwards to TG'),

-- ============================================================================
-- S3 RELATIONSHIPS
-- ============================================================================

('s3.bucket', 'encrypted_by', 'kms.key', '["ServerSideEncryptionConfiguration", "Rules", "ApplyServerSideEncryptionByDefault", "KMSMasterKeyID"]', NULL, '{KMSMasterKeyID}', FALSE, 'ServerSideEncryptionConfiguration IS NOT NULL', 10, 'S3 bucket encryption'),
('s3.bucket', 'logging_enabled_to', 's3.bucket', '["LoggingConfiguration", "TargetBucket"]', NULL, 'arn:aws:s3:::{TargetBucket}', FALSE, 'LoggingConfiguration IS NOT NULL', 15, 'S3 access logging'),
('s3.bucket', 'replicates_to', 's3.bucket', '["ReplicationConfiguration", "Rules"]', 'Destination.Bucket', '{Bucket}', TRUE, 'ReplicationConfiguration IS NOT NULL', 20, 'S3 replication'),
('s3.bucket', 'triggers', 'lambda.function', '["NotificationConfiguration", "LambdaFunctionConfigurations"]', 'LambdaFunctionArn', '{LambdaFunctionArn}', TRUE, NULL, 15, 'S3 event triggers Lambda'),
('s3.bucket', 'publishes_to', 'sns.topic', '["NotificationConfiguration", "TopicConfigurations"]', 'TopicArn', '{TopicArn}', TRUE, NULL, 15, 'S3 event to SNS'),
('s3.bucket', 'publishes_to', 'sqs.queue', '["NotificationConfiguration", "QueueConfigurations"]', 'QueueArn', '{QueueArn}', TRUE, NULL, 15, 'S3 event to SQS'),

-- ============================================================================
-- IAM RELATIONSHIPS
-- ============================================================================

('iam.role', 'has_policy', 'iam.policy', '["AttachedPolicies"]', 'PolicyArn', '{PolicyArn}', TRUE, NULL, 10, 'Role attached policies'),
('iam.user', 'member_of', 'iam.group', '["Groups"]', 'GroupName', 'arn:aws:iam::{account_id}:group/{GroupName}', TRUE, NULL, 10, 'User group membership'),
('iam.user', 'has_policy', 'iam.policy', '["AttachedPolicies"]', 'PolicyArn', '{PolicyArn}', TRUE, NULL, 10, 'User attached policies'),
('iam.instance-profile', 'uses', 'iam.role', '["Roles"]', 'Arn', '{Arn}', TRUE, NULL, 10, 'Instance profile roles'),

-- ============================================================================
-- SNS/SQS RELATIONSHIPS
-- ============================================================================

('sns.topic', 'triggers', 'lambda.function', '["Subscriptions"]', 'Endpoint', '{Endpoint}', TRUE, 'Protocol = "lambda"', 10, 'SNS triggers Lambda'),
('sns.topic', 'publishes_to', 'sqs.queue', '["Subscriptions"]', 'Endpoint', '{Endpoint}', TRUE, 'Protocol = "sqs"', 10, 'SNS to SQS'),
('sns.topic', 'encrypted_by', 'kms.key', '["KmsMasterKeyId"]', NULL, '{KmsMasterKeyId}', FALSE, 'KmsMasterKeyId IS NOT NULL', 15, 'SNS encryption'),

('sqs.queue', 'encrypted_by', 'kms.key', '["KmsMasterKeyId"]', NULL, '{KmsMasterKeyId}', FALSE, 'KmsMasterKeyId IS NOT NULL', 10, 'SQS encryption'),
('sqs.queue', 'publishes_to', 'sqs.queue', '["RedrivePolicy", "deadLetterTargetArn"]', NULL, '{deadLetterTargetArn}', FALSE, 'RedrivePolicy IS NOT NULL', 15, 'SQS dead letter queue'),

-- ============================================================================
-- CLOUDWATCH & MONITORING
-- ============================================================================

('cloudwatch.alarm', 'publishes_to', 'sns.topic', '["AlarmActions"]', NULL, '{item}', TRUE, NULL, 10, 'CloudWatch alarm actions'),
('logs.group', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, '{KmsKeyId}', FALSE, 'KmsKeyId IS NOT NULL', 15, 'CloudWatch Logs encryption'),

-- ============================================================================
-- CLOUDTRAIL
-- ============================================================================

('cloudtrail.trail', 'logging_enabled_to', 's3.bucket', '["S3BucketName"]', NULL, 'arn:aws:s3:::{S3BucketName}', FALSE, NULL, 10, 'CloudTrail to S3'),
('cloudtrail.trail', 'logging_enabled_to', 'logs.group', '["CloudWatchLogsLogGroupArn"]', NULL, '{CloudWatchLogsLogGroupArn}', FALSE, 'CloudWatchLogsLogGroupArn IS NOT NULL', 15, 'CloudTrail to CloudWatch'),
('cloudtrail.trail', 'uses', 'iam.role', '["CloudWatchLogsRoleArn"]', NULL, '{CloudWatchLogsRoleArn}', FALSE, 'CloudWatchLogsRoleArn IS NOT NULL', 15, 'CloudTrail IAM role'),
('cloudtrail.trail', 'encrypted_by', 'kms.key', '["KmsKeyId"]', NULL, 'arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}', FALSE, 'KmsKeyId IS NOT NULL', 15, 'CloudTrail encryption'),

-- ============================================================================
-- ECS RELATIONSHIPS
-- ============================================================================

('ecs.service', 'contained_by', 'ecs.cluster', '["clusterArn"]', NULL, '{clusterArn}', FALSE, NULL, 10, 'ECS service in cluster'),
('ecs.service', 'uses', 'ecs.task-definition', '["taskDefinition"]', NULL, '{taskDefinition}', FALSE, NULL, 10, 'ECS service task definition'),
('ecs.service', 'attached_to', 'elbv2.target-group', '["loadBalancers"]', 'targetGroupArn', '{targetGroupArn}', TRUE, NULL, 15, 'ECS service to target group'),
('ecs.service', 'attached_to', 'ec2.security-group', '["networkConfiguration", "awsvpcConfiguration", "securityGroups"]', NULL, 'arn:aws:ec2:{region}:{account_id}:security-group:{item}', TRUE, 'launchType = "FARGATE" OR networkConfiguration IS NOT NULL', 20, 'ECS Fargate security groups'),

('ecs.task-definition', 'uses', 'iam.role', '["taskRoleArn"]', NULL, '{taskRoleArn}', FALSE, 'taskRoleArn IS NOT NULL', 10, 'ECS task role'),
('ecs.task-definition', 'uses', 'iam.role', '["executionRoleArn"]', NULL, '{executionRoleArn}', FALSE, NULL, 10, 'ECS execution role'),
('ecs.task-definition', 'logging_enabled_to', 'logs.group', '["containerDefinitions"]', 'logConfiguration.options.awslogs-group', 'arn:aws:logs:{region}:{account_id}:log-group:{awslogs-group}', TRUE, 'logConfiguration.logDriver = "awslogs"', 15, 'ECS container logs'),

-- ============================================================================
-- API GATEWAY
-- ============================================================================

('apigateway.rest-api', 'invokes', 'lambda.function', '["Integration", "Uri"]', NULL, '{FunctionArn}', FALSE, 'Integration.Type = "AWS_PROXY"', 15, 'API Gateway Lambda integration'),
('apigateway.rest-api', 'contained_by', 'ec2.vpc', '["EndpointConfiguration", "VpcEndpointIds"]', NULL, 'arn:aws:ec2:{region}:{account_id}:vpc-endpoint:{item}', TRUE, 'EndpointConfiguration.Types CONTAINS "PRIVATE"', 20, 'Private API Gateway VPC endpoint'),

-- ============================================================================
-- ROUTE53
-- ============================================================================

('route53.record', 'resolves_to', 'elbv2.load-balancer', '["AliasTarget", "DNSName"]', NULL, '{DNSName}', FALSE, 'Type = "A" AND AliasTarget IS NOT NULL', 15, 'Route53 to ALB/NLB'),
('route53.record', 'resolves_to', 'cloudfront.distribution', '["AliasTarget", "DNSName"]', NULL, '{DNSName}', FALSE, 'AliasTarget.HostedZoneId = "Z2FDTNDATAQYW2"', 15, 'Route53 to CloudFront'),

-- ============================================================================
-- KMS
-- ============================================================================

('kms.alias', 'uses', 'kms.key', '["TargetKeyId"]', NULL, 'arn:aws:kms:{region}:{account_id}:key/{TargetKeyId}', FALSE, NULL, 10, 'KMS alias to key')

ON CONFLICT (source_resource_type, relation_type, target_resource_type, source_field) DO NOTHING;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
