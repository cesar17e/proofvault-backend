"""Embedding-provider dependency wiring."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.embeddings import EmbeddingProvider, VoyageEmbeddingProvider


@lru_cache
def get_embedding_provider() -> VoyageEmbeddingProvider:
    """Build one reusable provider from validated application settings."""
    settings = get_settings()
    return VoyageEmbeddingProvider(
        api_key=settings.voyage_api_key.get_secret_value(),
        model=settings.voyage_embedding_model,
        timeout_seconds=settings.voyage_timeout_seconds,
        max_retries=settings.voyage_max_retries,
    )


EmbeddingProviderDependency = Annotated[
    EmbeddingProvider,
    Depends(get_embedding_provider),
]
