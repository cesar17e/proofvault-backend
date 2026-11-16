import pytest
from pydantic import ValidationError

from app.core.config import Settings


BASE_SETTINGS = {
    "_env_file": None,
    "database_url": "postgresql+psycopg://user:password@localhost/proofvault",
    "supabase_url": "https://project-ref.supabase.co",
    "voyage_api_key": "private-voyage-key",
}


def test_voyage_settings_use_safe_defaults_and_mask_api_key() -> None:
    settings = Settings(**BASE_SETTINGS)

    assert settings.voyage_embedding_model == "voyage-4"
    assert settings.voyage_timeout_seconds == 10
    assert settings.voyage_max_retries == 1
    assert "private-voyage-key" not in repr(settings)


@pytest.mark.parametrize(
    "override",
    [
        {"voyage_api_key": "   "},
        {"voyage_embedding_model": "   "},
        {"voyage_timeout_seconds": 0},
        {"voyage_timeout_seconds": 61},
        {"voyage_max_retries": -1},
        {"voyage_max_retries": 4},
    ],
)
def test_voyage_settings_reject_unsafe_values(override: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**(BASE_SETTINGS | override))
