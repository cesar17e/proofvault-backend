"""Trusted application identity created from verified JWT claims."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.auth.claims import SupabaseJWTClaims


class CurrentUser(BaseModel):
    """The minimal authenticated identity exposed to application code."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str | None
    role: Literal["authenticated"]
    session_id: UUID
    aal: Literal["aal1", "aal2"]

    @classmethod
    def from_claims(cls, claims: SupabaseJWTClaims) -> Self:
        return cls(
            id=claims.sub,
            email=claims.email or None,
            role=claims.role,
            session_id=claims.session_id,
            aal=claims.aal,
        )
