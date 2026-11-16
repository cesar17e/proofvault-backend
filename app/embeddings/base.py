"""Provider-independent embedding contracts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


EMBEDDING_DIMENSIONS = 1_024


class EmbeddingError(Exception):
    """Base error for embedding operations."""


class InvalidEmbeddingInputError(EmbeddingError, ValueError):
    """Raised before a malformed embedding request reaches a provider."""


class EmbeddingProviderError(EmbeddingError):
    """Safe application error for an external provider failure."""

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type


class InvalidEmbeddingResponseError(EmbeddingProviderError):
    """Raised when a provider returns an unusable embedding response."""


@dataclass(frozen=True)
class EmbeddingBatch:
    """Validated embeddings in the same order as their source texts."""

    embeddings: tuple[tuple[float, ...], ...]
    total_tokens: int | None


class EmbeddingProvider(Protocol):
    """Interface consumed by indexing now and semantic search later."""

    name: str
    model: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed stored content for later retrieval."""

