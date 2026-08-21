"""
Relationship Builder - Generate Comprehensive AWS Relationship Definitions
Analyzes existing relationships and generates complete predefined relationship database
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any


class RelationshipBuilder:
    """Builds comprehensive relationship definitions for all AWS services"""

    def __init__(self, existing_index_path: str):
        """Load existing relationship index"""
        with open(existing_index_path) as f:
            self.existing_data = json.load(f)
        
        self.service_coverage = defaultdict(lambda: {'defined': 0, 'missing': 0})
        self.relation_patterns = self._analyze_patterns()
    
    def _analyze_patterns(self) -> Dict[str, List[Dict]]:
        """Analyze existing patterns to replicate across services"""
        patterns = {
            'vpc_containment': [],
            'security_group_attachment': [],
            'kms_encryption': [],
            'iam_role_usage': [],
            'logging_to_s3': [],
            'logging_to_cloudwatch': [],
            'subnet_attachment': []
        }
        
        # Extract patterns from existing relationships
        for resource_type, data in self.existing_data['classifications']['by_resource_type'].items():
            for rel in data.get('relationships', []):
                # VPC containment pattern
                if rel.get('target_type') == 'ec2.vpc' and rel.get('relation_type') == 'contained_by':
                    patterns['vpc_containment'].append({
                        'source': resource_type,
                        'field': rel['source_field'],
                        'pattern': rel['target_uid_pattern']
                    })
                
                # Security group pattern
                if 'security-group' in rel.get('target_type', ''):
                    patterns['security_group_attachment'].append({
                        'source': resource_type,
                        'field': rel['source_field'],
                        'pattern': rel['target_uid_pattern']
                    })
                
                # KMS encryption pattern
                if rel.get('target_type') == 'kms.key':
                    patterns['kms_encryption'].append({
                        'source': resource_type,
                        'field': rel['source_field'],
                        'pattern': rel['target_uid_pattern']
                    })
        
        return patterns
    
    def generate_complete_relationships(self) -> Dict[str, Any]:
        """Generate complete relationship definitions for all services"""
        
        complete_relationships = {
            "version": "2.0",
            "generated_at": "2026-01-23T12:00:00Z",
            "description": "Comprehensive AWS relationship definitions for ALL services",
            "metadata": {
                "total_services": 0,
                "total_resource_types": 0,
                "total_relationships": 0
            },
            "relationships": {}
        }
        
        # Core compute services - HIGHEST PRIORITY
        complete_relationships["relationships"].update(self._generate_ec2_relationships())
        complete_relationships["relationships"].update(self._generate_lambda_relationships())
        complete_relationships["relationships"].update(self._generate_ecs_relationships())
        complete_relationships["relationships"].update(self._generate_eks_relationships())
        
        # Storage services
        complete_relationships["relationships"].update(self._generate_s3_relationships())
        complete_relationships["relationships"].update(self._generate_ebs_relationships())
        complete_relationships["relationships"].update(self._generate_efs_relationships())
        
        # Database services
        complete_relationships["relationships"].update(self._generate_rds_relationships())
        complete_relationships["relationships"].update(self._generate_dynamodb_relationships())
        complete_relationships["relationships"].update(self._generate_elasticache_relationships())
        complete_relationships["relationships"].update(self._generate_redshift_relationships())
        
        # Networking services
        complete_relationships["relationships"].update(self._generate_vpc_relationships())
        complete_relationships["relationships"].update(self._generate_elb_relationships())
        complete_relationships["relationships"].update(self._generate_cloudfront_relationships())
        complete_relationships["relationships"].update(self._generate_route53_relationships())
        complete_relationships["relationships"].update(self._generate_apigateway_relationships())
        
        # Security & Identity
        complete_relationships["relationships"].update(self._generate_iam_relationships())
        complete_relationships["relationships"].update(self._generate_kms_relationships())
        complete_relationships["relationships"].update(self._generate_secrets_manager_relationships())
        complete_relationships["relationships"].update(self._generate_acm_relationships())
        
        # Monitoring & Logging
        complete_relationships["relationships"].update(self._generate_cloudwatch_relationships())
        complete_relationships["relationships"].update(self._generate_cloudtrail_relationships())
        
        # Messaging & Events
        complete_relationships["relationships"].update(self._generate_sns_relationships())
        complete_relationships["relationships"].update(self._generate_sqs_relationships())
        complete_relationships["relationships"].update(self._generate_eventbridge_relationships())
        complete_relationships["relationships"].update(self._generate_kinesis_relationships())
        
        # Container & Orchestration
        complete_relationships["relationships"].update(self._generate_ecr_relationships())
        
        # Application Integration
        complete_relationships["relationships"].update(self._generate_step_functions_relationships())
        complete_relationships["relationships"].update(self._generate_appconfig_relationships())
        
        # Analytics
        complete_relationships["relationships"].update(self._generate_athena_relationships())
        complete_relationships["relationships"].update(self._generate_glue_relationships())
        
        # ML & AI
        complete_relationships["relationships"].update(self._generate_sagemaker_relationships())
        complete_relationships["relationships"].update(self._generate_bedrock_relationships())
        
        # Developer Tools
        complete_relationships["relationships"].update(self._generate_codepipeline_relationships())
        complete_relationships["relationships"].update(self._generate_codebuild_relationships())
        
        # Management & Governance
        complete_relationships["relationships"].update(self._generate_config_relationships())
        complete_relationships["relationships"].update(self._generate_ssm_relationships())
        complete_relationships["relationships"].update(self._generate_backup_relationships())
        
        # Update metadata
        total_rels = sum(len(rels) for rels in complete_relationships["relationships"].values())
        complete_relationships["metadata"]["total_resource_types"] = len(complete_relationships["relationships"])
        complete_relationships["metadata"]["total_relationships"] = total_rels
        
        return complete_relationships
    
    # ========================================================================
    # EC2 & COMPUTE RELATIONSHIPS
    # ========================================================================
    
    def _generate_ec2_relationships(self) -> Dict[str, List[Dict]]:
        """Generate all EC2-related relationships"""
        return {
            "ec2.instance": [
                {"relation_type": "contained_by", "target_type": "ec2.subnet", "source_field": "SubnetId", 
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}"},
                {"relation_type": "attached_to", "target_type": "ec2.security-group", "source_field": "SecurityGroups", 
                 "source_field_item": "GroupId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}", "is_array": True},
                {"relation_type": "uses", "target_type": "iam.instance-profile", "source_field": "IamInstanceProfile.Arn",
                 "target_uid_pattern": "{Arn}"},
                {"relation_type": "attached_to", "target_type": "ec2.volume", "source_field": "BlockDeviceMappings",
                 "source_field_item": "Ebs.VolumeId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:volume/{VolumeId}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "ec2.network-interface", "source_field": "NetworkInterfaces",
                 "source_field_item": "NetworkInterfaceId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:network-interface/{NetworkInterfaceId}", "is_array": True},
                {"relation_type": "uses", "target_type": "ec2.key-pair", "source_field": "KeyName",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:key-pair/{KeyName}"},
                {"relation_type": "attached_to", "target_type": "ec2.placement-group", "source_field": "Placement.GroupName",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:placement-group/{GroupName}", "conditional": "Placement.GroupName IS NOT NULL"},
                {"relation_type": "runs_on", "target_type": "ec2.dedicated-host", "source_field": "Placement.HostId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:dedicated-host/{HostId}", "conditional": "Placement.Tenancy = 'host'"},
                {"relation_type": "monitored_by", "target_type": "cloudwatch.alarm", "source_field": "InstanceId",
                 "target_uid_pattern": "arn:aws:cloudwatch:{region}:{account_id}:alarm:*{InstanceId}*", "note": "Implicit monitoring"},
                {"relation_type": "internet_accessible", "target_type": "internet", "source_field": "PublicIpAddress",
                 "target_uid_pattern": "internet", "conditional": "PublicIpAddress IS NOT NULL"}
            ],
            
            "ec2.subnet": [
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "attached_to", "target_type": "ec2.route-table", "source_field": "RouteTableId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:route-table/{RouteTableId}"},
                {"relation_type": "attached_to", "target_type": "ec2.network-acl", "source_field": "NetworkAclId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:network-acl/{NetworkAclId}"},
                {"relation_type": "contained_by", "target_type": "ec2.availability-zone", "source_field": "AvailabilityZone",
                 "target_uid_pattern": "{region}:{AvailabilityZone}"}
            ],
            
            "ec2.security-group": [
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "allows_traffic_from", "target_type": "ec2.security-group", "source_field": "IpPermissions",
                 "source_field_item": "UserIdGroupPairs.GroupId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}", "is_array": True},
                {"relation_type": "allows_traffic_from", "target_type": "ec2.prefix-list", "source_field": "IpPermissions",
                 "source_field_item": "PrefixListIds.PrefixListId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:prefix-list/{PrefixListId}", "is_array": True}
            ],
            
            "ec2.vpc": [
                {"relation_type": "uses", "target_type": "ec2.dhcp-options", "source_field": "DhcpOptionsId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:dhcp-options/{DhcpOptionsId}"},
                {"relation_type": "logging_enabled_to", "target_type": "s3.bucket", "source_field": "FlowLogsConfiguration.S3.BucketArn",
                 "target_uid_pattern": "{BucketArn}", "conditional": "FlowLogsConfiguration IS NOT NULL"},
                {"relation_type": "logging_enabled_to", "target_type": "logs.log-group", "source_field": "FlowLogsConfiguration.CloudWatchLogs.LogGroupName",
                 "target_uid_pattern": "arn:aws:logs:{region}:{account_id}:log-group:{LogGroupName}", "conditional": "FlowLogsConfiguration IS NOT NULL"}
            ],
            
            "ec2.route-table": [
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "routes_to", "target_type": "ec2.internet-gateway", "source_field": "Routes",
                 "source_field_item": "GatewayId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:internet-gateway/{GatewayId}", 
                 "is_array": True, "conditional": "GatewayId LIKE 'igw-%'"},
                {"relation_type": "routes_to", "target_type": "ec2.nat-gateway", "source_field": "Routes",
                 "source_field_item": "NatGatewayId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:natgateway/{NatGatewayId}",
                 "is_array": True, "conditional": "NatGatewayId IS NOT NULL"},
                {"relation_type": "routes_to", "target_type": "ec2.transit-gateway", "source_field": "Routes",
                 "source_field_item": "TransitGatewayId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:transit-gateway/{TransitGatewayId}",
                 "is_array": True, "conditional": "TransitGatewayId IS NOT NULL"},
                {"relation_type": "routes_to", "target_type": "ec2.vpc-peering-connection", "source_field": "Routes",
                 "source_field_item": "VpcPeeringConnectionId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc-peering-connection/{VpcPeeringConnectionId}",
                 "is_array": True, "conditional": "VpcPeeringConnectionId IS NOT NULL"},
                {"relation_type": "routes_to", "target_type": "ec2.vpc-endpoint", "source_field": "Routes",
                 "source_field_item": "GatewayId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc-endpoint/{GatewayId}",
                 "is_array": True, "conditional": "GatewayId LIKE 'vpce-%'"},
                {"relation_type": "routes_to", "target_type": "ec2.network-interface", "source_field": "Routes",
                 "source_field_item": "NetworkInterfaceId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:network-interface/{NetworkInterfaceId}",
                 "is_array": True, "conditional": "NetworkInterfaceId IS NOT NULL"},
                {"relation_type": "routes_to", "target_type": "ec2.instance", "source_field": "Routes",
                 "source_field_item": "InstanceId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:instance/{InstanceId}",
                 "is_array": True, "conditional": "InstanceId IS NOT NULL"},
                {"relation_type": "routes_to", "target_type": "ec2.egress-only-internet-gateway", "source_field": "Routes",
                 "source_field_item": "EgressOnlyInternetGatewayId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:egress-only-internet-gateway/{EgressOnlyInternetGatewayId}",
                 "is_array": True, "conditional": "EgressOnlyInternetGatewayId IS NOT NULL"}
            ],
            
            "ec2.volume": [
                {"relation_type": "encrypted_by", "target_type": "kms.key", "source_field": "KmsKeyId",
                 "target_uid_pattern": "arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}", "conditional": "Encrypted = TRUE"},
                {"relation_type": "attached_to", "target_type": "ec2.instance", "source_field": "Attachments",
                 "source_field_item": "InstanceId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:instance/{InstanceId}", "is_array": True},
                {"relation_type": "backs_up_to", "target_type": "ec2.snapshot", "source_field": "VolumeId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:snapshot:*{VolumeId}*", "note": "Implicit backup relationship"}
            ],
            
            "ec2.snapshot": [
                {"relation_type": "encrypted_by", "target_type": "kms.key", "source_field": "KmsKeyId",
                 "target_uid_pattern": "arn:aws:kms:{region}:{account_id}:key/{KmsKeyId}", "conditional": "Encrypted = TRUE"},
                {"relation_type": "backup_of", "target_type": "ec2.volume", "source_field": "VolumeId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:volume/{VolumeId}"}
            ],
            
            "ec2.network-interface": [
                {"relation_type": "contained_by", "target_type": "ec2.subnet", "source_field": "SubnetId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}"},
                {"relation_type": "attached_to", "target_type": "ec2.security-group", "source_field": "Groups",
                 "source_field_item": "GroupId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "ec2.instance", "source_field": "Attachment.InstanceId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:instance/{InstanceId}", "conditional": "Attachment IS NOT NULL"}
            ],
            
            "ec2.nat-gateway": [
                {"relation_type": "contained_by", "target_type": "ec2.subnet", "source_field": "SubnetId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}"},
                {"relation_type": "uses", "target_type": "ec2.elastic-ip", "source_field": "NatGatewayAddresses",
                 "source_field_item": "AllocationId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:elastic-ip/{AllocationId}", "is_array": True}
            ],
            
            "ec2.internet-gateway": [
                {"relation_type": "attached_to", "target_type": "ec2.vpc", "source_field": "Attachments",
                 "source_field_item": "VpcId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}", "is_array": True}
            ],
            
            "ec2.transit-gateway": [
                {"relation_type": "uses", "target_type": "ec2.transit-gateway-route-table", "source_field": "Options.AssociationDefaultRouteTableId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:transit-gateway-route-table/{AssociationDefaultRouteTableId}",
                 "conditional": "Options.AssociationDefaultRouteTableId IS NOT NULL"},
                {"relation_type": "uses", "target_type": "ec2.transit-gateway-route-table", "source_field": "Options.PropagationDefaultRouteTableId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:transit-gateway-route-table/{PropagationDefaultRouteTableId}",
                 "conditional": "Options.PropagationDefaultRouteTableId IS NOT NULL"}
            ],
            
            "ec2.transit-gateway-attachment": [
                {"relation_type": "attached_to", "target_type": "ec2.transit-gateway", "source_field": "TransitGatewayId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:transit-gateway/{TransitGatewayId}"},
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "ResourceId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{ResourceId}", "conditional": "ResourceType = 'vpc'"},
                {"relation_type": "attached_to", "target_type": "ec2.subnet", "source_field": "SubnetIds",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{item}", "is_array": True}
            ],
            
            "ec2.vpc-peering-connection": [
                {"relation_type": "connected_to", "target_type": "ec2.vpc", "source_field": "RequesterVpcInfo.VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "connected_to", "target_type": "ec2.vpc", "source_field": "AccepterVpcInfo.VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{AccepterVpcInfo.Region}:{AccepterVpcInfo.OwnerId}:vpc/{VpcId}"}
            ],
            
            "ec2.vpc-endpoint": [
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "attached_to", "target_type": "ec2.subnet", "source_field": "SubnetIds",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{item}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "ec2.security-group", "source_field": "Groups",
                 "source_field_item": "GroupId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{GroupId}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "ec2.route-table", "source_field": "RouteTableIds",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:route-table/{item}", "is_array": True}
            ],
            
            "ec2.network-acl": [
                {"relation_type": "contained_by", "target_type": "ec2.vpc", "source_field": "VpcId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:vpc/{VpcId}"},
                {"relation_type": "attached_to", "target_type": "ec2.subnet", "source_field": "Associations",
                 "source_field_item": "SubnetId", "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{SubnetId}", "is_array": True}
            ],
            
            "ec2.elastic-ip": [
                {"relation_type": "attached_to", "target_type": "ec2.instance", "source_field": "InstanceId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:instance/{InstanceId}", "conditional": "InstanceId IS NOT NULL"},
                {"relation_type": "attached_to", "target_type": "ec2.network-interface", "source_field": "NetworkInterfaceId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:network-interface/{NetworkInterfaceId}", "conditional": "NetworkInterfaceId IS NOT NULL"}
            ],
            
            "ec2.launch-template": [
                {"relation_type": "uses", "target_type": "ec2.security-group", "source_field": "LaunchTemplateData.SecurityGroupIds",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:security-group/{item}", "is_array": True},
                {"relation_type": "uses", "target_type": "iam.instance-profile", "source_field": "LaunchTemplateData.IamInstanceProfile.Arn",
                 "target_uid_pattern": "{Arn}", "conditional": "LaunchTemplateData.IamInstanceProfile IS NOT NULL"},
                {"relation_type": "uses", "target_type": "ec2.key-pair", "source_field": "LaunchTemplateData.KeyName",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:key-pair/{KeyName}"}
            ],
            
            "ec2.auto-scaling-group": [
                {"relation_type": "uses", "target_type": "ec2.launch-template", "source_field": "LaunchTemplate.LaunchTemplateId",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:launch-template/{LaunchTemplateId}", "conditional": "LaunchTemplate IS NOT NULL"},
                {"relation_type": "attached_to", "target_type": "ec2.subnet", "source_field": "VPCZoneIdentifier",
                 "target_uid_pattern": "arn:aws:ec2:{region}:{account_id}:subnet/{item}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "elbv2.target-group", "source_field": "TargetGroupARNs",
                 "target_uid_pattern": "{item}", "is_array": True},
                {"relation_type": "attached_to", "target_type": "elb.load-balancer", "source_field": "LoadBalancerNames",
                 "target_uid_pattern": "arn:aws:elasticloadbalancing:{region}:{account_id}:loadbalancer/{item}", "is_array": True}
            ]
        }
    
    # Continuing in next message...
