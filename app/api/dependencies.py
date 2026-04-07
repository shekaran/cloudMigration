"""FastAPI dependency injection — shared service instances wired at startup."""

from app.adapters.registry import AdapterRegistry
from app.services.containerization import ContainerizationRecommender
from app.services.discovery import DiscoveryService
from app.services.firewall_engine import FirewallEngine
from app.services.k8s_migration import K8sMigrationService
from app.services.k8s_translation import K8sTranslationService
from app.services.network_planner import NetworkPlanner
from app.services.orchestrator import MigrationOrchestrator
from app.services.strategy import StrategyEngine
from app.services.translation import TranslationService
from app.services.validation import ValidationEngine

_registry: AdapterRegistry | None = None
_discovery_service: DiscoveryService | None = None
_translation_service: TranslationService | None = None
_orchestrator: MigrationOrchestrator | None = None
_strategy_engine: StrategyEngine | None = None
_validation_engine: ValidationEngine | None = None
_network_planner: NetworkPlanner | None = None
_firewall_engine: FirewallEngine | None = None
_k8s_translation_service: K8sTranslationService | None = None
_k8s_migration_service: K8sMigrationService | None = None
_containerization_recommender: ContainerizationRecommender | None = None


def configure_services(
    registry: AdapterRegistry,
    discovery_service: DiscoveryService,
    translation_service: TranslationService,
    orchestrator: MigrationOrchestrator,
    strategy_engine: StrategyEngine | None = None,
    validation_engine: ValidationEngine | None = None,
    network_planner: NetworkPlanner | None = None,
    firewall_engine: FirewallEngine | None = None,
    k8s_translation_service: K8sTranslationService | None = None,
    k8s_migration_service: K8sMigrationService | None = None,
    containerization_recommender: ContainerizationRecommender | None = None,
) -> None:
    """Called once at app startup to wire service instances."""
    global _registry, _discovery_service, _translation_service, _orchestrator
    global _strategy_engine, _validation_engine, _network_planner, _firewall_engine
    global _k8s_translation_service, _k8s_migration_service, _containerization_recommender
    _registry = registry
    _discovery_service = discovery_service
    _translation_service = translation_service
    _orchestrator = orchestrator
    _strategy_engine = strategy_engine
    _validation_engine = validation_engine
    _network_planner = network_planner
    _firewall_engine = firewall_engine
    _k8s_translation_service = k8s_translation_service
    _k8s_migration_service = k8s_migration_service
    _containerization_recommender = containerization_recommender


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


def get_strategy_engine() -> StrategyEngine:
    """FastAPI dependency that provides the StrategyEngine."""
    if _strategy_engine is None:
        raise RuntimeError("StrategyEngine not initialized — app startup incomplete")
    return _strategy_engine


def get_validation_engine() -> ValidationEngine:
    """FastAPI dependency that provides the ValidationEngine."""
    if _validation_engine is None:
        raise RuntimeError("ValidationEngine not initialized — app startup incomplete")
    return _validation_engine


def get_network_planner() -> NetworkPlanner:
    """FastAPI dependency that provides the NetworkPlanner."""
    if _network_planner is None:
        raise RuntimeError("NetworkPlanner not initialized — app startup incomplete")
    return _network_planner


def get_firewall_engine() -> FirewallEngine:
    """FastAPI dependency that provides the FirewallEngine."""
    if _firewall_engine is None:
        raise RuntimeError("FirewallEngine not initialized — app startup incomplete")
    return _firewall_engine


def get_k8s_translation_service() -> K8sTranslationService:
    """FastAPI dependency that provides the K8sTranslationService."""
    if _k8s_translation_service is None:
        raise RuntimeError("K8sTranslationService not initialized — app startup incomplete")
    return _k8s_translation_service


def get_k8s_migration_service() -> K8sMigrationService:
    """FastAPI dependency that provides the K8sMigrationService."""
    if _k8s_migration_service is None:
        raise RuntimeError("K8sMigrationService not initialized — app startup incomplete")
    return _k8s_migration_service


def get_containerization_recommender() -> ContainerizationRecommender:
    """FastAPI dependency that provides the ContainerizationRecommender."""
    if _containerization_recommender is None:
        raise RuntimeError("ContainerizationRecommender not initialized — app startup incomplete")
    return _containerization_recommender


def get_graph_service():
    """Placeholder — graph is built on-demand from resources, not a singleton."""
    pass
