"""Discovery API routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_discovery_service
from app.core.exceptions import AdapterDiscoveryError, AdapterNotFoundError
from app.models.responses import DiscoveryResponse, ErrorResponse
from app.services.discovery import DiscoveryService

router = APIRouter(prefix="/discover", tags=["discovery"])


@router.post(
    "/{adapter_name}",
    response_model=DiscoveryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Adapter not found"},
        500: {"model": ErrorResponse, "description": "Discovery failed"},
    },
)
async def discover(
    adapter_name: str,
    service: DiscoveryService = Depends(get_discovery_service),
) -> DiscoveryResponse:
    """Trigger discovery for a source platform adapter.

    Returns both the raw platform data and the normalized canonical model.
    """
    try:
        return await service.run(adapter_name)
    except AdapterNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except AdapterDiscoveryError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
