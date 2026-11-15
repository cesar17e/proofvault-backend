"""Ownership-aware course persistence operations."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.course import Course
from app.schemas.course import CourseCreate, CourseUpdate


class CourseNotFoundError(Exception):
    """Raised when an owner-scoped course query finds no resource."""


def create_course(
    session: Session,
    *,
    owner_id: UUID,
    payload: CourseCreate,
) -> Course:
    course = Course(
        owner_id=owner_id,
        name=payload.name,
        description=payload.description,
    )
    session.add(course)
    _commit(session)
    session.refresh(course)
    return course


def list_courses(session: Session, *, owner_id: UUID) -> Sequence[Course]:
    statement = (
        select(Course)
        .where(Course.owner_id == owner_id)
        .order_by(Course.name.asc(), Course.id.asc())
    )
    return session.scalars(statement).all()


def get_course(
    session: Session,
    *,
    owner_id: UUID,
    course_id: UUID,
) -> Course:
    statement = select(Course).where(
        Course.id == course_id,
        Course.owner_id == owner_id,
    )
    course = session.scalar(statement)
    if course is None:
        raise CourseNotFoundError
    return course


def update_course(
    session: Session,
    *,
    owner_id: UUID,
    course_id: UUID,
    payload: CourseUpdate,
) -> Course:
    course = get_course(
        session,
        owner_id=owner_id,
        course_id=course_id,
    )
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field_name, value)

    _commit(session)
    session.refresh(course)
    return course


def delete_course(
    session: Session,
    *,
    owner_id: UUID,
    course_id: UUID,
) -> None:
    course = get_course(
        session,
        owner_id=owner_id,
        course_id=course_id,
    )
    session.delete(course)
    _commit(session)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
