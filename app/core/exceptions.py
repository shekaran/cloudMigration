"""Custom exception hierarchy for the migration engine."""


class MigrationEngineError(Exception):
    """Base exception for all migration engine errors."""


class AdapterNotFoundError(MigrationEngineError):
    """Raised when a requested adapter is not registered."""

    def __init__(self, adapter_name: str) -> None:
        self.adapter_name = adapter_name
        super().__init__(f"Adapter not found: '{adapter_name}'")


class AdapterDiscoveryError(MigrationEngineError):
    """Raised when an adapter fails during discovery."""

    def __init__(self, adapter_name: str, reason: str) -> None:
        self.adapter_name = adapter_name
        self.reason = reason
        super().__init__(f"Discovery failed for '{adapter_name}': {reason}")


class AdapterRegistrationError(MigrationEngineError):
    """Raised when adapter registration or auto-discovery fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Adapter registration failed: {reason}")
