from collections.abc import Callable

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


def commit_or_conflict(commit: Callable[[], None]) -> None:
    try:
        commit()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The request conflicts with existing data.",
        ) from error
