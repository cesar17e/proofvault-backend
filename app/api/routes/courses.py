"""Authenticated course CRUD endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentUserDependency, DbSessionDependency
from app.schemas.course import (
    CourseCreate,
    CourseListResponse,
    CourseResponse,
    CourseUpdate,
)
from app.services import course_service


router = APIRouter(prefix="/courses", tags=["courses"])


@router.post(
    "",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course(
    payload: CourseCreate,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> CourseResponse:
    course = course_service.create_course(
        session,
        owner_id=current_user.id,
        payload=payload,
    )
    return CourseResponse.model_validate(course)


@router.get("", response_model=CourseListResponse)
def list_courses(
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> CourseListResponse:
    courses = course_service.list_courses(
        session,
        owner_id=current_user.id,
    )
    return CourseListResponse(
        items=[CourseResponse.model_validate(course) for course in courses]
    )


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: UUID,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> CourseResponse:
    try:
        course = course_service.get_course(
            session,
            owner_id=current_user.id,
            course_id=course_id,
        )
    except course_service.CourseNotFoundError:
        raise _course_not_found() from None
    return CourseResponse.model_validate(course)


@router.patch("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: UUID,
    payload: CourseUpdate,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> CourseResponse:
    try:
        course = course_service.update_course(
            session,
            owner_id=current_user.id,
            course_id=course_id,
            payload=payload,
        )
    except course_service.CourseNotFoundError:
        raise _course_not_found() from None
    return CourseResponse.model_validate(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: UUID,
    current_user: CurrentUserDependency,
    session: DbSessionDependency,
) -> Response:
    try:
        course_service.delete_course(
            session,
            owner_id=current_user.id,
            course_id=course_id,
        )
    except course_service.CourseNotFoundError:
        raise _course_not_found() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _course_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Course not found",
    )
