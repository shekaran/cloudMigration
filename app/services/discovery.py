"""Discovery service — orchestrates adapter discovery and normalization."""

import structlog

from app.adapters.registry import AdapterRegistry
from app.core.exceptions import AdapterDiscoveryError
from app.models.responses import DiscoveryResponse

logger = structlog.get_logger(__name__)


class DiscoveryService:
    """Runs discovery against a named adapter and returns both raw and normalized data."""

    def __init__(self, registry: AdapterRegistry) -> None:
        self._registry = registry

    async def run(self, adapter_name: str) -> DiscoveryResponse:
        """Execute discovery for the given adapter.

        Args:
            adapter_name: Registered adapter name (e.g. 'ibm_classic').

        Returns:
            DiscoveryResponse with raw data and normalized canonical resources.

        Raises:
            AdapterNotFoundError: If the adapter is not registered.
            AdapterDiscoveryError: If discovery or normalization fails.
        """
        logger.info("discovery_service_started", adapter=adapter_name)

        adapter = self._registry.get_adapter(adapter_name)

        try:
            raw_data = await adapter.discover()
        except Exception as exc:
            raise AdapterDiscoveryError(adapter_name, str(exc)) from exc

        try:
            normalized = adapter.normalize(raw_data)
        except Exception as exc:
            raise AdapterDiscoveryError(
                adapter_name, f"Normalization failed: {exc}"
            ) from exc

        response = DiscoveryResponse(
            adapter=adapter_name,
            raw_data=raw_data,
            normalized=normalized,
            resource_count=normalized.resource_count,
        )

        logger.info(
            "discovery_service_completed",
            adapter=adapter_name,
            resource_count=normalized.resource_count,
        )
        return response
