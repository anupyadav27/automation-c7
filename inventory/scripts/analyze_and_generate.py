#!/usr/bin/env python3
"""
Comprehensive AWS Relationship Analyzer and Generator
Analyzes current relationships and generates comprehensive coverage
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Set, Any


class RelationshipAnalyzer:
    """Analyze existing relationships and generate comprehensive coverage"""
    
    def __init__(self):
        self.stats = {
            'total_resource_types': 0,
            'resources_with_relationships': 0,
            'resources_without_relationships': 0,
            'total_relationships': 0,
            'relationships_by_type': defaultdict(int),
            'relationships_by_service': defaultdict(int),
            'most_connected_resources': [],
            'services_missing_relationships': set()
        }
        
    def analyze_existing(self, index_data: dict) -> dict:
        """Analyze existing relationships in the index"""
        print("🔍 Analyzing existing relationships...\n")
        
        resource_types = index_data['classifications']['by_resource_type']
        self.stats['total_resource_types'] = len(resource_types)
        
        # Analyze each resource type
        resource_rel_counts = []
        
        for resource_type, data in resource_types.items():
            service = resource_type.split('.')[0]
            relationships = data.get('relationships', [])
            rel_count = len(relationships)
            
            if relationships:
                self.stats['resources_with_relationships'] += 1
                resource_rel_counts.append((resource_type, rel_count))
            else:
                self.stats['resources_without_relationships'] += 1
                self.stats['services_missing_relationships'].add(service)
            
            self.stats['total_relationships'] += rel_count
            self.stats['relationships_by_service'][service] += rel_count
            
            # Count by relationship type
            for rel in relationships:
                rel_type = rel.get('relation_type', 'unknown')
                self.stats['relationships_by_type'][rel_type] += 1
        
        # Get most connected resources
        resource_rel_counts.sort(key=lambda x: x[1], reverse=True)
        self.stats['most_connected_resources'] = resource_rel_counts[:10]
        
        return self.stats
    
    def print_analysis(self):
        """Print analysis results"""
        print("=" * 80)
        print("📊 RELATIONSHIP ANALYSIS REPORT")
        print("=" * 80)
        
        print(f"\n📈 Overall Statistics:")
        print(f"   Total Resource Types:           {self.stats['total_resource_types']}")
        print(f"   Resources WITH relationships:   {self.stats['resources_with_relationships']} ({self.stats['resources_with_relationships']/self.stats['total_resource_types']*100:.1f}%)")
        print(f"   Resources WITHOUT relationships: {self.stats['resources_without_relationships']} ({self.stats['resources_without_relationships']/self.stats['total_resource_types']*100:.1f}%)")
        print(f"   Total Relationships Defined:    {self.stats['total_relationships']}")
        
        if self.stats['total_relationships'] > 0:
            avg = self.stats['total_relationships'] / self.stats['resources_with_relationships']
            print(f"   Avg Relationships per Resource: {avg:.1f}")
        
        print(f"\n🔗 Relationships by Type:")
        for rel_type, count in sorted(self.stats['relationships_by_type'].items(), 
                                      key=lambda x: x[1], reverse=True)[:15]:
            print(f"   {rel_type:30s}: {count:5d}")
        
        print(f"\n🏆 Most Connected Resource Types:")
        for resource_type, count in self.stats['most_connected_resources']:
            print(f"   {resource_type:50s}: {count:3d} relationships")
        
        print(f"\n📦 Top Services by Relationship Count:")
        top_services = sorted(self.stats['relationships_by_service'].items(), 
                            key=lambda x: x[1], reverse=True)[:15]
        for service, count in top_services:
            print(f"   {service:30s}: {count:5d} relationships")
        
        print(f"\n⚠️  Services Missing Relationships: {len(self.stats['services_missing_relationships'])}")
        missing_list = sorted(list(self.stats['services_missing_relationships']))[:20]
        for i in range(0, len(missing_list), 4):
            services = missing_list[i:i+4]
            print(f"   {', '.join(services)}")
        if len(self.stats['services_missing_relationships']) > 20:
            print(f"   ... and {len(self.stats['services_missing_relationships']) - 20} more")


class ComprehensiveRelationshipGenerator:
    """Generate comprehensive relationships for all AWS services"""
    
    def __init__(self):
        # Define ALL possible relationship patterns
        self.patterns = self._define_all_patterns()
        
    def _define_all_patterns(self) -> List[Dict]:
        """Define comprehensive relationship patterns"""
        return [
            # ============= NETWORK RELATIONSHIPS =============
            {
                "name": "VPC Containment",
                "relation_type": "contained_by",
                "target_type": "ec2.vpc",
                "fields": ["VpcId", "vpcId", "Vpc", "VPCId"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}",
                "priority": 10
            },
            {
                "name": "Subnet Attachment",
                "relation_type": "attached_to",
                "target_type": "ec2.subnet",
                "fields": ["SubnetId", "subnetId", "SubnetIds", "subnetIds", "Subnets"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}",
                "is_array": True,
                "priority": 10
            },
            {
                "name": "Security Group",
                "relation_type": "attached_to",
                "target_type": "ec2.security-group",
                "fields": ["SecurityGroups", "SecurityGroupIds", "VpcSecurityGroups", "securityGroupIds"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}",
                "is_array": True,
                "item_field": "GroupId",
                "priority": 10
            },
            {
                "name": "Network ACL",
                "relation_type": "attached_to",
                "target_type": "ec2.network-acl",
                "fields": ["NetworkAclId", "NetworkAclIds"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:network-acl/{NetworkAclId}",
                "priority": 20
            },
            {
                "name": "Route Table",
                "relation_type": "attached_to",
                "target_type": "ec2.route-table",
                "fields": ["RouteTableId", "RouteTableIds"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:route-table/{RouteTableId}",
                "priority": 20
            },
            {
                "name": "Internet Gateway",
                "relation_type": "routes_to",
                "target_type": "ec2.internet-gateway",
                "fields": ["InternetGatewayId", "GatewayId"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:internet-gateway/{InternetGatewayId}",
                "priority": 15
            },
            {
                "name": "NAT Gateway",
                "relation_type": "routes_to",
                "target_type": "ec2.nat-gateway",
                "fields": ["NatGatewayId"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:natgateway/{NatGatewayId}",
                "priority": 15
            },
            {
                "name": "Transit Gateway",
                "relation_type": "connected_to",
                "target_type": "ec2.transit-gateway",
                "fields": ["TransitGatewayId", "TransitGatewayArn"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:transit-gateway/{TransitGatewayId}",
                "priority": 15
            },
            {
                "name": "VPC Endpoint",
                "relation_type": "attached_to",
                "target_type": "ec2.vpc-endpoint",
                "fields": ["VpcEndpointId", "VpcEndpointIds"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:vpc-endpoint/{VpcEndpointId}",
                "priority": 20
            },
            {
                "name": "VPC Peering",
                "relation_type": "connected_to",
                "target_type": "ec2.vpc-peering-connection",
                "fields": ["VpcPeeringConnectionId"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:vpc-peering-connection/{VpcPeeringConnectionId}",
                "priority": 20
            },
            
            # ============= IAM & IDENTITY =============
            {
                "name": "IAM Role",
                "relation_type": "uses",
                "target_type": "iam.role",
                "fields": ["RoleArn", "Role", "ExecutionRoleArn", "TaskRoleArn", "ServiceRoleArn", 
                          "IamRoleArn", "DataAccessRoleArn", "JobRoleArn"],
                "pattern": "{RoleArn}",
                "priority": 5
            },
            {
                "name": "IAM Instance Profile",
                "relation_type": "uses",
                "target_type": "iam.instance-profile",
                "fields": ["IamInstanceProfile", "InstanceProfileArn", "InstanceProfileName"],
                "pattern": "{Arn}",
                "priority": 10
            },
            {
                "name": "IAM Policy",
                "relation_type": "has_policy",
                "target_type": "iam.policy",
                "fields": ["PolicyArn", "ManagedPolicyArns", "AttachedPolicies"],
                "pattern": "{PolicyArn}",
                "is_array": True,
                "priority": 10
            },
            {
                "name": "IAM Group",
                "relation_type": "member_of",
                "target_type": "iam.group",
                "fields": ["GroupId", "GroupArn", "Groups", "GroupName"],
                "pattern": "{GroupArn}",
                "is_array": True,
                "priority": 15
            },
            {
                "name": "IAM User",
                "relation_type": "controlled_by",
                "target_type": "iam.user",
                "fields": ["UserArn", "UserId", "UserName"],
                "pattern": "{UserArn}",
                "priority": 20
            },
            
            # ============= ENCRYPTION & SECURITY =============
            {
                "name": "KMS Encryption",
                "relation_type": "encrypted_by",
                "target_type": "kms.key",
                "fields": ["KmsKeyId", "KMSKeyArn", "KmsMasterKeyId", "MasterKeyId", 
                          "EncryptionKey", "SSEKMSKeyId", "CustomerMasterKeyId"],
                "pattern": "arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}",
                "priority": 5
            },
            {
                "name": "ACM Certificate",
                "relation_type": "uses",
                "target_type": "acm.certificate",
                "fields": ["CertificateArn", "ServerCertificateArn", "CertificateId", "SSLCertificateId"],
                "pattern": "{CertificateArn}",
                "priority": 10
            },
            {
                "name": "Secrets Manager",
                "relation_type": "uses",
                "target_type": "secretsmanager.secret",
                "fields": ["SecretArn", "SecretId", "SecretName"],
                "pattern": "{SecretArn}",
                "priority": 10
            },
            {
                "name": "Parameter Store",
                "relation_type": "uses",
                "target_type": "ssm.parameter",
                "fields": ["ParameterName", "ParameterArn", "ParameterKey"],
                "pattern": "{ParameterArn}",
                "priority": 15
            },
            {
                "name": "WAF WebACL",
                "relation_type": "protected_by",
                "target_type": "wafv2.web-acl",
                "fields": ["WebAclArn", "WebACLArn", "WafAclArn", "WebAclId"],
                "pattern": "{WebAclArn}",
                "priority": 15
            },
            {
                "name": "Shield Protection",
                "relation_type": "protected_by",
                "target_type": "shield.protection",
                "fields": ["ProtectionId", "ProtectionArn"],
                "pattern": "{ProtectionArn}",
                "priority": 20
            },
            
            # ============= STORAGE =============
            {
                "name": "S3 Bucket",
                "relation_type": "uses",
                "target_type": "s3.bucket",
                "fields": ["S3BucketName", "BucketName", "Bucket", "TargetBucket", 
                          "DestinationBucket", "OutputBucket", "LoggingBucket"],
                "pattern": "arn:aws:s3:::{BucketName}",
                "priority": 5
            },
            {
                "name": "S3 Logging",
                "relation_type": "logging_enabled_to",
                "target_type": "s3.bucket",
                "fields": ["LoggingConfiguration.TargetBucket", "AccessLogs.S3Bucket", "S3LoggingBucket"],
                "pattern": "arn:aws:s3:::{TargetBucket}",
                "priority": 10
            },
            {
                "name": "EBS Volume",
                "relation_type": "attached_to",
                "target_type": "ec2.volume",
                "fields": ["VolumeId", "Volumes"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:volume/{VolumeId}",
                "is_array": True,
                "priority": 10
            },
            {
                "name": "EBS Snapshot",
                "relation_type": "backs_up_to",
                "target_type": "ec2.snapshot",
                "fields": ["SnapshotId", "Snapshots"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:snapshot/{SnapshotId}",
                "priority": 15
            },
            {
                "name": "EFS File System",
                "relation_type": "uses",
                "target_type": "efs.file-system",
                "fields": ["FileSystemId", "FileSystemArn"],
                "pattern": "{FileSystemArn}",
                "priority": 15
            },
            
            # ============= LOGGING & MONITORING =============
            {
                "name": "CloudWatch Logs",
                "relation_type": "logging_enabled_to",
                "target_type": "logs.group",
                "fields": ["CloudWatchLogsLogGroupArn", "LogGroupArn", "LogGroupName", 
                          "CloudWatchLogGroup", "LogGroup"],
                "pattern": "arn:aws:logs:{region}:{account_id}:log-group:{LogGroupName}",
                "priority": 5
            },
            {
                "name": "CloudWatch Alarm",
                "relation_type": "monitored_by",
                "target_type": "cloudwatch.alarm",
                "fields": ["AlarmName", "AlarmArn", "AlarmNames"],
                "pattern": "{AlarmArn}",
                "is_array": True,
                "priority": 15
            },
            {
                "name": "CloudTrail",
                "relation_type": "monitored_by",
                "target_type": "cloudtrail.trail",
                "fields": ["TrailArn", "TrailName"],
                "pattern": "{TrailArn}",
                "priority": 20
            },
            {
                "name": "X-Ray",
                "relation_type": "monitored_by",
                "target_type": "xray.group",
                "fields": ["TracingConfig", "XRayConfig"],
                "pattern": "arn:aws:xray:{region}:{account_id}:group/{GroupName}",
                "priority": 20
            },
            
            # ============= MESSAGING & EVENTS =============
            {
                "name": "SNS Topic",
                "relation_type": "publishes_to",
                "target_type": "sns.topic",
                "fields": ["TopicArn", "SnsTopicArn", "NotificationTopicArn", 
                          "AlarmActions", "OKActions", "InsufficientDataActions"],
                "pattern": "{TopicArn}",
                "is_array": True,
                "priority": 5
            },
            {
                "name": "SQS Queue",
                "relation_type": "publishes_to",
                "target_type": "sqs.queue",
                "fields": ["QueueArn", "QueueUrl", "DeadLetterTargetArn", "QueueName"],
                "pattern": "{QueueArn}",
                "priority": 5
            },
            {
                "name": "EventBridge Bus",
                "relation_type": "publishes_to",
                "target_type": "events.event-bus",
                "fields": ["EventBusArn", "EventBusName"],
                "pattern": "{EventBusArn}",
                "priority": 10
            },
            {
                "name": "EventBridge Rule",
                "relation_type": "triggers",
                "target_type": "events.rule",
                "fields": ["RuleArn", "RuleName"],
                "pattern": "{RuleArn}",
                "priority": 15
            },
            {
                "name": "Kinesis Stream",
                "relation_type": "subscribes_to",
                "target_type": "kinesis.stream",
                "fields": ["StreamArn", "KinesisStreamArn", "DeliveryStreamArn", "StreamName"],
                "pattern": "{StreamArn}",
                "priority": 10
            },
            {
                "name": "Kinesis Firehose",
                "relation_type": "subscribes_to",
                "target_type": "firehose.delivery-stream",
                "fields": ["DeliveryStreamArn", "DeliveryStreamName"],
                "pattern": "{DeliveryStreamArn}",
                "priority": 15
            },
            
            # ============= COMPUTE =============
            {
                "name": "Lambda Function",
                "relation_type": "triggers",
                "target_type": "lambda.function",
                "fields": ["FunctionArn", "LambdaFunctionArn", "TargetArn", "FunctionName"],
                "pattern": "{FunctionArn}",
                "priority": 5
            },
            {
                "name": "Lambda Layer",
                "relation_type": "uses",
                "target_type": "lambda.layer",
                "fields": ["LayerArn", "LayerVersionArn", "Layers"],
                "pattern": "{LayerArn}",
                "is_array": True,
                "priority": 15
            },
            {
                "name": "ECS Cluster",
                "relation_type": "contained_by",
                "target_type": "ecs.cluster",
                "fields": ["ClusterArn", "clusterArn", "Cluster"],
                "pattern": "{ClusterArn}",
                "priority": 10
            },
            {
                "name": "ECS Task Definition",
                "relation_type": "uses",
                "target_type": "ecs.task-definition",
                "fields": ["TaskDefinition", "TaskDefinitionArn", "taskDefinition"],
                "pattern": "{TaskDefinitionArn}",
                "priority": 10
            },
            {
                "name": "ECS Service",
                "relation_type": "runs_on",
                "target_type": "ecs.service",
                "fields": ["ServiceArn", "ServiceName"],
                "pattern": "{ServiceArn}",
                "priority": 15
            },
            {
                "name": "ECR Repository",
                "relation_type": "uses",
                "target_type": "ecr.repository",
                "fields": ["RepositoryArn", "ImageUri", "RepositoryName"],
                "pattern": "{RepositoryArn}",
                "priority": 10
            },
            {
                "name": "EKS Cluster",
                "relation_type": "runs_on",
                "target_type": "eks.cluster",
                "fields": ["ClusterArn", "ClusterName"],
                "pattern": "{ClusterArn}",
                "priority": 10
            },
            {
                "name": "Auto Scaling Group",
                "relation_type": "scales_with",
                "target_type": "autoscaling.group",
                "fields": ["AutoScalingGroupArn", "AutoScalingGroupName"],
                "pattern": "{AutoScalingGroupArn}",
                "priority": 15
            },
            {
                "name": "Launch Template",
                "relation_type": "uses",
                "target_type": "ec2.launch-template",
                "fields": ["LaunchTemplateId", "LaunchTemplateName"],
                "pattern": "arn:aws:ec2:{region}:{account_id}:launch-template/{LaunchTemplateId}",
                "priority": 15
            },
            
            # ============= LOAD BALANCING =============
            {
                "name": "Load Balancer",
                "relation_type": "exposed_through",
                "target_type": "elbv2.load-balancer",
                "fields": ["LoadBalancerArn", "LoadBalancerName", "LoadBalancers"],
                "pattern": "{LoadBalancerArn}",
                "is_array": True,
                "priority": 5
            },
            {
                "name": "Target Group",
                "relation_type": "serves_traffic_for",
                "target_type": "elbv2.target-group",
                "fields": ["TargetGroupArn", "TargetGroups", "TargetGroupName"],
                "pattern": "{TargetGroupArn}",
                "is_array": True,
                "priority": 10
            },
            {
                "name": "Classic Load Balancer",
                "relation_type": "exposed_through",
                "target_type": "elb.load-balancer",
                "fields": ["LoadBalancerName", "DNSName"],
                "pattern": "arn:aws:elasticloadbalancing:{region}:{account_id}:loadbalancer/{LoadBalancerName}",
                "priority": 15
            },
            
            # ============= DATABASES =============
            {
                "name": "RDS Instance",
                "relation_type": "member_of",
                "target_type": "rds.instance",
                "fields": ["DBInstanceIdentifier", "DBInstanceArn"],
                "pattern": "{DBInstanceArn}",
                "priority": 10
            },
            {
                "name": "RDS Cluster",
                "relation_type": "member_of",
                "target_type": "rds.cluster",
                "fields": ["DBClusterIdentifier", "DBClusterArn"],
                "pattern": "{DBClusterArn}",
                "priority": 10
            },
            {
                "name": "DynamoDB Table",
                "relation_type": "uses",
                "target_type": "dynamodb.table",
                "fields": ["TableName", "TableArn"],
                "pattern": "{TableArn}",
                "priority": 10
            },
            {
                "name": "DynamoDB Stream",
                "relation_type": "subscribes_to",
                "target_type": "dynamodb.stream",
                "fields": ["StreamArn", "TableStreamArn", "LatestStreamArn"],
                "pattern": "{StreamArn}",
                "priority": 10
            },
            {
                "name": "ElastiCache Cluster",
                "relation_type": "uses",
                "target_type": "elasticache.cluster",
                "fields": ["CacheClusterId", "ReplicationGroupId"],
                "pattern": "arn:aws:elasticache:{region}:{account_id}:cluster:{CacheClusterId}",
                "priority": 15
            },
            {
                "name": "Redshift Cluster",
                "relation_type": "uses",
                "target_type": "redshift.cluster",
                "fields": ["ClusterIdentifier", "ClusterArn"],
                "pattern": "{ClusterArn}",
                "priority": 15
            },
            
            # ============= API & INTEGRATION =============
            {
                "name": "API Gateway",
                "relation_type": "exposed_through",
                "target_type": "apigateway.rest-api",
                "fields": ["RestApiId", "ApiId", "ApiArn"],
                "pattern": "arn:aws:apigateway:{region}::/restapis/{RestApiId}",
                "priority": 10
            },
            {
                "name": "AppSync API",
                "relation_type": "exposed_through",
                "target_type": "appsync.graphqlapi",
                "fields": ["ApiId", "GraphQLApiId", "ApiArn"],
                "pattern": "{ApiArn}",
                "priority": 15
            },
            {
                "name": "Step Functions",
                "relation_type": "invokes",
                "target_type": "states.state-machine",
                "fields": ["StateMachineArn", "StateMachineName"],
                "pattern": "{StateMachineArn}",
                "priority": 15
            },
            
            # ============= CDN & DNS =============
            {
                "name": "CloudFront Distribution",
                "relation_type": "exposed_through",
                "target_type": "cloudfront.distribution",
                "fields": ["DistributionId", "DistributionArn", "CloudFrontDistribution"],
                "pattern": "arn:aws:cloudfront::{account_id}:distribution/{DistributionId}",
                "priority": 10
            },
            {
                "name": "Route53 Hosted Zone",
                "relation_type": "resolves_to",
                "target_type": "route53.hosted-zone",
                "fields": ["HostedZoneId", "ZoneId"],
                "pattern": "arn:aws:route53:::hostedzone/{HostedZoneId}",
                "priority": 10
            },
            
            # ============= ANALYTICS & ML =============
            {
                "name": "Glue Database",
                "relation_type": "uses",
                "target_type": "glue.database",
                "fields": ["DatabaseName", "DatabaseArn"],
                "pattern": "{DatabaseArn}",
                "priority": 15
            },
            {
                "name": "Glue Crawler",
                "relation_type": "uses",
                "target_type": "glue.crawler",
                "fields": ["CrawlerName", "CrawlerArn"],
                "pattern": "{CrawlerArn}",
                "priority": 20
            },
            {
                "name": "SageMaker Endpoint",
                "relation_type": "uses",
                "target_type": "sagemaker.endpoint",
                "fields": ["EndpointName", "EndpointArn"],
                "pattern": "{EndpointArn}",
                "priority": 15
            },
            {
                "name": "SageMaker Model",
                "relation_type": "uses",
                "target_type": "sagemaker.model",
                "fields": ["ModelName", "ModelArn"],
                "pattern": "{ModelArn}",
                "priority": 15
            },
            
            # ============= BACKUP & DR =============
            {
                "name": "Backup Vault",
                "relation_type": "backs_up_to",
                "target_type": "backup.vault",
                "fields": ["BackupVaultArn", "BackupVaultName", "RecoveryPointArn"],
                "pattern": "{BackupVaultArn}",
                "priority": 15
            },
            {
                "name": "Backup Plan",
                "relation_type": "backs_up_to",
                "target_type": "backup.plan",
                "fields": ["BackupPlanArn", "BackupPlanId"],
                "pattern": "{BackupPlanArn}",
                "priority": 20
            },
            
            # ============= COGNITO =============
            {
                "name": "Cognito User Pool",
                "relation_type": "uses",
                "target_type": "cognito-idp.user-pool",
                "fields": ["UserPoolId", "UserPoolArn"],
                "pattern": "{UserPoolArn}",
                "priority": 10
            },
            {
                "name": "Cognito Identity Pool",
                "relation_type": "uses",
                "target_type": "cognito-identity.identity-pool",
                "fields": ["IdentityPoolId", "IdentityPoolArn"],
                "pattern": "{IdentityPoolArn}",
                "priority": 15
            }
        ]
    
    def generate_relationships(self, resource_type: str) -> List[Dict]:
        """Generate relationships for a resource type"""
        relationships = []
        service = resource_type.split('.')[0]
        resource_name = resource_type.split('.', 1)[1] if '.' in resource_type else resource_type
        
        for pattern in self.patterns:
            for field in pattern['fields']:
                rel = {
                    "relation_type": pattern['relation_type'],
                    "target_type": pattern['target_type'],
                    "source_field": field,
                    "target_uid_pattern": pattern['pattern']
                }
                
                if pattern.get('is_array'):
                    rel['is_array'] = True
                    if pattern.get('item_field'):
                        rel['source_field_item'] = pattern['item_field']
                
                relationships.append(rel)
        
        return relationships
    
    def generate_for_all(self, index_data: dict) -> dict:
        """Generate relationships for all resource types"""
        print("\n🚀 Generating comprehensive relationships...\n")
        
        resource_types = index_data['classifications']['by_resource_type']
        total = len(resource_types)
        updated_count = 0
        added_rel_count =