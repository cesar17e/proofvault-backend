"""FastAPI database-session dependency.

The session module is imported only when the dependency executes. This keeps
route imports side-effect free and allows tests to replace the dependency
without loading runtime database configuration.
"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session


def get_db() -> Generator[Session, None, None]:
    from app.db.session import get_db as get_session

    yield from get_session()


DbSessionDependency = Annotated[Session, Depends(get_db)]
