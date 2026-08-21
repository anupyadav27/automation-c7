"""
AWS Relationship Generator
Automatically generates relationships for ALL 1688 AWS resource types
Run this to populate relationships for all services
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class ComprehensiveRelationshipGenerator:
    """
    Generates relationships for all AWS services using pattern matching
    """
    
    def __init__(self):
        # Universal relationship patterns that apply to many services
        self.universal_patterns = [
            # Network & Infrastructure
            {
                "name": "VPC Containment",
                "relation_type": "contained_by",
                "target_type": "ec2.vpc",
                "field_patterns": ["VpcId", "vpcId", "Vpc.Id"],
                "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}",
                "applies_to_services": "*"  # All services
            },
            {
                "name": "Subnet Attachment",
                "relation_type": "attached_to",
                "target_type": "ec2.subnet",
                "field_patterns": ["SubnetId", "subnetId", "SubnetIds", "subnetIds", "Subnets"],
                "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}",
                "is_array_field": ["SubnetIds", "subnetIds", "Subnets"],
                "applies_to_services": "*"
            },
            {
                "name": "Security Group Attachment",
                "relation_type": "attached_to",
                "target_type": "ec2.security-group",
                "field_patterns": [
                    "SecurityGroups", "securityGroups", "SecurityGroupIds", 
                    "securityGroupIds", "VpcSecurityGroups", "SecurityGroupIdList"
                ],
                "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}",
                "is_array": True,
                "item_fields": ["GroupId", "VpcSecurityGroupId", "SecurityGroupId"],
                "applies_to_services": "*"
            },
            
            # Identity & Access
            {
                "name": "IAM Role Usage",
                "relation_type": "uses",
                "target_type": "iam.role",
                "field_patterns": [
                    "RoleArn", "roleArn", "Role", "ExecutionRoleArn", 
                    "TaskRoleArn", "ServiceRoleArn", "IamRoleArn",
                    "DataAccessRoleArn", "PassRoleArn"
                ],
                "target_uid_pattern": "{RoleArn}",
                "applies_to_services": "*"
            },
            {
                "name": "IAM Instance Profile",
                "relation_type": "uses",
                "target_type": "iam.instance-profile",
                "field_patterns": ["IamInstanceProfile", "InstanceProfileArn"],
                "target_uid_pattern": "{Arn}",
                "applies_to_services": ["ec2", "autoscaling"]
            },
            
            # Encryption & Security
            {
                "name": "KMS Encryption",
                "relation_type": "encrypted_by",
                "target_type": "kms.key",
                "field_patterns": [
                    "KmsKeyId", "kmsKeyId", "KMSKeyArn", "KmsMasterKeyId",
                    "MasterKeyId", "EncryptionKey", "SSEKMSKeyId"
                ],
                "target_uid_pattern": "arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}",
                "applies_to_services": "*"
            },
            {
                "name": "ACM Certificate",
                "relation_type": "uses",
                "target_type": "acm.certificate",
                "field_patterns": [
                    "CertificateArn", "ServerCertificateArn", "CertificateId"
                ],
                "target_uid_pattern": "{CertificateArn}",
                "applies_to_services": "*"
            },
            
            # Storage
            {
                "name": "S3 Bucket Usage",
                "relation_type": "uses",
                "target_type": "s3.bucket",
                "field_patterns": [
                    "S3BucketName", "BucketName", "Bucket", "TargetBucket",
                    "LoggingBucket", "DestinationBucket", "OutputBucket"
                ],
                "target_uid_pattern": "arn:aws:s3:::{BucketName}",
                "applies_to_services": "*"
            },
            {
                "name": "S3 Logging",
                "relation_type": "logging_enabled_to",
                "target_type": "s3.bucket",
                "field_patterns": [
                    "LoggingConfiguration.TargetBucket", "AccessLogs.S3Bucket"
                ],
                "target_uid_pattern": "arn:aws:s3:::{TargetBucket}",
                "applies_to_services": "*"
            },
            
            # Logging & Monitoring
            {
                "name": "CloudWatch Logs",
                "relation_type": "logging_enabled_to",
                "target_type": "logs.group",
                "field_patterns": [
                    "CloudWatchLogsLogGroupArn", "LogGroupArn", "LogGroupName",
                    "CloudWatchLogGroup", "LogConfiguration.LogGroupName"
                ],
                "target_uid_pattern": "arn:aws:logs:{region}:{account_id}:log-group:{LogGroupName}",
                "applies_to_services": "*"
            },
            {
                "name": "CloudWatch Alarms",
                "relation_type": "monitored_by",
                "target_type": "cloudwatch.alarm",
                "field_patterns": ["AlarmName", "AlarmArn"],
                "target_uid_pattern": "{AlarmArn}",
                "applies_to_services": "*"
            },
            
            # Messaging & Events
            {
                "name": "SNS Topic Notification",
                "relation_type": "publishes_to",
                "target_type": "sns.topic",
                "field_patterns": [
                    "TopicArn", "SnsTopicArn", "NotificationTopicArn",
                    "AlarmActions", "InsufficientDataActions", "OKActions"
                ],
                "target_uid_pattern": "{TopicArn}",
                "is_array_field": ["AlarmActions", "InsufficientDataActions", "OKActions"],
                "applies_to_services": "*"
            },
            {
                "name": "SQS Queue Messaging",
                "relation_type": "publishes_to",
                "target_type": "sqs.queue",
                "field_patterns": [
                    "QueueArn", "QueueUrl", "DeadLetterTargetArn", "QueueName"
                ],
                "target_uid_pattern": "{QueueArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Lambda Function Trigger",
                "relation_type": "triggers",
                "target_type": "lambda.function",
                "field_patterns": [
                    "FunctionArn", "LambdaFunctionArn", "TargetArn",
                    "Handler", "FunctionName"
                ],
                "target_uid_pattern": "{FunctionArn}",
                "applies_to_services": "*"
            },
            {
                "name": "EventBridge Bus",
                "relation_type": "publishes_to",
                "target_type": "events.event-bus",
                "field_patterns": ["EventBusArn", "EventBusName"],
                "target_uid_pattern": "{EventBusArn}",
                "applies_to_services": "*"
            },
            
            # Compute
            {
                "name": "ECS Cluster",
                "relation_type": "contained_by",
                "target_type": "ecs.cluster",
                "field_patterns": ["ClusterArn", "clusterArn", "Cluster"],
                "target_uid_pattern": "{ClusterArn}",
                "applies_to_services": ["ecs", "fargate", "batch"]
            },
            {
                "name": "ECS Task Definition",
                "relation_type": "uses",
                "target_type": "ecs.task-definition",
                "field_patterns": ["TaskDefinition", "TaskDefinitionArn", "taskDefinition"],
                "target_uid_pattern": "{TaskDefinitionArn}",
                "applies_to_services": ["ecs", "fargate"]
            },
            {
                "name": "ECR Repository",
                "relation_type": "uses",
                "target_type": "ecr.repository",
                "field_patterns": ["RepositoryArn", "ImageUri", "Image"],
                "target_uid_pattern": "{RepositoryArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Load Balancer",
                "relation_type": "exposed_through",
                "target_type": "elbv2.load-balancer",
                "field_patterns": [
                    "LoadBalancerArn", "LoadBalancerName", "LoadBalancers"
                ],
                "target_uid_pattern": "{LoadBalancerArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Target Group",
                "relation_type": "serves_traffic_for",
                "target_type": "elbv2.target-group",
                "field_patterns": ["TargetGroupArn", "TargetGroups"],
                "target_uid_pattern": "{TargetGroupArn}",
                "is_array_field": ["TargetGroups"],
                "applies_to_services": "*"
            },
            
            # Databases & Streams
            {
                "name": "DynamoDB Stream",
                "relation_type": "subscribes_to",
                "target_type": "dynamodb.stream",
                "field_patterns": ["StreamArn", "TableStreamArn", "LatestStreamArn"],
                "target_uid_pattern": "{StreamArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Kinesis Stream",
                "relation_type": "subscribes_to",
                "target_type": "kinesis.stream",
                "field_patterns": [
                    "StreamArn", "KinesisStreamArn", "DeliveryStreamArn",
                    "StreamName"
                ],
                "target_uid_pattern": "{StreamArn}",
                "applies_to_services": "*"
            },
            {
                "name": "RDS Cluster Membership",
                "relation_type": "member_of",
                "target_type": "rds.cluster",
                "field_patterns": ["DBClusterIdentifier"],
                "target_uid_pattern": "arn:aws:rds:{region}:{account_id}:cluster:{DBClusterIdentifier}",
                "applies_to_services": ["rds", "aurora"]
            },
            
            # Secrets & Configuration
            {
                "name": "Secrets Manager",
                "relation_type": "uses",
                "target_type": "secretsmanager.secret",
                "field_patterns": ["SecretArn", "SecretId", "SecretString"],
                "target_uid_pattern": "{SecretArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Parameter Store",
                "relation_type": "uses",
                "target_type": "ssm.parameter",
                "field_patterns": ["ParameterName", "ParameterArn"],
                "target_uid_pattern": "{ParameterArn}",
                "applies_to_services": "*"
            },
            
            # DNS & CDN
            {
                "name": "Route53 Hosted Zone",
                "relation_type": "resolves_to",
                "target_type": "route53.hosted-zone",
                "field_patterns": ["HostedZoneId", "ZoneId"],
                "target_uid_pattern": "arn:aws:route53:::hostedzone/{HostedZoneId}",
                "applies_to_services": "*"
            },
            {
                "name": "CloudFront Distribution",
                "relation_type": "exposed_through",
                "target_type": "cloudfront.distribution",
                "field_patterns": ["DistributionId", "CloudFrontDistribution"],
                "target_uid_pattern": "arn:aws:cloudfront::{account_id}:distribution/{DistributionId}",
                "applies_to_services": "*"
            },
            
            # Security Services
            {
                "name": "WAF WebACL",
                "relation_type": "protected_by",
                "target_type": "wafv2.web-acl",
                "field_patterns": ["WebAclArn", "WebACLArn", "WafAclArn"],
                "target_uid_pattern": "{WebAclArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Shield Protection",
                "relation_type": "protected_by",
                "target_type": "shield.protection",
                "field_patterns": ["ProtectionId", "ProtectionArn"],
                "target_uid_pattern": "{ProtectionArn}",
                "applies_to_services": "*"
            },
            
            # Backup & Disaster Recovery
            {
                "name": "Backup Vault",
                "relation_type": "backs_up_to",
                "target_type": "backup.vault",
                "field_patterns": [
                    "BackupVaultArn", "BackupVaultName", "RecoveryPointArn"
                ],
                "target_uid_pattern": "{BackupVaultArn}",
                "applies_to_services": "*"
            },
            {
                "name": "Snapshot Backup",
                "relation_type": "backs_up_to",
                "target_type": "ec2.snapshot",
                "field_patterns": ["SnapshotId", "SnapshotArn"],
                "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:snapshot/{SnapshotId}",
                "applies_to_services": ["ec2", "ebs"]
            }
        ]
    
    def generate_for_all_resources(self, index_file_path: str) -> dict:
        """
        Generate relationships for all resources in the index file
        """
        print("🚀 Starting comprehensive relationship generation...")
        
        # Load index
        with open(index_file_path, 'r') as f:
            index_data = json.load(f)
        
        resource_types = index_data['classifications']['by_resource_type']
        total = len(resource_types)
        processed = 0
        updated = 0
        
        print(f"📊 Found {total} resource types to process\n")
        
        for resource_type, resource_data in resource_types.items():
            processed += 1
            service = resource_type.split('.')[0]
            
            # Get existing relationships
            existing_rels = resource_data.get('relationships', [])
            existing_count = len(existing_rels)
            
            # Generate new relationships
            new_rels = self._generate_relationships(resource_type, service)
            
            # Merge (avoid duplicates)
            if new_rels:
                existing_keys = {
                    (r.get('relation_type'), r.get('target_type'), r.get('source_field'))
                    for r in existing_rels
                }
                
                for rel in new_rels:
                    key = (rel['relation_type'], rel['target_type'], rel.get('source_field'))
                    if key not in existing_keys:
                        existing_rels.append(rel)
                        existing_keys.add(key)
                
                resource_data['relationships'] = existing_rels
                
                if len(existing_rels) > existing_count:
                    updated += 1
            
            # Progress indicator
            if processed % 100 == 0:
                print(f"  Progress: {processed}/{total} ({(processed/total*100):.1f}%)")
        
        # Update metadata
        total_rels = sum(
            len(rt['relationships'])
            for rt in resource_types.values()
        )
        types_with_rels = sum(
            1 for rt in resource_types.values()
            if rt['relationships']
        )
        
        index_data['metadata'].update({
            'resource_types_with_relations': types_with_rels,
            'total_relationship_definitions': total_rels,
            'auto_generated': True,
            'generation_date': datetime.now(timezone.utc).isoformat() + 'Z',
            'generator_version': '2.0'
        })
        
        print(f"\n✅ Generation Complete!")
        print(f"   Resource types updated: {updated}/{total}")
        print(f"   Types with relationships: {types_with_rels}/{total} ({types_with_rels/total*100:.1f}%)")
        print(f"   Total relationships: {total_rels}")
        
        return index_data
    
    def _generate_relationships(self, resource_type: str, service: str) -> list:
        """Generate relationships for a specific resource type"""
        relationships = []
        
        for pattern in self.universal_patterns:
            # Check if pattern applies to this service
            if pattern['applies_to_services'] != '*':
                if service not in pattern['applies_to_services']:
                    continue
            
            # Generate relationships from this pattern
            for field_pattern in pattern['field_patterns']:
                rel = {
                    "relation_type": pattern['relation_type'],
                    "target_type": pattern['target_type'],
                    "source_field": field_pattern,
                    "target_uid_pattern": pattern['target_uid_pattern']
                }
                
                # Handle array fields
                if field_pattern in pattern.get('is_array_field', []):
                    rel['is_array'] = True
                    if pattern.get('item_fields'):
                        rel['source_field_item'] = pattern['item_fields'][0]
                elif pattern.get('is_array'):
                    rel['is_array'] = True
                    if pattern.get('item_fields'):
                        rel['source_field_item'] = pattern['item_fields'][0]
                
                relationships.append(rel)
        
        return relationships


def main():
    """Main execution function"""
    # Get paths
    script_dir = Path(__file__).parent
    config_dir = script_dir.parent / 'config'
    
    input_file = config_dir / 'aws_relationship_index_20260123T065606Z.json'
    output_file = config_dir / 'aws_relationship_index_COMPLETE.json'
    
    if not input_file.exists():
        print(f"❌ Error: Input file not found: {input_file}")
        return 1
    
    # Generate relationships
    generator = ComprehensiveRelationshipGenerator()
    updated_index = generator.generate_for_all_resources(str(input_file))
    
    # Save output
    with open(output_file, 'w') as f:
        json.dump(updated_index, f, indent=2)
    
    print(f"\n💾 Saved complete relationship index to:")
    print(f"   {output_file}")
    
    # Print summary statistics
    print(f"\n📈 Relationship Summary by Type:")
    rel_counts = {}
    for rt in updated_index['classifications']['by_resource_type'].values():
        for rel in rt.get('relationships', []):
            rel_type = rel['relation_type']
            rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1
    
    for rel_type, count in sorted(rel_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        print(f"   {rel_type:25s}: {count:5d}")
    
    print(f"\n🎉 All done! You now have comprehensive relationships for all AWS services!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
