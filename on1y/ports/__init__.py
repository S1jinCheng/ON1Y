"""Abstract ports (interfaces) for storage and extraction — enables backend migration."""

from on1y.ports.extractor import ExtractorPort
from on1y.ports.storage import StoragePort

__all__ = ["ExtractorPort", "StoragePort"]
