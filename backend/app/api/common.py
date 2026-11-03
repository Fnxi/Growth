from collections.abc import Callable

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


def _or_conflict(operation: Callable[[], None], rollback: Callable[[], None] | None = None) -> None:
    try:
        operation()
    except IntegrityError as error:
        if rollback:
            rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The request conflicts with existing data.",
        ) from error


def flush_or_conflict(flush: Callable[[], None], rollback: Callable[[], None]) -> None:
    _or_conflict(flush, rollback)


def commit_or_conflict(commit: Callable[[], None], rollback: Callable[[], None] | None = None) -> None:
    _or_conflict(commit, rollback)
