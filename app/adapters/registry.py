"""Adapter registry — config-driven registration with auto-discovery support."""

import importlib
import inspect
import pkgutil
from typing import Any

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.core.exceptions import AdapterNotFoundError, AdapterRegistrationError

logger = structlog.get_logger(__name__)


class AdapterRegistry:
    """Central registry for platform adapters.

    Supports two registration modes:
        1. Config-based: explicit name → dotted-path mapping.
        2. Auto-discovery: scan adapter sub-packages for AbstractBaseAdapter subclasses.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, type[AbstractBaseAdapter]] = {}

    @property
    def registered_adapters(self) -> list[str]:
        """Return names of all registered adapters."""
        return list(self._adapters.keys())

    def register(self, name: str, adapter_cls: type[AbstractBaseAdapter]) -> None:
        """Register an adapter class under the given name.

        Args:
            name: Lookup key (e.g. 'ibm_classic').
            adapter_cls: A concrete subclass of AbstractBaseAdapter.

        Raises:
            AdapterRegistrationError: If adapter_cls is not a valid subclass.
        """
        if not (isinstance(adapter_cls, type) and issubclass(adapter_cls, AbstractBaseAdapter)):
            raise AdapterRegistrationError(
                f"Cannot register '{name}': {adapter_cls} is not a subclass of AbstractBaseAdapter"
            )
        self._adapters[name] = adapter_cls
        logger.info("adapter_registered", adapter=name, cls=adapter_cls.__qualname__)

    def register_from_config(self, config: dict[str, str]) -> None:
        """Register adapters from a name → dotted-path mapping.

        Args:
            config: e.g. {"ibm_classic": "app.adapters.ibm_classic.adapter.IBMClassicAdapter"}
        """
        for name, dotted_path in config.items():
            module_path, class_name = dotted_path.rsplit(".", 1)
            try:
                module = importlib.import_module(module_path)
                adapter_cls = getattr(module, class_name)
            except (ImportError, AttributeError) as exc:
                raise AdapterRegistrationError(
                    f"Failed to load adapter '{name}' from '{dotted_path}': {exc}"
                ) from exc
            self.register(name, adapter_cls)

    def auto_discover(self, package_path: str = "app.adapters") -> None:
        """Scan sub-packages of the adapter package for AbstractBaseAdapter subclasses.

        Each sub-package (e.g. app.adapters.ibm_classic) is imported, and any
        concrete class that inherits from AbstractBaseAdapter is registered
        using its `platform_name` property.

        Args:
            package_path: Dotted path to the adapters package.
        """
        package = importlib.import_module(package_path)
        package_dir = getattr(package, "__path__", None)
        if package_dir is None:
            return

        for importer, module_name, is_pkg in pkgutil.iter_modules(package_dir):
            if not is_pkg:
                continue

            full_module = f"{package_path}.{module_name}"
            try:
                sub_package = importlib.import_module(full_module)
            except ImportError as exc:
                logger.warning("adapter_auto_discover_skip", module=full_module, error=str(exc))
                continue

            self._scan_module_for_adapters(sub_package, full_module)

    def _scan_module_for_adapters(self, package: Any, package_path: str) -> None:
        """Recursively scan a package's modules for adapter classes."""
        for importer, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
            full_module = f"{package_path}.{module_name}"
            try:
                module = importlib.import_module(full_module)
            except ImportError:
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, AbstractBaseAdapter)
                    and obj is not AbstractBaseAdapter
                    and not inspect.isabstract(obj)
                ):
                    try:
                        instance = obj()
                        name = instance.platform_name
                    except Exception:
                        continue
                    if name not in self._adapters:
                        self.register(name, obj)

    def get_adapter(self, name: str) -> AbstractBaseAdapter:
        """Instantiate and return an adapter by name.

        Args:
            name: Registered adapter name.

        Returns:
            An instance of the requested adapter.

        Raises:
            AdapterNotFoundError: If no adapter is registered under that name.
        """
        adapter_cls = self._adapters.get(name)
        if adapter_cls is None:
            raise AdapterNotFoundError(name)
        return adapter_cls()
