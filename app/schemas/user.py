from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserMeResponse(BaseModel):
    """Public identity returned for the authenticated Supabase user."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str | None
