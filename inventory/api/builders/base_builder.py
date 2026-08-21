"""
Base Architecture Builder — shared output format and helpers.

All CSP-specific builders inherit from this and produce the same output structure.
The UI renders this structure identically regardless of which CSP produced it.

Output schema:
{
  accounts: [{
    account_id, provider,
    regions: [{
      region,
      availability_zones: ["az-1a", "az-1b"],
      vpcs: [{
        uid, name, cidr,
        gateways: [{ uid, name, type, subtype }],          ← IGW, NAT, TGW
        subnets: [{
          uid, name, az, subnet_type (public/private),
          badges: [{ type, name }],                         ← NACL, RT
          resources: [{
            uid, name, type, category, subcategory,
            children: [{                                    ← expandable: ENI, SG, EBS
              uid, name, type, relation
            }]
          }]
        }],
        edge_services: [{ uid, name, type }],               ← ELB, VPC endpoints
      }],
      regional_services: {                                   ← services not in VPC
        "compute-serverless": [{ uid, name, type }],         ← Lambda
        "compute-database": [{ uid, name, type }],           ← DynamoDB
        "messaging": [{ uid, name, type }],                  ← SQS, SNS
        ...
      },
    }],
    public_services: {                                       ← internet-facing
      "storage-object": [{ uid, name, type }],               ← S3
      "public": [{ uid, name, type }],                       ← CloudFront, API GW
      "network-dns": [{ uid, name, type }],                  ← Route53
    },
    supporting_services: {                                   ← bottom panel
      "identity": { count, items: [{ uid, name, ref_id }] },
      "encryption": { count, items: [...] },
      "monitoring": { count, items: [...] },
      "security": { count, items: [...] },
      ...
    },
  }],
  relationships: [...],
  stats: { ... }
}
"""

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseArchitectureBuilder(ABC):
    """Base class for CSP-specific architecture builders."""

    def __init__(self, taxonomy: Dict[str, Dict], relationships: List[Dict]):
        self.taxonomy = taxonomy
        self.relationships = relationships
        self._build_relationship_indexes()

    def _build_relationship_indexes(self):
        """Index relationships for fast lookup."""
        self.contained_by: Dict[str, str] = {}
        self.children_of: Dict[str, List[str]] = defaultdict(list)
        self.attached_to: Dict[str, List[Dict]] = defaultdict(list)

        # Two passes: first VPC-level, then subnet-level (subnet overwrites VPC)
        vpc_parents = {}
        subnet_parents = {}

        for rel in self.relationships:
            from_uid = rel.get("from_uid", "")
            to_uid = rel.get("to_uid", "")
            rel_type = (rel.get("relation_type") or "").lower()
            to_type = (rel.get("to_resource_type") or "").lower()

            if rel_type in ("contained_by", "in_subnet", "in_vpc"):
                if self._is_subnet_type(to_type):
                    subnet_parents[from_uid] = to_uid
                elif self._is_vpc_type(to_type):
                    vpc_parents[from_uid] = to_uid
                else:
                    self.contained_by[from_uid] = to_uid
                self.children_of[to_uid].append(from_uid)
            elif rel_type in ("attached_to", "has_sg", "has_eni", "has_volume",
                              "has_role", "has_profile", "protected_by", "encrypted_by"):
                self.attached_to[from_uid].append({
                    "uid": to_uid,
                    "type": to_type,
                    "relation": rel_type,
                })

        # Merge: subnet wins over VPC
        for uid, parent in vpc_parents.items():
            self.contained_by[uid] = parent
        for uid, parent in subnet_parents.items():
            self.contained_by[uid] = parent

    @abstractmethod
    def _is_vpc_type(self, resource_type: str) -> bool:
        """Return True if this resource_type is a VPC/VNet/VCN."""
        ...

    @abstractmethod
    def _is_subnet_type(self, resource_type: str) -> bool:
        """Return True if this resource_type is a Subnet."""
        ...

    @abstractmethod
    def build(self, assets: List[Dict]) -> Dict[str, Any]:
        """Build the architecture hierarchy. Subclasses implement this."""
        ...

    # ── Shared helpers ──

    def _get_taxonomy(self, asset: Dict) -> Optional[Dict]:
        """Look up taxonomy for an asset."""
        rt = asset.get("resource_type", "")
        provider = (asset.get("provider") or "").lower()
        return self.taxonomy.get(f"{provider}.{rt}")

    def _make_entry(self, asset: Dict, tax: Optional[Dict] = None) -> Dict:
        """Build a standard resource entry."""
        if not tax:
            tax = self._get_taxonomy(asset) or {}
        _uid = asset.get("resource_uid", "")
        _name = (asset.get("name") or asset.get("display_name")
                 or asset.get("resource_id") or _uid.split("/")[-1])
        _rt = asset.get("resource_type", "")
        return {
            # Both old (resource_uid) and new (uid) keys for UI compatibility
            "resource_uid": _uid,
            "uid": _uid,
            "name": _name,
            "display_name": _name,
            "resource_type": _rt,
            "type": _rt,
            "resource_id": asset.get("resource_id", ""),
            "category": tax.get("category", "other"),
            "subcategory": tax.get("subcategory", ""),
            "region": asset.get("region", ""),
            "account_id": asset.get("account_id", ""),
            "provider": (asset.get("provider") or "").lower(),
            "risk_score": asset.get("risk_score"),
            "criticality": asset.get("criticality"),
            "compliance_status": asset.get("compliance_status"),
            "tags": asset.get("tags"),
            "show_as": tax.get("show_as", "box"),
        }

    def _get_children(self, uid: str, assets_by_uid: Dict) -> List[Dict]:
        """Get attached resources (ENI, SG, EBS) as expandable children."""
        children = []
        for att in self.attached_to.get(uid, []):
            child_asset = assets_by_uid.get(att["uid"])
            if child_asset:
                children.append({
                    "uid": att["uid"],
                    "name": child_asset.get("name") or child_asset.get("resource_id") or att["uid"].split("/")[-1],
                    "type": child_asset.get("resource_type", ""),
                    "relation": att["relation"],
                })
        return children

    def _make_empty_account(self, account_id: str, provider: str) -> Dict:
        return {
            "account_id": account_id,
            "provider": provider,
            "regions": [],
            "public_services": {},
            "supporting_services": {},
        }

    def _make_empty_region(self, region: str) -> Dict:
        return {
            "region": region,
            "availability_zones": [],
            "vpcs": [],
            "regional_primary": {},   # UI expects this key
            "regional_services": {},  # backward compat
        }

    def _make_empty_vpc(self, asset: Dict) -> Dict:
        p = self._get_merged_props(asset)
        # Name: prefer Tags.Name → VpcId → resource_id
        name = self._extract_tag_name(p) or p.get("VpcId") or asset.get("resource_id") or asset.get("resource_uid", "").split("/")[-1]
        _uid = asset.get("resource_uid", "")
        return {
            "resource_uid": _uid,
            "vpc_uid": _uid,
            "uid": _uid,
            "name": name,
            "resource_type": asset.get("resource_type", ""),
            "type": asset.get("resource_type", ""),
            "cidr": self._extract_cidr(asset),
            "gateways": [],
            "subnets": [],
            "edge_services": [],
        }

    def _make_empty_subnet(self, asset: Dict) -> Dict:
        p = self._get_merged_props(asset)
        # Name: prefer Tags.Name → SubnetId → AvailabilityZone → resource_id
        name = (self._extract_tag_name(p) or p.get("SubnetId")
                or p.get("AvailabilityZone") or asset.get("resource_id")
                or asset.get("resource_uid", "").split("/")[-1])
        _uid = asset.get("resource_uid", "")
        return {
            "resource_uid": _uid,
            "subnet_uid": _uid,
            "uid": _uid,
            "name": name,
            "resource_type": asset.get("resource_type", ""),
            "type": asset.get("resource_type", ""),
            "az": self._extract_az(asset),
            "subnet_type": self._infer_subnet_type(asset),
            "cidr": p.get("CidrBlock") or p.get("cidr_block") or "",
            "badges": [],
            "resources": [],
            "resources_by_category": {},
        }

    @staticmethod
    def _extract_tag_name(props: Dict) -> str:
        """Extract Name tag from Tags list or dict."""
        tags = props.get("Tags") or props.get("tags") or {}
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, dict) and t.get("Key") == "Name":
                    return t.get("Value", "")
        elif isinstance(tags, dict):
            return tags.get("Name", "")
        return ""

    def _get_merged_props(self, asset: Dict) -> Dict:
        """Get merged properties — checks emitted_fields inside properties, then top-level."""
        props = asset.get("properties") or {}
        if isinstance(props, str):
            import json
            try: props = json.loads(props)
            except: return {}
        # emitted_fields is nested inside properties for catalog-driven flow
        ef = props.get("emitted_fields", {})
        if isinstance(ef, str):
            import json
            try: ef = json.loads(ef)
            except: ef = {}
        if ef and isinstance(ef, dict):
            return {**props, **ef}  # ef fields take priority
        return props

    def _extract_cidr(self, asset: Dict) -> str:
        p = self._get_merged_props(asset)
        return p.get("CidrBlock") or p.get("cidr_block") or p.get("addressPrefix") or ""

    def _extract_az(self, asset: Dict) -> str:
        p = self._get_merged_props(asset)
        return (p.get("AvailabilityZone") or p.get("availabilityZone")
                or p.get("availability_zone") or p.get("zone") or "")

    def _infer_subnet_type(self, asset: Dict) -> str:
        p = self._get_merged_props(asset)
        if p.get("MapPublicIpOnLaunch") or p.get("map_public_ip_on_launch"):
            return "public"
        return "private"
