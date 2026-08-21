"""
Metadata module for inventory engine
Provides database-driven metadata loading
"""

from .service_metadata_loader import ServiceMetadataLoader, ServiceMetadata, ResourceInventoryMetadata

__all__ = ['ServiceMetadataLoader', 'ServiceMetadata', 'ResourceInventoryMetadata']
