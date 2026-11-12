"""FastAPI dependencies for Supabase bearer authentication."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import (
    CurrentUser,
    InvalidAccessTokenError,
    JWKSUnavailableError,
    SupabaseJWTVerifier,
)
from app.core.config import get_settings


bearer_scheme = HTTPBearer(
    scheme_name="SupabaseAccessToken",
    description="Supabase Auth user access token",
    auto_error=False,
)


@lru_cache
def get_jwt_verifier() -> SupabaseJWTVerifier:
    """Create one cached verifier and JWKS client per application process."""
    settings = get_settings()
    return SupabaseJWTVerifier(
        issuer=settings.supabase_jwt_issuer,
        audience=settings.supabase_jwt_audience,
        jwks_url=settings.supabase_jwks_url,
        algorithm=settings.supabase_jwt_algorithm,
    )


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    verifier: Annotated[
        SupabaseJWTVerifier,
        Depends(get_jwt_verifier),
    ],
) -> CurrentUser:
    """Authenticate a bearer token and return its trusted user identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        claims = verifier.verify(credentials.credentials)
    except InvalidAccessTokenError:
        raise _unauthorized() from None
    except JWKSUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from None

    return CurrentUser.from_claims(claims)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]
