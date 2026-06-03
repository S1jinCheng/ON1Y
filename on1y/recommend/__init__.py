"""Content-based related-item recommendations."""

from on1y.recommend.feedback import record_less_relevant
from on1y.recommend.similar import find_related_items

__all__ = ["find_related_items", "record_less_relevant"]
