"""Abstract base class that every platform adapter must implement."""

from abc import ABC, abstractmethod
from typing import Any

from app.models.responses import DiscoveredResources


class AbstractBaseAdapter(ABC):
    """Contract for all platform adapters.

    Lifecycle:
        1. discover()   — pull raw data from the source platform
        2. normalize()  — convert raw data into canonical models
        3. translate()  — map canonical models to IBM VPC target model
        4. migrate()    — execute the actual migration steps
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the canonical name of this platform (e.g. 'ibm_classic')."""

    @abstractmethod
    async def discover(self) -> dict[str, Any]:
        """Discover resources on the source platform.

        Returns:
            Raw platform-specific data as a dict.
        """

    @abstractmethod
    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Normalize raw platform data into the canonical model.

        Args:
            raw_data: Output from discover().

        Returns:
            Canonical DiscoveredResources.
        """

    @abstractmethod
    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Translate canonical model to IBM VPC target model.

        Args:
            canonical: Normalized canonical resources.

        Returns:
            Target platform representation (VPC-specific).

        Note:
            Stub in Phase 0 — full implementation in Phase 1.
        """

    @abstractmethod
    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Execute migration based on a translation plan.

        Args:
            plan: Output from translate().

        Returns:
            Migration result with status and details.

        Note:
            Stub in Phase 0 — full implementation in Phase 1.
        """
