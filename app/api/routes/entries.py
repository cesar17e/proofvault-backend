"""Authenticated mathematical-entry endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUserDependency, DbSessionDependency
from app.schemas.entry import EntryCreate, EntryDetailResponse
from app.services import course_service, entry_service


router = APIRouter(prefix="/entries", tags=["entries"])


@router.post(
    "",
    response_model=EntryDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_entry(
    payload: EntryCreate,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> EntryDetailResponse:
    try:
        entry = entry_service.create_entry(
            session,
            owner_id=current_user.id,
            payload=payload,
        )
    except course_service.CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None
    return EntryDetailResponse.model_validate(entry)


@router.get("/{entry_id}", response_model=EntryDetailResponse)
def get_entry(
    entry_id: UUID,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> EntryDetailResponse:
    try:
        entry = entry_service.get_entry(
            session,
            owner_id=current_user.id,
            entry_id=entry_id,
        )
    except entry_service.EntryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        ) from None
    return EntryDetailResponse.model_validate(entry)
