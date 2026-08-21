"""
Files backend — serves the same contract shapes as postgres from the out/
artifacts the pipeline writes. Read-mostly; the writers it does have
(runs.json) mirror what the postgres backend stores so local mode keeps
full Runs-table parity.
"""
import json
import os

from cspm import paths

NAME = "files"

ARTIFACTS = {
    "assets_v1": os.path.join(paths.OUT, "cspm", "assets.v1.json"),
    "assets_v2": os.path.join(paths.OUT, "cspm", "assets.v2.json"),
    "findings": os.path.join(paths.OUT, "findings.json"),
    "recommendations": os.path.join(paths.OUT, "recommendations.json"),
    "registry": os.path.join(paths.OUT, "registry.json"),
    "runs": os.path.join(paths.OUT, "runs.json"),
    "scene": os.path.join(paths.OUT, "scene.json"),
    "resources": os.path.join(paths.OUT, "resources.json"),
}


def read(kind, default=None):
    path = ARTIFACTS[kind]
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def write(kind, payload):
    path = ARTIFACTS[kind]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=1, default=str)
    return path


def paginate(rows, limit=50, offset=0, sort=None):
    """Uniform list handling so files responses match postgres responses."""
    if sort:
        field, _, direction = sort.partition(":")
        rows = sorted(rows, key=lambda r: (r.get(field) is None, r.get(field)),
                      reverse=(direction == "desc"))
    total = len(rows)
    return rows[offset:offset + limit], total


def match(row, **filters):
    for key, wanted in filters.items():
        if wanted is None:
            continue
        value = row.get(key)
        if isinstance(wanted, (list, tuple, set)):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True
