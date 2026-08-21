"""
Provider-neutral resource-UID helpers.

`is_arn` / `normalize_resource_uid` give the normalizer one place to turn a
short-form identifier into the canonical UID. For AWS the heavy lifting is
delegated to the catalog-driven recipes in `providers.aws.runtime.arn` when
they are importable; a DB-loaded identifier-pattern cache
(`preload_identifier_patterns`) can extend this to other CSPs without a
redeploy. Every path degrades to returning the input unchanged — a caller
must never get an exception where a fallback UID would do.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# resource_type -> pattern row, loaded from resource_inventory_identifier
_PATTERNS: Dict[str, Dict[str, Dict[str, Any]]] = {}

_TEMPLATE_COLUMNS = ("arn_template", "arn_format", "uid_pattern", "identifier_pattern")


def is_arn(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith("arn:")


def preload_identifier_patterns(conn, csp: str) -> int:
    """Warm the in-memory pattern cache from resource_inventory_identifier.

    Best-effort: a missing table or column set loads nothing and returns 0.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM resource_inventory_identifier WHERE csp = %s", (csp,)
            )
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.debug("No identifier patterns for %s: %s", csp, exc)
        return 0

    bucket = _PATTERNS.setdefault(csp, {})
    for row in rows:
        rtype = row.get("resource_type") or row.get("resource_key")
        if rtype:
            bucket[str(rtype)] = row
    return len(rows)


def _from_pattern(row: Dict[str, Any], region: str, account_id: str, resource_id: str) -> Optional[str]:
    for col in _TEMPLATE_COLUMNS:
        template = row.get(col)
        if isinstance(template, str) and template:
            try:
                return template.format(
                    region="" if region == "global" else region,
                    account_id=account_id,
                    resource_id=resource_id,
                )
            except (KeyError, IndexError):
                continue
    return None


def normalize_resource_uid(
    resource_uid: str,
    resource_type: str = "",
    provider: str = "aws",
    region: str = "global",
    account_id: str = "",
    resource_arn: str = "",
) -> str:
    """Return the canonical UID for a resource, preferring full ARN form.

    Falls back to the input UID whenever a canonical form cannot be built.
    """
    if is_arn(resource_arn):
        return resource_arn
    if is_arn(resource_uid):
        return resource_uid

    resource_id = (resource_uid or "").rsplit(":", 1)[-1] or resource_uid

    # 1. DB-loaded identifier pattern (any CSP)
    row = _PATTERNS.get(provider, {}).get(resource_type)
    if row:
        built = _from_pattern(row, region, account_id, resource_id)
        if built:
            return built

    # 2. AWS catalog recipes (offline, data-driven)
    if provider == "aws" and resource_type:
        try:
            from providers.aws.runtime import arn as aws_arn
            from providers.aws.runtime.index import load_recipes

            recipe = load_recipes().get(resource_type)
            if recipe:
                return aws_arn.build_from_id(
                    recipe, resource_id, region=region, account_id=account_id
                )
        except Exception:
            pass

    return resource_uid
