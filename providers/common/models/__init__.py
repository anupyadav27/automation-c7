"""Common data models and interfaces"""

from .provider_interface import (
    DiscoveryScanner,
    AuthenticationError,
    DiscoveryError,
    ScannerConfigError
)

__all__ = [
    'DiscoveryScanner',
    'AuthenticationError',
    'DiscoveryError',
    'ScannerConfigError'
]
