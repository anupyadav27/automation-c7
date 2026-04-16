"""Shared utility functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(filepath: str | Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    with open(filepath) as f:
        return yaml.safe_load(f) or {}


def merge_dicts(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries (override wins)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result
