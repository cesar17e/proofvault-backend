"""Voyage AI implementation of the embedding provider contract."""

import math
import time
from collections.abc import Sequence
from numbers import Real
from typing import Any, Callable, Protocol

import voyageai
from voyageai.error import (
    APIConnectionError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    Timeout,
)

from app.embeddings.base import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBatch,
    EmbeddingProviderError,
    InvalidEmbeddingInputError,
    InvalidEmbeddingResponseError,
)


MAX_EMBEDDING_BATCH_SIZE = 1_000
_RETRYABLE_ERRORS = (
    APIConnectionError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    Timeout,
)


class _VoyageClient(Protocol):
    def embed(self, **kwargs: Any) -> Any:
        """Return a Voyage embeddings response."""


class VoyageEmbeddingProvider:
    """Generate validated document embeddings through Voyage AI."""

    name = "voyage"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        api_key: str | None = None,
        client: _VoyageClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("Voyage embedding model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("Voyage timeout must be greater than zero")
        if max_retries < 0:
            raise ValueError("Voyage maximum retries must not be negative")
        if client is None and (api_key is None or not api_key.strip()):
            raise ValueError("Voyage API key must not be blank")

        self.model = normalized_model
        self._max_retries = max_retries
        self._sleep = sleep
        if client is None:
            # Keep retry ownership in this adapter. In voyageai 0.5.0 the SDK
            # treats max_retries as total attempts, despite the public name.
            self._client = voyageai.Client(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=0,
            )
        else:
            self._client = client

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        source_texts = _validate_inputs(texts)

        response = self._request_documents(source_texts)

        return _validate_response(response, expected_count=len(source_texts))

    def _request_documents(self, source_texts: list[str]) -> Any:
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.embed(
                    texts=source_texts,
                    model=self.model,
                    input_type="document",
                    truncation=False,
                    output_dtype="float",
                    output_dimension=self.dimensions,
                )
            except _RETRYABLE_ERRORS as error:
                if attempt == self._max_retries:
                    raise _safe_provider_error(error) from None
                self._sleep(min(2**attempt, 4))
            except Exception as error:
                raise _safe_provider_error(error) from None

        raise AssertionError("unreachable embedding retry state")


def _validate_inputs(texts: Sequence[str]) -> list[str]:
    source_texts = list(texts)
    if not source_texts:
        raise InvalidEmbeddingInputError(
            "At least one document is required for embedding"
        )
    if len(source_texts) > MAX_EMBEDDING_BATCH_SIZE:
        raise InvalidEmbeddingInputError(
            f"Embedding batches may contain at most {MAX_EMBEDDING_BATCH_SIZE} documents"
        )
    if any(not isinstance(text, str) or not text.strip() for text in source_texts):
        raise InvalidEmbeddingInputError(
            "Embedding documents must be non-blank strings"
        )
    return source_texts


def _validate_response(response: Any, *, expected_count: int) -> EmbeddingBatch:
    raw_embeddings = getattr(response, "embeddings", None)
    if not _is_sequence(raw_embeddings) or len(raw_embeddings) != expected_count:
        raise InvalidEmbeddingResponseError(
            "Voyage returned an unexpected number of embeddings"
        )

    embeddings = tuple(_validate_vector(vector) for vector in raw_embeddings)
    total_tokens = getattr(response, "total_tokens", None)
    if total_tokens is not None and (
        isinstance(total_tokens, bool)
        or not isinstance(total_tokens, int)
        or total_tokens < 0
    ):
        raise InvalidEmbeddingResponseError(
            "Voyage returned an invalid token count"
        )

    return EmbeddingBatch(
        embeddings=embeddings,
        total_tokens=total_tokens,
    )


def _validate_vector(vector: Any) -> tuple[float, ...]:
    if not _is_sequence(vector) or len(vector) != EMBEDDING_DIMENSIONS:
        raise InvalidEmbeddingResponseError(
            f"Voyage embeddings must contain {EMBEDDING_DIMENSIONS} values"
        )

    normalized: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise InvalidEmbeddingResponseError(
                "Voyage embeddings must contain only numeric values"
            )
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise InvalidEmbeddingResponseError(
                "Voyage embeddings must contain only finite values"
            )
        normalized.append(numeric_value)

    return tuple(normalized)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _safe_provider_error(error: Exception) -> EmbeddingProviderError:
    return EmbeddingProviderError(
        "Voyage embedding request failed",
        error_type=type(error).__name__,
    )
