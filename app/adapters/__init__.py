"""Platform adapters — plugin-based discovery and migration modules."""

from app.adapters.base import AbstractBaseAdapter
from app.adapters.registry import AdapterRegistry

__all__ = ["AbstractBaseAdapter", "AdapterRegistry"]
