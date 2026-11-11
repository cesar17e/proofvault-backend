"""The verified Supabase access-token contract used by ProofVault."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr


Audience = StrictStr | list[StrictStr]
Timestamp = StrictInt


class SupabaseJWTClaims(BaseModel):
    """Claims accepted after a token's signature has been verified.

    This model validates claim shape and ProofVault's user policy. It does not
    verify JWT signatures, issuers, audiences, or token lifetime by itself.
    """

    model_config = ConfigDict(extra="allow")

    iss: StrictStr
    aud: Audience
    exp: Timestamp
    iat: Timestamp
    sub: UUID
    role: Literal["authenticated"]
    aal: Literal["aal1", "aal2"]
    session_id: UUID
    email: StrictStr
    phone: StrictStr
    is_anonymous: Literal[False]

    nbf: Timestamp | None = None
    jti: StrictStr | None = None
