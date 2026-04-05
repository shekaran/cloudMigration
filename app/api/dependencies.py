"""FastAPI dependency injection — shared service instances wired at startup."""

from app.adapters.registry import AdapterRegistry
from app.services.discovery import DiscoveryService

_registry: AdapterRegistry | None = None
_discovery_service: DiscoveryService | None = None


def configure_services(registry: AdapterRegistry, discovery_service: DiscoveryService) -> None:
    """Called once at app startup to wire service instances."""
    global _registry, _discovery_service
    _registry = registry
    _discovery_service = discovery_service


def get_adapter_registry() -> AdapterRegistry:
    """FastAPI dependency that provides the AdapterRegistry."""
    if _registry is None:
        raise RuntimeError("AdapterRegistry not initialized — app startup incomplete")
    return _registry


def get_discovery_service() -> DiscoveryService:
    """FastAPI dependency that provides the DiscoveryService."""
    if _discovery_service is None:
        raise RuntimeError("DiscoveryService not initialized — app startup incomplete")
    return _discovery_service
