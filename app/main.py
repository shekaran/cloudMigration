"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from app.adapters.registry import AdapterRegistry
from app.api.dependencies import configure_services
from app.api.routes.adapters import router as adapters_router
from app.api.routes.analysis import router as analysis_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.migration import router as migration_router
from app.core.config import get_settings
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
from app.terraform.generator import TerraformGenerator
from app.utils.logging import setup_logging

logger = structlog.get_logger(__name__)

# Default adapter config — maps name → dotted class path.
ADAPTER_CONFIG: dict[str, str] = {
    "ibm_classic": "app.adapters.ibm_classic.adapter.IBMClassicAdapter",
    "vmware": "app.adapters.vmware.adapter.VMwareAdapter",
    "kubernetes": "app.adapters.kubernetes.adapter.KubernetesAdapter",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
    setup_logging(settings)

    logger.info("app_startup", env=settings.app_env)

    # Build adapter registry
    registry = AdapterRegistry()
    registry.register_from_config(ADAPTER_CONFIG)
    registry.auto_discover()

    logger.info("adapters_loaded", adapters=registry.registered_adapters)

    # Build services
    discovery_service = DiscoveryService(registry)
    translation_service = TranslationService()
    terraform_generator = TerraformGenerator()

    # Phase 2 engines
    strategy_engine = StrategyEngine()
    validation_engine = ValidationEngine()
    network_planner = NetworkPlanner()

    # Phase 3 engines
    firewall_engine = FirewallEngine()

    # Phase 4 engines
    k8s_translation_service = K8sTranslationService()
    k8s_migration_service = K8sMigrationService()
    containerization_recommender = ContainerizationRecommender()

    orchestrator = MigrationOrchestrator(
        registry=registry,
        translation_service=translation_service,
        terraform_generator=terraform_generator,
        strategy_engine=strategy_engine,
        validation_engine=validation_engine,
        network_planner=network_planner,
        firewall_engine=firewall_engine,
        k8s_translation_service=k8s_translation_service,
        k8s_migration_service=k8s_migration_service,
        containerization_recommender=containerization_recommender,
    )

    # Wire into FastAPI dependency injection
    configure_services(
        registry,
        discovery_service,
        translation_service,
        orchestrator,
        strategy_engine=strategy_engine,
        validation_engine=validation_engine,
        network_planner=network_planner,
        firewall_engine=firewall_engine,
        k8s_translation_service=k8s_translation_service,
        k8s_migration_service=k8s_migration_service,
        containerization_recommender=containerization_recommender,
    )

    yield

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Migration Orchestration Engine",
        description="Multi-Platform Migration Orchestration Engine to IBM Cloud VPC",
        version="0.6.0",
        lifespan=lifespan,
        debug=settings.app_debug,
    )

    app.include_router(discovery_router)
    app.include_router(adapters_router)
    app.include_router(migration_router)
    app.include_router(analysis_router)

    return app


app = create_app()
