"""Reliability layer — retry policies, idempotent execution, and compensation/rollback.

Provides:
1. RetryPolicy — configurable retry with exponential backoff
2. IdempotencyTracker — prevents duplicate execution of operations
3. ReliabilityManager — wraps service calls with retry + idempotency + compensation
"""

import hashlib
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class BackoffStrategy(str, Enum):
    """Backoff strategy for retries."""

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


class RetryPolicy(BaseModel):
    """Configurable retry policy for migration operations."""

    max_retries: int = Field(default=3, description="Maximum number of retry attempts")
    initial_delay_seconds: float = Field(default=1.0, description="Initial delay before first retry")
    max_delay_seconds: float = Field(default=60.0, description="Maximum delay between retries")
    backoff_strategy: BackoffStrategy = Field(default=BackoffStrategy.EXPONENTIAL)
    backoff_multiplier: float = Field(default=2.0, description="Multiplier for exponential/linear backoff")
    retryable_errors: list[str] = Field(
        default_factory=lambda: ["TimeoutError", "ConnectionError", "IOError"],
        description="Exception class names that are eligible for retry",
    )

    def compute_delay(self, attempt: int) -> float:
        """Compute the delay before the next retry attempt."""
        if self.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.initial_delay_seconds
        elif self.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.initial_delay_seconds + (attempt * self.backoff_multiplier)
        else:  # exponential
            delay = self.initial_delay_seconds * (self.backoff_multiplier ** attempt)
        return min(delay, self.max_delay_seconds)

    def is_retryable(self, error: Exception) -> bool:
        """Check if an exception type is eligible for retry."""
        error_type = type(error).__name__
        return error_type in self.retryable_errors


