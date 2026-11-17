"""Authenticated mathematical-entry endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import (
    CurrentUserDependency,
    DbSessionDependency,
    EmbeddingProviderDependency,
)
from app.schemas.entry import (
    EntryCreate,
    EntryDetailResponse,
    EntryKind,
    EntryListResponse,
    EntrySummaryResponse,
    EntryUpdate,
)
from app.services import course_service, entry_service, indexing_service


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
    embedding_provider: EmbeddingProviderDependency,
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
    indexing_result = indexing_service.index_entry(
        session,
        owner_id=current_user.id,
        entry_id=entry.id,
        provider=embedding_provider,
    )
    entry.index_status = indexing_result.index_status.value
    return EntryDetailResponse.model_validate(entry)


@router.get("", response_model=EntryListResponse)
def list_entries(
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
    kind: Annotated[EntryKind | None, Query()] = None,
    course_id: Annotated[UUID | None, Query()] = None,
    topic: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=1_024)] = None,
) -> EntryListResponse:
    try:
        page = entry_service.list_entries(
            session,
            owner_id=current_user.id,
            kind=kind,
            course_id=course_id,
            topic=topic,
            limit=limit,
            cursor=cursor,
        )
    except entry_service.InvalidEntryCursorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid pagination cursor",
        ) from None

    return EntryListResponse(
        items=[
            EntrySummaryResponse.model_validate(item)
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


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


@router.patch("/{entry_id}", response_model=EntryDetailResponse)
def update_entry(
    entry_id: UUID,
    payload: EntryUpdate,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
    embedding_provider: EmbeddingProviderDependency,
) -> EntryDetailResponse:
    try:
        entry = entry_service.update_entry(
            session,
            owner_id=current_user.id,
            entry_id=entry_id,
            payload=payload,
        )
    except entry_service.EntryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        ) from None
    except course_service.CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None
    if "statement" in payload.model_fields_set:
        indexing_result = indexing_service.index_entry(
            session,
            owner_id=current_user.id,
            entry_id=entry.id,
            provider=embedding_provider,
        )
        entry.index_status = indexing_result.index_status.value
    return EntryDetailResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: UUID,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> Response:
    try:
        entry_service.delete_entry(
            session,
            owner_id=current_user.id,
            entry_id=entry_id,
        )
    except entry_service.EntryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
