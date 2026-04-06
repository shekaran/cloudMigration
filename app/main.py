"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI

from app.adapters.registry import AdapterRegistry
from app.api.dependencies import configure_services
from app.api.routes.adapters import router as adapters_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.migration import router as migration_router
from app.core.config import get_settings
from app.services.discovery import DiscoveryService
from app.services.orchestrator import MigrationOrchestrator
from app.services.translation import TranslationService
from app.terraform.generator import TerraformGenerator
from app.utils.logging import setup_logging

logger = structlog.get_logger(__name__)

# Default adapter config — maps name → dotted class path.
# New adapters only need an entry here (or rely on auto-discovery).
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
    orchestrator = MigrationOrchestrator(
        registry=registry,
        translation_service=translation_service,
        terraform_generator=terraform_generator,
    )

    # Wire into FastAPI dependency injection
    configure_services(registry, discovery_service, translation_service, orchestrator)

    yield

    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Migration Orchestration Engine",
        description="Multi-Platform Migration Orchestration Engine to IBM Cloud VPC",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app_debug,
    )

    app.include_router(discovery_router)
    app.include_router(adapters_router)
    app.include_router(migration_router)

    return app


app = create_app()
