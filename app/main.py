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
from app.services.discovery import DiscoveryService
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

    orchestrator = MigrationOrchestrator(
        registry=registry,
        translation_service=translation_service,
        terraform_generator=terraform_generator,
        strategy_engine=strategy_engine,
        validation_engine=validation_engine,
        network_planner=network_planner,
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
    )

    yield

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Migration Orchestration Engine",
        description="Multi-Platform Migration Orchestration Engine to IBM Cloud VPC",
        version="0.4.0",
        lifespan=lifespan,
        debug=settings.app_debug,
    )

    app.include_router(discovery_router)
    app.include_router(adapters_router)
    app.include_router(migration_router)
    app.include_router(analysis_router)

    return app


app = create_app()
