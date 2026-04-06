"""Temporal worker — registers workflows and activities, connects to Temporal server."""

import asyncio

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows.activities import MigrationActivities
from app.workflows.migration_workflow import MigrationWorkflow

logger = structlog.get_logger(__name__)

TASK_QUEUE = "migration-task-queue"


async def create_worker(
    activities: MigrationActivities,
    temporal_address: str = "localhost:7233",
) -> Worker:
    """Create and return a Temporal worker (does not start it).

    The caller is responsible for running the worker:
        worker = await create_worker(activities)
        await worker.run()
    """
    client = await Client.connect(temporal_address)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[MigrationWorkflow],
        activities=[
            activities.discover,
            activities.normalize,
            activities.validate,
            activities.analyze,
            activities.translate,
            activities.migrate_data,
        ],
    )

    logger.info(
        "temporal_worker_created",
        task_queue=TASK_QUEUE,
        address=temporal_address,
    )
    return worker


async def run_worker(
    activities: MigrationActivities,
    temporal_address: str = "localhost:7233",
) -> None:
    """Connect to Temporal and run the worker until interrupted."""
    worker = await create_worker(activities, temporal_address)
    logger.info("temporal_worker_starting", task_queue=TASK_QUEUE)
    await worker.run()
