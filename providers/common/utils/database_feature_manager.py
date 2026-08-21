"""
Feature flags for discovery runs.

Historically read per-provider feature toggles from the check engine's DB.
The unified platform defaults every feature on; flags can be forced off with
DISCOVERY_FEATURE_<NAME>=false so a bad collector can be disabled without a
redeploy.
"""
import os


class DatabaseFeatureManager:
    def __init__(self, provider: str = "aws"):
        self.provider = provider

    def is_enabled(self, feature: str, default: bool = True) -> bool:
        value = os.getenv(f"DISCOVERY_FEATURE_{feature.upper()}")
        if value is None:
            return default
        return value.lower() in ("1", "true", "yes")
