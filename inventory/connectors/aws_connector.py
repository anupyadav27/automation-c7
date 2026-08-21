"""
AWS Provider Connector

Collects AWS resources using boto3.
"""

import boto3
import json
from typing import List, Dict, Any, Optional
from botocore.config import Config
from ..schemas.asset_schema import Provider


class AWSConnector:
    """AWS resource collector"""
    
    def __init__(self, session: Optional[boto3.Session] = None):
        self.session = session or boto3.Session()
        self.boto_config = Config(
            retries={'max_attempts': 5, 'mode': 'standard'},
            read_timeout=60,
            connect_timeout=10
        )
    
    def collect_service_resources(
        self,
        service_name: str,
        account_id: str,
        region: str
    ) -> Dict[str, Any]:
        """
        Collect resources for a specific AWS service.
        
        Returns:
            Raw resource data dictionary
        """
        try:
            client = self.session.client(service_name, region_name=region, config=self.boto_config)
            
            # Service-specific collection logic
            if service_name == "s3":
                return self._collect_s3(client, account_id, region)
            elif service_name == "ec2":
                return self._collect_ec2(client, account_id, region)
            elif service_name == "iam":
                return self._collect_iam(client, account_id, region)
            elif service_name == "rds":
                return self._collect_rds(client, account_id, region)
            else:
                # Generic collection
                return self._collect_generic(client, service_name, account_id, region)
        
        except Exception as e:
            return {
                "error": str(e),
                "service": service_name,
                "account_id": account_id,
                "region": region
            }
    
    def _collect_s3(self, client, account_id: str, region: str) -> Dict[str, Any]:
        """Collect S3 buckets"""
        buckets = []
        try:
            response = client.list_buckets()
            for bucket in response.get("Buckets", []):
                bucket_name = bucket["Name"]
                # Get bucket details
                try:
                    location = client.get_bucket_location(Bucket=bucket_name)
                    tags = client.get_bucket_tagging(Bucket=bucket_name)
                    buckets.append({
                        "Name": bucket_name,
                        "CreationDate": bucket["CreationDate"].isoformat(),
                        "Region": location.get("LocationConstraint") or "us-east-1",
                        "Tags": tags.get("TagSet", [])
                    })
                except Exception:
                    buckets.append({
                        "Name": bucket_name,
                        "CreationDate": bucket["CreationDate"].isoformat()
                    })
        except Exception as e:
            return {"error": str(e), "service": "s3"}
        
        return {"Buckets": buckets}
    
    def _collect_ec2(self, client, account_id: str, region: str) -> Dict[str, Any]:
        """Collect EC2 resources"""
        resources = {}
        
        # Instances
        try:
            instances = client.describe_instances()
            resources["Instances"] = []
            for reservation in instances.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    resources["Instances"].append(instance)
        except Exception:
            pass
        
        # VPCs
        try:
            vpcs = client.describe_vpcs()
            resources["Vpcs"] = vpcs.get("Vpcs", [])
        except Exception:
            pass
        
        # Subnets
        try:
            subnets = client.describe_subnets()
            resources["Subnets"] = subnets.get("Subnets", [])
        except Exception:
            pass
        
        # Security Groups
        try:
            sgs = client.describe_security_groups()
            resources["SecurityGroups"] = sgs.get("SecurityGroups", [])
        except Exception:
            pass
        
        return resources
    
    def _collect_iam(self, client, account_id: str, region: str) -> Dict[str, Any]:
        """Collect IAM resources"""
        resources = {}
        
        # Users
        try:
            users = client.list_users()
            resources["Users"] = users.get("Users", [])
        except Exception:
            pass
        
        # Roles
        try:
            roles = client.list_roles()
            resources["Roles"] = roles.get("Roles", [])
        except Exception:
            pass
        
        # Groups
        try:
            groups = client.list_groups()
            resources["Groups"] = groups.get("Groups", [])
        except Exception:
            pass
        
        return resources
    
    def _collect_rds(self, client, account_id: str, region: str) -> Dict[str, Any]:
        """Collect RDS resources"""
        resources = {}
        
        # DB Instances
        try:
            instances = client.describe_db_instances()
            resources["DBInstances"] = instances.get("DBInstances", [])
        except Exception:
            pass
        
        return resources
    
    def _collect_generic(self, client, service_name: str, account_id: str, region: str) -> Dict[str, Any]:
        """Generic collection for unknown services"""
        return {
            "service": service_name,
            "account_id": account_id,
            "region": region,
            "note": "Generic collection not implemented"
        }

