"""
Filesystem anchors shared by the engines.

The repo root is resolved by cspm.paths (marker files, not `..` counting), so
every engine agrees on where `engine_output/` and `out/` live regardless of
its own location in the tree.
"""
from pathlib import Path

from cspm import paths as _cspm_paths


def get_project_root() -> Path:
    return Path(_cspm_paths.ROOT)


def get_engine_output_root() -> Path:
    return get_project_root() / "engine_output"
