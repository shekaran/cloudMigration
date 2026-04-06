"""FastAPI dependency injection — shared service instances wired at startup."""

from app.adapters.registry import AdapterRegistry
from app.services.discovery import DiscoveryService
from app.services.orchestrator import MigrationOrchestrator
from app.services.translation import TranslationService

_registry: AdapterRegistry | None = None
_discovery_service: DiscoveryService | None = None
_translation_service: TranslationService | None = None
_orchestrator: MigrationOrchestrator | None = None


def configure_services(
    registry: AdapterRegistry,
    discovery_service: DiscoveryService,
    translation_service: TranslationService,
    orchestrator: MigrationOrchestrator,
) -> None:
    """Called once at app startup to wire service instances."""
    global _registry, _discovery_service, _translation_service, _orchestrator
    _registry = registry
    _discovery_service = discovery_service
    _translation_service = translation_service
    _orchestrator = orchestrator


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


def get_translation_service() -> TranslationService:
    """FastAPI dependency that provides the TranslationService."""
    if _translation_service is None:
        raise RuntimeError("TranslationService not initialized — app startup incomplete")
    return _translation_service


def get_orchestrator() -> MigrationOrchestrator:
    """FastAPI dependency that provides the MigrationOrchestrator."""
    if _orchestrator is None:
        raise RuntimeError("MigrationOrchestrator not initialized — app startup incomplete")
    return _orchestrator
