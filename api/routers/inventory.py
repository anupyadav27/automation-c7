from fastapi import APIRouter, Depends, HTTPException

from api.common import ListParams, envelope
from store import edges as edges_store
from store import inventory as inventory_store

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/assets")
def list_assets(params: ListParams = Depends(), provider: str = None,
                account_id: str = None, region: str = None,
                resource_type: str = None, scope: str = None,
                format: str = None):
    rows, total = inventory_store.list_assets(
        limit=params.limit, offset=params.offset, sort=params.sort,
        provider=provider, account_id=account_id, region=region,
        resource_type=resource_type, scope=scope)
    return envelope(rows, total, params.limit, params.offset, fmt=format)


@router.get("/drift")
def list_drift(params: ListParams = Depends()):
    rows, total = inventory_store.list_drift(limit=params.limit,
                                             offset=params.offset)
    return envelope(rows, total, params.limit, params.offset)


@router.get("/assets/{resource_uid:path}/relations")
def asset_relations(resource_uid: str, params: ListParams = Depends()):
    """
    Every edge touching this resource, both directions.

    `direction` rides on each row rather than being normalised away. An edge is
    directional but relatedness is not: a security group's whole answer is the
    edges pointing AT it, and only the caller knows which end it is standing on
    — so it is told, and phrases the relationship from there.
    """
    rows = edges_store.relations_for(resource_uid, limit=params.limit)
    return envelope(rows, len(rows), params.limit, params.offset,
                    resource_uid=resource_uid)


@router.get("/assets/{resource_uid:path}")
def get_asset(resource_uid: str):
    asset = inventory_store.get_asset(resource_uid)
    if asset is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown asset: {resource_uid}")
    return {"data": asset}
