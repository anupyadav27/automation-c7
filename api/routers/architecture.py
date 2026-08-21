"""
Architecture — the scene graph, served to the console.

The scene is the diagram: a containment tree plus, on every node, where it draws
inside its container. Both halves are produced offline by

    python -m providers.aws.cli scene

and written to `out/scene.json`, so this router reads a file rather than
recomputing anything. That is deliberate. Placement needs the resources' RAW
payloads to decide, for example, whether a private endpoint is a route-table
entry on the network border or an interface inside a segment - and those
payloads are far too large to keep in the store. The scene is the artifact; the
API hands it over.

The payload is the provider-neutral shape defined by
`providers/common/topology/model.yaml`, so a console rendering it does not need
to know which cloud it came from.
"""
import json
import os

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/architecture", tags=["architecture"])

# docker-compose mounts ./out read-only at /app/out; running the API straight
# from a checkout finds the same file two directories up.
OUT = os.getenv("OUT_DIR") or os.path.join(
    os.path.dirname(__file__), "..", "..", "out")


def _scene_path():
    return os.path.abspath(os.path.join(OUT, "scene.json"))


@router.get("/scene")
def scene():
    """
    The whole scene graph: nesting tree, overlay buckets, edges and counts.

    404 rather than an empty tree when it has not been generated. An empty
    diagram and a missing one look identical in the UI, and the second is a
    pipeline that did not run - which the console should be able to say.
    """
    path = _scene_path()
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no scene generated; run `providers.aws.cli scene` first")
    with open(path) as fh:
        return json.load(fh)


@router.get("/meta")
def meta():
    """
    Cheap header for the page: account, region and layer counts, no tree.

    The full scene runs to several hundred kilobytes, and a page that only wants
    to say "ap-south-1 · 827 assets" should not have to pull all of it.
    """
    path = _scene_path()
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="no scene generated")
    with open(path) as fh:
        doc = json.load(fh)
    return {
        "account": doc.get("account"),
        "region": doc.get("region"),
        "counts": doc.get("counts", {}),
        "meta": doc.get("meta", {}),
        "generated_at": os.path.getmtime(path),
    }
