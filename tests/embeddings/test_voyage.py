from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from voyageai.error import RateLimitError

from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingProviderError,
    InvalidEmbeddingInputError,
    InvalidEmbeddingResponseError,
    VoyageEmbeddingProvider,
)
from app.embeddings import voyage as voyage_module


def make_provider(client: MagicMock) -> VoyageEmbeddingProvider:
    return VoyageEmbeddingProvider(
        model="voyage-4",
        timeout_seconds=10,
        max_retries=1,
        client=client,
    )


def make_vector(value: float = 0.0) -> list[float]:
    return [value] * EMBEDDING_DIMENSIONS


def test_provider_disables_sdk_retries_and_configures_timeout(monkeypatch) -> None:
    client_factory = MagicMock()
    monkeypatch.setattr(voyage_module.voyageai, "Client", client_factory)

    VoyageEmbeddingProvider(
        api_key="private-key",
        model="voyage-4",
        timeout_seconds=10,
        max_retries=1,
    )

    client_factory.assert_called_once_with(
        api_key="private-key",
        timeout=10,
        max_retries=0,
    )


def test_embed_documents_preserves_source_and_uses_document_contract() -> None:
    client = MagicMock()
    client.embed.return_value = SimpleNamespace(
        embeddings=[make_vector(0.25), make_vector(-0.5)],
        total_tokens=42,
    )
    provider = make_provider(client)
    statements = [
        "  If $a_n \\to L$, then $(a_n)$ is bounded.  ",
        "$$x^2 + y^2 = z^2$$\n",
    ]

    result = provider.embed_documents(statements)

    client.embed.assert_called_once_with(
        texts=statements,
        model="voyage-4",
        input_type="document",
        truncation=False,
        output_dtype="float",
        output_dimension=EMBEDDING_DIMENSIONS,
    )
    assert result.embeddings[0][0] == 0.25
    assert result.embeddings[1][0] == -0.5
    assert result.total_tokens == 42


@pytest.mark.parametrize(
    "documents",
    [
        [],
        ["   "],
        ["statement"] * 1_001,
    ],
)
def test_invalid_documents_are_rejected_before_provider_call(documents) -> None:
    client = MagicMock()
    provider = make_provider(client)

    with pytest.raises(InvalidEmbeddingInputError):
        provider.embed_documents(documents)

    client.embed.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(embeddings=[], total_tokens=0),
        SimpleNamespace(embeddings=[[0.0] * 1_023], total_tokens=1),
        SimpleNamespace(embeddings=[make_vector(float("nan"))], total_tokens=1),
        SimpleNamespace(embeddings=[make_vector()], total_tokens=-1),
    ],
)
def test_invalid_provider_responses_are_rejected(response) -> None:
    client = MagicMock()
    client.embed.return_value = response
    provider = make_provider(client)

    with pytest.raises(InvalidEmbeddingResponseError):
        provider.embed_documents(["A valid mathematical statement"])


def test_sdk_errors_are_translated_without_leaking_upstream_details() -> None:
    client = MagicMock()
    client.embed.side_effect = RuntimeError("private upstream request detail")
    provider = make_provider(client)

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed_documents(["A valid mathematical statement"])

    assert str(captured.value) == "Voyage embedding request failed"
    assert captured.value.error_type == "RuntimeError"
    assert "private upstream request detail" not in str(captured.value)


def test_retryable_error_uses_one_bounded_adapter_retry() -> None:
    client = MagicMock()
    client.embed.side_effect = [
        RateLimitError("private rate-limit detail"),
        SimpleNamespace(embeddings=[make_vector()], total_tokens=7),
    ]
    sleep = MagicMock()
    provider = VoyageEmbeddingProvider(
        model="voyage-4",
        timeout_seconds=10,
        max_retries=1,
        client=client,
        sleep=sleep,
    )

    result = provider.embed_documents(["A valid mathematical statement"])

    assert result.total_tokens == 7
    assert client.embed.call_count == 2
    sleep.assert_called_once_with(1)
