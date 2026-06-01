"""Content extraction — platform plugins registered via ExtractorRegistry."""

from on1y.extract.registry import ExtractorRegistry, get_default_registry

__all__ = ["ExtractorRegistry", "get_default_registry"]
