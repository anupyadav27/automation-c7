"""
The platform's flow, one module per stage:

    1. discover            collect raw resources from the cloud provider
    2. build_assets        normalise them into canonical cspm_asset records
    3. build_architecture  place assets into the layered account diagram
    4. compliance          run policy checks for one, many, or all resources
    5. finops              evaluate cost rules and price the savings

Each stage reads the previous stage's artifact from `out/` and writes its
own, so any stage can be re-run alone. `orchestration.pipeline` is the CLI
that chains them.
"""

from . import build_architecture, build_assets, discover

__all__ = [
    "discover",
    "build_assets",
    "build_architecture",
]
