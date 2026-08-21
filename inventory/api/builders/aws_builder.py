"""
AWS Architecture Builder

Builds AWS-specific hierarchy:
  Account → Region → AZ → VPC → Subnet → Resources
  + Regional services (Lambda, DynamoDB, SQS)
  + Public services (S3, CloudFront, Route53)
  + Supporting services (IAM, KMS, CloudWatch)
  + EKS hierarchy (cluster → compute + containers)
  + EC2 expandable (instance → ENI, SG, EBS)
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from .base_builder import BaseArchitectureBuilder

logger = logging.getLogger(__name__)

# AWS-specific VPC/Subnet type names
_VPC_TYPES = {"ec2.vpc"}
_SUBNET_TYPES = {"ec2.subnet", "ec2.subnet_subnet"}

# Container services → placed inside VPC as edge_services
_CONTAINER_CLUSTER_TYPES = {"eks.cluster", "ecs.cluster", "eks.nodegroup", "ecs.service"}

# EC2 attachment types (show as expandable children)
_EC2_CHILDREN_TYPES = {"ec2.network-interface", "ec2.security-group", "ec2.volume"}

# EKS subcategory detection
_EKS_INDICATORS = {"eks", "kubernetes", "k8s"}

# Noise VPC names (EC2 account attributes, not real VPCs)
_NOISE_VPC_PREFIXES = ("vpc-max-", "vpc-default-")


class AWSArchitectureBuilder(BaseArchitectureBuilder):

    def _is_vpc_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _VPC_TYPES

    def _is_subnet_type(self, resource_type: str) -> bool:
        return resource_type.lower() in _SUBNET_TYPES

    def build(self, assets: List[Dict]) -> Dict[str, Any]:
        # Index assets
        assets_by_uid: Dict[str, Dict] = {}
        for a in assets:
            assets_by_uid[a["resource_uid"]] = a

        # ── Phase 1: Build structural containers (VPCs, Subnets) ──
        accounts: Dict[str, Dict] = {}
        vpcs_by_uid: Dict[str, Dict] = {}   # vpc_uid → vpc dict
        subnets_by_uid: Dict[str, Dict] = {}  # subnet_uid → subnet dict
        vpc_region: Dict[str, str] = {}      # vpc_uid → region
        azs_per_region: Dict[str, Set[str]] = defaultdict(set)

        for asset in assets:
            rt = asset.get("resource_type", "")
            provider = (asset.get("provider") or "aws").lower()
            account_id = asset.get("account_id", "unknown")
            region = asset.get("region") or "global"

            # Ensure account
            if account_id not in accounts:
                accounts[account_id] = self._make_empty_account(account_id, provider)

            if self._is_vpc_type(rt):
                # Real VPC = ARN contains :vpc/vpc-XXXXXXXX
                # Use vpc-id from the ARN (not the display name) to filter noise entries.
                # Noise: account attributes like vpc-max-elastic-ips, vpc-default-* that
                # Discovery misclassifies as ec2.vpc resources.
                uid = asset.get("resource_uid", "")
                if ":vpc/vpc-" not in uid:
                    continue
                vpc_id = uid.split(":vpc/")[-1]  # e.g. "vpc-0abc123" or "vpc-max-elastic-ips"
                if any(vpc_id.startswith(pfx) for pfx in _NOISE_VPC_PREFIXES):
                    continue
                vpc = self._make_empty_vpc(asset)
                vpcs_by_uid[asset["resource_uid"]] = vpc
                vpc_region[asset["resource_uid"]] = region

            elif self._is_subnet_type(rt):
                uid = asset.get("resource_uid", "")
                # Real subnet = ARN contains :subnet/subnet-
                if ":subnet/subnet-" not in uid:
                    continue
                subnet = self._make_empty_subnet(asset)
                subnets_by_uid[asset["resource_uid"]] = subnet
                az = subnet["az"]
                if az:
                    azs_per_region[region].add(az)

        # Link subnets to VPCs
        for sub_uid, subnet in subnets_by_uid.items():
            parent_vpc_uid = self.contained_by.get(sub_uid)
            if parent_vpc_uid and parent_vpc_uid in vpcs_by_uid:
                vpcs_by_uid[parent_vpc_uid]["subnets"].append(subnet)

        logger.info(f"AWS builder: {len(vpcs_by_uid)} VPCs, {len(subnets_by_uid)} subnets")

        # ── Phase 2: Place resources ──
        regional_services: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))  # region → category → items
        public_services: Dict[str, List] = defaultdict(list)  # category → items
        supporting_services: Dict[str, List] = defaultdict(list)  # group → items
        ref_counter: Dict[str, int] = defaultdict(int)

        for asset in assets:
            rt = asset.get("resource_type", "")
            if self._is_vpc_type(rt) or self._is_subnet_type(rt):
                continue  # Already handled

            tax = self._get_taxonomy(asset)
            if not tax:
                continue

            show_as = tax.get("show_as", "box")
            if show_as == "hidden":
                continue

            category = tax.get("category", "other")
            region = asset.get("region") or "global"
            uid = asset["resource_uid"]

            entry = self._make_entry(asset, tax)

            # Attach children (ENI, SG, EBS) to EC2 instances
            if rt == "ec2.instance":
                entry["children"] = self._get_children(uid, assets_by_uid)
                entry["subcategory"] = self._detect_eks_association(asset)

            # ── Routing logic — driven by diagram_zone from taxonomy ──
            dz = tax.get("diagram_zone", "services")

            if dz == "hidden":
                continue

            if dz == "supporting":
                prefix = _REF_PREFIXES.get(tax.get("subcategory", ""),
                         _REF_PREFIXES.get(category, "REF"))
                ref_counter[prefix] += 1
                entry["ref_id"] = f"{prefix}-{ref_counter[prefix]}"
                supporting_services[category].append(entry)
                continue

            if dz == "internet_edge":
                public_services[category].append(entry)
                continue

            if dz == "network":
                # Transit gateway → its own regional bucket
                if rt == "ec2.transit-gateway":
                    regional_services[region]["network-gateway"].append(entry)
                else:
                    placed = self._place_in_vpc_gateways(entry, uid, region, vpcs_by_uid, vpc_region)
                    if not placed:
                        regional_services[region][category].append(entry)
                continue

            if dz == "compute":
                # Container clusters go to VPC edge_services
                if rt in _CONTAINER_CLUSTER_TYPES:
                    if "eks" in rt:
                        entry["subcategory"] = "eks-compute" if "nodegroup" in rt else "eks"
                    else:
                        entry["subcategory"] = "ecs-service" if "service" in rt else "ecs"
                    placed = self._place_in_vpc_edge(entry, uid, region, vpcs_by_uid, vpc_region)
                    if not placed:
                        regional_services[region][category].append(entry)
                    continue
                # All other compute: subnet → VPC edge → regional
                placed = self._place_in_subnet(entry, uid, region, vpcs_by_uid,
                                               vpc_region, subnets_by_uid)
                if placed:
                    continue
                placed = self._place_in_vpc_edge(entry, uid, region, vpcs_by_uid, vpc_region)
                if placed:
                    continue
                regional_services[region][category].append(entry)
                continue

            # "services" and any unknown zone → regional
            regional_services[region][category].append(entry)

        # ── Phase 3: Assemble accounts → regions ──
        for account_id, acct in accounts.items():
            regions_map: Dict[str, Dict] = {}

            # Create regions from VPCs
            for vpc_uid, vpc in vpcs_by_uid.items():
                region = vpc_region.get(vpc_uid, "unknown")
                acct_id = assets_by_uid.get(vpc_uid, {}).get("account_id", "")
                if acct_id != account_id:
                    continue
                if region not in regions_map:
                    regions_map[region] = self._make_empty_region(region)
                    regions_map[region]["availability_zones"] = sorted(azs_per_region.get(region, []))
                regions_map[region]["vpcs"].append(vpc)

            # Add regions from regional_services
            for region, cats in regional_services.items():
                if region not in regions_map:
                    regions_map[region] = self._make_empty_region(region)
                    regions_map[region]["availability_zones"] = sorted(azs_per_region.get(region, []))
                # UI expects "regional_primary" not "regional_services"
                regions_map[region]["regional_primary"] = dict(cats)

            # PaaS subcategory → compute group key
            _PAAS_GROUP = {
                "eks": "eks-compute",     "eks-compute": "eks-compute",
                "ecs": "ecs-compute",     "ecs-service": "ecs-compute",
                "rds": "rds-compute",
                "elasticache": "elasticache-compute",
                "redshift": "redshift-compute",
                "docdb": "docdb-compute",
                "neptune": "neptune-compute",
                "sagemaker": "sagemaker-compute",
                "emr": "emr-compute",
            }

            # Convert subnet resources list → resources_by_category dict (UI expects this)
            for region_data in regions_map.values():
                for vpc in region_data["vpcs"]:
                    for subnet in vpc["subnets"]:
                        resources = subnet.pop("resources", [])
                        rbc = defaultdict(list)
                        for r in resources:
                            sub = r.get("subcategory", "")
                            group_key = _PAAS_GROUP.get(sub, "compute")
                            rbc[group_key].append(r)
                        subnet["resources_by_category"] = dict(rbc)

            # ── Filter empty VPCs (no gateways, no edge services, no subnet resources) ──
            for region_data in regions_map.values():
                region_data["vpcs"] = [
                    vpc for vpc in region_data["vpcs"]
                    if vpc.get("gateways")
                    or vpc.get("edge_services")
                    or any(
                        any(len(v) > 0 for v in sn.get("resources_by_category", {}).values())
                        for sn in vpc.get("subnets", [])
                    )
                ]

            # ── Filter empty regions (no VPCs and no regional services) ──
            regions_map = {
                region: data for region, data in regions_map.items()
                if data.get("vpcs")
                or any(len(items) > 0 for items in data.get("regional_primary", {}).values())
            }

            acct["regions"] = sorted(regions_map.values(), key=lambda r: r["region"])
            acct["global_primary"] = {}  # UI expects this key
            acct["public_services"] = dict(public_services)
            acct["supporting_services"] = {
                grp: {"count": len(items), "items": items, "global": items, "regional": {}}
                for grp, items in supporting_services.items()
            }

        return {
            "accounts": list(accounts.values()),
            "relationships": self.relationships,
            "stats": {
                "total_assets": len(assets),
                "total_vpcs": len(vpcs_by_uid),
                "total_subnets": len(subnets_by_uid),
                "total_relationships": len(self.relationships),
            },
        }

    # ── Placement helpers ──

    def _place_in_subnet(self, entry, uid, region, vpcs_by_uid, vpc_region, subnets_by_uid) -> bool:
        """Place resource inside a subnet via containment relationship."""
        parent_uid = self.contained_by.get(uid)
        if not parent_uid:
            return False

        # Direct subnet match
        if parent_uid in subnets_by_uid:
            # Find which VPC owns this subnet
            for vpc_uid, vpc in vpcs_by_uid.items():
                for sub in vpc["subnets"]:
                    if sub["uid"] == parent_uid:
                        sub["resources"].append(entry)
                        return True

        # Parent is a VPC → put in first subnet
        if parent_uid in vpcs_by_uid:
            vpc = vpcs_by_uid[parent_uid]
            if vpc["subnets"]:
                vpc["subnets"][0]["resources"].append(entry)
                return True
            vpc["edge_services"].append(entry)
            return True

        return False

    def _place_in_vpc_gateways(self, entry, uid, region, vpcs_by_uid, vpc_region) -> bool:
        """Place gateway inside VPC."""
        parent_uid = self.contained_by.get(uid)
        if parent_uid and parent_uid in vpcs_by_uid:
            vpcs_by_uid[parent_uid]["gateways"].append(entry)
            return True
        # Fallback: first VPC in this region
        for vpc_uid, vpc in vpcs_by_uid.items():
            if vpc_region.get(vpc_uid) == region:
                vpc["gateways"].append(entry)
                return True
        return False

    def _place_in_vpc_edge(self, entry, uid, region, vpcs_by_uid, vpc_region) -> bool:
        """Place edge service (LB, endpoint) inside VPC."""
        parent_uid = self.contained_by.get(uid)
        if parent_uid and parent_uid in vpcs_by_uid:
            vpcs_by_uid[parent_uid]["edge_services"].append(entry)
            return True
        for vpc_uid, vpc in vpcs_by_uid.items():
            if vpc_region.get(vpc_uid) == region:
                vpc["edge_services"].append(entry)
                return True
        return False

    def _detect_eks_association(self, asset: Dict) -> str:
        """Detect if EC2 instance is an EKS node."""
        tags = asset.get("tags") or {}
        if isinstance(tags, str):
            import json
            try: tags = json.loads(tags)
            except: tags = {}
        if isinstance(tags, dict):
            for k in tags:
                if any(ind in k.lower() for ind in _EKS_INDICATORS):
                    return "eks"
        # Check instance profile name
        name = asset.get("name") or ""
        if "eks" in name.lower():
            return "eks"
        return "ec2"


# Reference ID prefixes for supporting services
_REF_PREFIXES = {
    # By subcategory
    "iam": "IAM", "role": "IAM-R", "user": "IAM-U", "policy": "IAM-P",
    "group": "IAM-G", "instance_profile": "IAM-IP",
    "sg": "SG", "sgr": "SGR", "nacl": "NACL", "waf": "WAF",
    "kms": "KMS", "acm": "CERT",
    "vpc": "VPC", "subnet": "SUB", "rt": "RT", "eni": "ENI",
    "eip": "EIP", "vpce": "VPCe", "tgw": "TGW",
    "cw": "CW", "cwlogs": "LOG", "cloudtrail": "CT",
    "ebs": "EBS", "efs": "EFS",
    "ecr": "ECR",
    # By category (fallback)
    "identity": "IAM", "security": "SEC", "encryption": "ENC",
    "monitoring": "MON", "logging": "LOG", "management": "MGT",
    "network": "NET", "compute": "CMP", "storage-block": "EBS",
    "storage-file": "EFS", "storage-object": "S3",
}
