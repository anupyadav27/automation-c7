"""
Provider-neutral diagram topology.

`model.yaml` defines the layout grammar once, in terms of roles. Each provider
ships a `topology_binding.yaml` naming which of its types play which role, and
inherits every placement rule. A new cloud is a binding file, not a renderer.
"""

from providers.common.topology.layout import (
    Position, layout, load_binding, load_model, resolve_role, sort_key,
)

__all__ = ['Position', 'layout', 'load_binding', 'load_model',
           'resolve_role', 'sort_key']
