"""
Architecture Builder — CSP-specific orchestrator.

Delegates to the right CSP builder based on the provider in the data.
Each builder produces the same output format (defined in base_builder.py).

Usage:
    from architecture_builder import build_architecture_hierarchy

    result = build_architecture_hierarchy(assets, taxonomy, relationships)
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def build_architecture_hierarchy(
    assets: List[Dict[str, Any]],
    taxonomy: Dict[str, Dict[str, Any]],
    relationships: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build nested architecture hierarchy from flat data.

    Detects the CSP from the assets and delegates to the right builder.
    For multi-CSP scans, splits assets by provider and merges results.

    Args:
        assets: inventory_findings rows
        taxonomy: placement rules from architecture_resource_placement
        relationships: inventory_relationships rows
    """
    if not assets:
        return {"accounts": [], "relationships": [], "stats": {}}

    # Detect CSPs in the data
    providers = set()
    for a in assets:
        p = (a.get("provider") or "aws").lower()
        providers.add(p)

    # Single CSP (most common case)
    if len(providers) == 1:
        csp = providers.pop()
        builder = _get_builder(csp, taxonomy, relationships)
        return builder.build(assets)

    # Multi-CSP: split by provider, build each, merge
    assets_by_csp: Dict[str, List] = {}
    for a in assets:
        p = (a.get("provider") or "aws").lower()
        assets_by_csp.setdefault(p, []).append(a)

    merged_accounts = []
    for csp, csp_assets in assets_by_csp.items():
        builder = _get_builder(csp, taxonomy, relationships)
        result = builder.build(csp_assets)
        merged_accounts.extend(result.get("accounts", []))

    return {
        "accounts": merged_accounts,
        "relationships": relationships,
        "stats": {
            "total_assets": len(assets),
            "total_relationships": len(relationships),
            "providers": list(assets_by_csp.keys()),
        },
    }


def _get_builder(csp: str, taxonomy, relationships):
    """Return the right CSP-specific builder."""
    if csp == "aws":
        from .builders.aws_builder import AWSArchitectureBuilder
        return AWSArchitectureBuilder(taxonomy, relationships)
    elif csp == "azure":
        from .builders.azure_builder import AzureArchitectureBuilder
        return AzureArchitectureBuilder(taxonomy, relationships)
    elif csp == "gcp":
        from .builders.gcp_builder import GCPArchitectureBuilder
        return GCPArchitectureBuilder(taxonomy, relationships)
    elif csp == "oci":
        from .builders.oci_builder import OCIArchitectureBuilder
        return OCIArchitectureBuilder(taxonomy, relationships)
    elif csp == "ibm":
        from .builders.ibm_builder import IBMArchitectureBuilder
        return IBMArchitectureBuilder(taxonomy, relationships)
    else:
        # Fallback: use AWS builder (most generic)
        logger.warning(f"No builder for CSP '{csp}', falling back to AWS builder")
        from .builders.aws_builder import AWSArchitectureBuilder
        return AWSArchitectureBuilder(taxonomy, relationships)
