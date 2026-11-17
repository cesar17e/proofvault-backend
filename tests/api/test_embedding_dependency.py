from unittest.mock import MagicMock

from pydantic import SecretStr

from app.api.dependencies import embedding as embedding_dependency


def test_embedding_provider_dependency_is_configured_once(monkeypatch) -> None:
    settings = MagicMock(
        voyage_api_key=SecretStr("test-api-key"),
        voyage_embedding_model="voyage-4",
        voyage_timeout_seconds=12.5,
        voyage_max_retries=3,
    )
    provider = object()
    provider_factory = MagicMock(return_value=provider)
    monkeypatch.setattr(embedding_dependency, "get_settings", lambda: settings)
    monkeypatch.setattr(
        embedding_dependency,
        "VoyageEmbeddingProvider",
        provider_factory,
    )
    embedding_dependency.get_embedding_provider.cache_clear()

    try:
        first = embedding_dependency.get_embedding_provider()
        second = embedding_dependency.get_embedding_provider()
    finally:
        embedding_dependency.get_embedding_provider.cache_clear()

    assert first is provider
    assert second is provider
    provider_factory.assert_called_once_with(
        api_key="test-api-key",
        model="voyage-4",
        timeout_seconds=12.5,
        max_retries=3,
    )
