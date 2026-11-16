from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "proofvault-api"
    app_env: Literal["development", "test", "production"] = "development"

    database_url: SecretStr
    supabase_url: AnyHttpUrl
    supabase_jwt_algorithm: Literal["ES256"] = "ES256"
    supabase_jwt_audience: Literal["authenticated"] = "authenticated"

    voyage_api_key: SecretStr
    voyage_embedding_model: str = "voyage-4"
    voyage_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    voyage_max_retries: int = Field(default=1, ge=0, le=3)

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.query is not None or value.fragment is not None:
            raise ValueError("Supabase URL must not contain a query or fragment")

        if value.path not in (None, "/"):
            raise ValueError("Supabase URL must not contain a path")

        return value

    @field_validator("voyage_api_key")
    @classmethod
    def validate_voyage_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Voyage API key must not be blank")
        return value

    @field_validator("voyage_embedding_model")
    @classmethod
    def validate_voyage_embedding_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("Voyage embedding model must not be blank")
        return model

    @property
    def supabase_jwt_issuer(self) -> str:
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_jwt_issuer}/.well-known/jwks.json"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
