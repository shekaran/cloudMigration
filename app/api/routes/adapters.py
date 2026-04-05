"""Adapter management API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.registry import AdapterRegistry
from app.api.dependencies import get_adapter_registry

router = APIRouter(prefix="/adapters", tags=["adapters"])


class AdapterListResponse(BaseModel):
    """Response listing all registered adapters."""

    adapters: list[str] = Field(description="Names of registered adapters")
    count: int = Field(description="Number of registered adapters")


@router.get("", response_model=AdapterListResponse)
async def list_adapters(
    registry: AdapterRegistry = Depends(get_adapter_registry),
) -> AdapterListResponse:
    """Return all registered adapter names."""
    names = registry.registered_adapters
    return AdapterListResponse(adapters=names, count=len(names))
