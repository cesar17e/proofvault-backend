from fastapi import APIRouter

from app.api.dependencies import CurrentUserDependency
from app.schemas.user import UserMeResponse


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMeResponse)
def get_current_user_profile(
    current_user: CurrentUserDependency,
) -> UserMeResponse:
    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
    )
