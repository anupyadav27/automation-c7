"""
Stage 3 — build architecture.

Places every discovered asset into the layered account diagram: account →
region → VPC → AZ → subnet → workload, with containment rendered as nesting
and everything else as coded references. Pure re-projection of stage 1's
output — no cloud calls — so it re-runs for free.

Artifacts:
    out/scene.json             the scene graph
    out/resources.json         per-resource detail tables

`ui/` was a Vite SPA that read a copy of the scene from its own `public/`
directory. The console replaced it — it reads `out/scene.json` directly, which
is why the sync no longer needs a running API — so the copy stopped being read
some time before it stopped being written. `docs/build-plan.md` recorded the
intent to retire it; this is that.

The DB-backed twin of this stage is the Inventory Engine's
GET /api/v1/inventory/architecture (architecture_builder.py).
"""
import logging
import os
from types import SimpleNamespace

from cspm import paths

logger = logging.getLogger("pipeline.architecture")

SCENE_PATH = os.path.join(paths.OUT, "scene.json")


def run(region: str = None, ui: bool = False, resources: bool = True) -> dict:
    from providers.aws.cli import cmd_resources, cmd_scene

    rc = cmd_scene(SimpleNamespace(region=region, ui=ui))
    if rc not in (0, None):
        raise RuntimeError(f"scene build failed with exit code {rc}")

    if resources:
        rc = cmd_resources(SimpleNamespace(ui=ui, raw=False))
        if rc not in (0, None):
            logger.warning("resources build failed with exit code %s", rc)

    logger.info("build_architecture: scene written to %s (ui=%s)", SCENE_PATH, ui)
    return {"scene_path": SCENE_PATH, "ui": ui}
