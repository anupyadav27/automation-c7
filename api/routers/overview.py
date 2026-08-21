from fastapi import APIRouter

from store import edges as edges_store
from store import inventory as inventory_store
from store import pipeline as pipeline_store

router = APIRouter(prefix="/api/v1", tags=["overview"])


@router.get("/overview")
def overview():
    """
    What the estate is, in one call.

    Findings and savings used to be half of this. Both engines moved to the
    threat-engine platform and the tables went with them, so every call raised
    on the import and answered 500 — which is also why the console's sync
    quietly kept yesterday's estate rather than the one just scanned.

    What is left is what this repo actually knows: how much there is, how it is
    connected, and when it was last looked at.
    """
    _, assets_total = inventory_store.list_assets(limit=1)
    runs, _ = pipeline_store.list_runs(limit=5)

    return {"data": {
        "assets": assets_total,
        "edges": edges_store.count(),
        "recent_runs": runs,
    }}