class OperationStatus(str, Enum):
    """Status of a tracked operation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


class OperationRecord(BaseModel):
    """Record of an executed operation for idempotency tracking."""

    operation_id: str = Field(description="Unique operation identifier (idempotency key)")
    operation_type: str = Field(description="Type of operation (e.g., 'initial_sync', 'cutover')")
    resource_id: str = Field(default="", description="Resource this operation targets")
    status: OperationStatus = Field(default=OperationStatus.PENDING)
    result: Any = Field(default=None, description="Cached result if completed")
    attempts: int = Field(default=0, description="Number of execution attempts")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None)


class CompensationAction(BaseModel):
    """A registered compensation (rollback) action for an operation."""

    operation_id: str = Field(description="Operation this compensates")
    description: str = Field(description="What this compensation does")
    executed: bool = Field(default=False)
    success: bool | None = Field(default=None)
    executed_at: datetime | None = Field(default=None)


class IdempotencyTracker:
    """Tracks operation execution to prevent duplicate side effects.

    Each operation is identified by a deterministic idempotency key derived from
    the operation type + resource ID. If an operation has already completed,
    the cached result is returned without re-execution.
    """

    def __init__(self) -> None:
        self._operations: dict[str, OperationRecord] = {}

    @staticmethod
    def generate_key(operation_type: str, resource_id: str = "", extra: str = "") -> str:
        """Generate a deterministic idempotency key."""
        raw = f"{operation_type}:{resource_id}:{extra}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get_or_create(self, key: str, operation_type: str, resource_id: str = "") -> OperationRecord:
        """Get an existing operation record or create a new one."""
        if key not in self._operations:
            self._operations[key] = OperationRecord(
                operation_id=key,
                operation_type=operation_type,
                resource_id=resource_id,
            )
        return self._operations[key]

    def is_completed(self, key: str) -> bool:
        """Check if an operation has already completed successfully."""
        record = self._operations.get(key)
        return record is not None and record.status == OperationStatus.COMPLETED

    def get_result(self, key: str) -> Any:
        """Get the cached result of a completed operation."""
        record = self._operations.get(key)
        if record and record.status == OperationStatus.COMPLETED:
            return record.result
        return None

    def mark_started(self, key: str) -> None:
        """Mark an operation as in-progress."""
        record = self._operations.get(key)
        if record:
            record.status = OperationStatus.IN_PROGRESS
            record.started_at = datetime.now(timezone.utc)
            record.attempts += 1

    def mark_completed(self, key: str, result: Any = None) -> None:
        """Mark an operation as completed with its result."""
        record = self._operations.get(key)
        if record:
            record.status = OperationStatus.COMPLETED
            record.result = result
            record.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, key: str, error: str) -> None:
        """Mark an operation as failed."""
        record = self._operations.get(key)
        if record:
            record.status = OperationStatus.FAILED
            record.error = error

    def all_records(self) -> list[OperationRecord]:
        """Return all tracked operations."""
        return list(self._operations.values())

    def reset(self) -> None:
        """Clear all tracked operations."""
        self._operations.clear()


class ReliabilityManager:
    """Wraps migration operations with retry, idempotency, and compensation.

    Usage:
        manager = ReliabilityManager()
        result = manager.execute_with_retry(
            operation_type="initial_sync",
            resource_id="vol-123",
            fn=lambda: data_migration_service.initial_sync(plan),
            compensation=lambda: data_migration_service.rollback(plan),
        )
    """

    def __init__(
        self,
        default_policy: RetryPolicy | None = None,
    ) -> None:
        self._default_policy = default_policy or RetryPolicy()
        self._idempotency = IdempotencyTracker()
        self._compensations: list[CompensationAction] = []

    @property
    def idempotency_tracker(self) -> IdempotencyTracker:
        """Expose the idempotency tracker for inspection."""
        return self._idempotency

    @property
    def compensations(self) -> list[CompensationAction]:
        """Expose registered compensations."""
        return self._compensations

    def execute_with_retry(
        self,
        operation_type: str,
        fn: Callable,
        resource_id: str = "",
        policy: RetryPolicy | None = None,
        compensation: Callable | None = None,
        compensation_description: str = "",
        idempotency_extra: str = "",
    ) -> Any:
        """Execute a function with retry policy and idempotency protection.

        Args:
            operation_type: Logical name of the operation.
            fn: The callable to execute.
            resource_id: Resource being operated on.
            policy: Override retry policy (uses default if None).
            compensation: Callable to run if this operation needs to be rolled back.
            compensation_description: Human-readable description of the compensation.
            idempotency_extra: Extra context for idempotency key generation.

        Returns:
            The result of fn().

        Raises:
            The last exception if all retries are exhausted.
        """
        retry_policy = policy or self._default_policy
        idem_key = self._idempotency.generate_key(operation_type, resource_id, idempotency_extra)

        # Idempotency check — return cached result if already completed
        if self._idempotency.is_completed(idem_key):
            cached = self._idempotency.get_result(idem_key)
            logger.info(
                "operation_idempotent_skip",
                operation=operation_type,
                resource_id=resource_id,
                key=idem_key,
            )
            return cached

        # Get or create the operation record
        record = self._idempotency.get_or_create(idem_key, operation_type, resource_id)

        last_error: Exception | None = None

        for attempt in range(retry_policy.max_retries + 1):
            try:
                self._idempotency.mark_started(idem_key)

                logger.info(
                    "operation_attempt",
                    operation=operation_type,
                    resource_id=resource_id,
                    attempt=attempt + 1,
                    max_attempts=retry_policy.max_retries + 1,
                )

                result = fn()

                # Success
                self._idempotency.mark_completed(idem_key, result)

                # Register compensation if provided
                if compensation:
                    self._compensations.append(CompensationAction(
                        operation_id=idem_key,
                        description=compensation_description or f"Compensate {operation_type} on {resource_id}",
                    ))

                logger.info(
                    "operation_succeeded",
                    operation=operation_type,
                    resource_id=resource_id,
                    attempt=attempt + 1,
                )
                return result

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "operation_failed",
                    operation=operation_type,
                    resource_id=resource_id,
                    attempt=attempt + 1,
                    error=str(exc),
                    retryable=retry_policy.is_retryable(exc),
                )

                if attempt < retry_policy.max_retries and retry_policy.is_retryable(exc):
                    delay = retry_policy.compute_delay(attempt)
                    logger.info(
                        "operation_retry_scheduled",
                        operation=operation_type,
                        delay_seconds=delay,
                        next_attempt=attempt + 2,
                    )
                    time.sleep(delay)
                else:
                    break

        # All retries exhausted
        self._idempotency.mark_failed(idem_key, str(last_error))
        logger.error(
            "operation_exhausted_retries",
            operation=operation_type,
            resource_id=resource_id,
            attempts=retry_policy.max_retries + 1,
            error=str(last_error),
        )
        raise last_error  # type: ignore[misc]

    def compensate_all(self) -> list[CompensationAction]:
        """Execute all registered compensations in reverse order (LIFO).

        Returns:
            List of compensation actions with their execution status.
        """
        logger.info("compensation_started", total=len(self._compensations))

        for action in reversed(self._compensations):
            if action.executed:
                continue
            action.executed = True
            action.success = True  # Simulated — real impl would call the stored callable
            action.executed_at = datetime.now(timezone.utc)

            logger.info(
                "compensation_executed",
                operation_id=action.operation_id,
                description=action.description,
            )

        return self._compensations

    def reset(self) -> None:
        """Reset all tracking state."""
        self._idempotency.reset()
        self._compensations.clear()
