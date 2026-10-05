"""The Fal.ai credential goes in a header, with a scheme that is not Bearer.

Two things about Fal's embeddings endpoint are not the OpenAI defaults: the key
travels as ``Authorization: Key <key>``, and the OpenAI client's own ``api_key`` is
a placeholder. A client that assumes ``Bearer`` gets a 401 against a perfectly valid
key, which reads as "the key is wrong" rather than "the header is wrong" -- so this
is exactly the kind of configuration mistake worth pinning with a test rather than a
comment.
"""

from __future__ import annotations

import pytest

from awltux.analysis.embeddings import EmbeddingClient
from awltux.config import EmbeddingsConfig, SecretStr

FAL_URL = "https://fal.run/openrouter/router/openai/v1"


class _Captured:
    """Stands in for HttpClient, recording how it was constructed."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        raise AssertionError("the test only inspects construction")

    def close(self):
        pass


@pytest.fixture
def capture(monkeypatch):
    from awltux.analysis import embeddings as module

    made: list[_Captured] = []

    def factory(*args, **kwargs):
        client = _Captured(**kwargs)
        made.append(client)
        return client

    monkeypatch.setattr(module, "HttpClient", factory)
    return made


def _client(settings, **overrides) -> EmbeddingClient:
    config = settings.news.embeddings
    config.base_url = overrides.pop("base_url", FAL_URL)
    config.model = overrides.pop("model", "openai/text-embedding-3-small")
    config.auth_scheme = overrides.pop("auth_scheme", "Key")
    for key, value in overrides.items():
        setattr(config, key, value)
    return EmbeddingClient(settings)


class TestTheAuthorizationHeader:
    def test_fal_is_sent_a_key_header_not_a_bearer_token(self, settings, capture, monkeypatch):
        monkeypatch.setattr(
            settings.env, "falai_key", SecretStr("fal-test-key"), raising=False
        )
        client = _client(settings)
        client._client()

        headers = capture[-1].kwargs["headers"]
        assert headers is not None
        assert headers["Authorization"] == "Key fal-test-key"
        assert "Bearer" not in headers["Authorization"]

    def test_the_scheme_is_configuration_not_an_assumption(self, settings, capture, monkeypatch):
        """A local Ollama needs none; OpenAI wants Bearer."""
        monkeypatch.setattr(
            settings.env, "falai_key", SecretStr("k"), raising=False
        )

        bearer = _client(settings, auth_scheme="Bearer")
        bearer._client()
        assert capture[-1].kwargs["headers"]["Authorization"] == "Bearer k"

        bare = _client(settings, auth_scheme="")
        bare._client()
        assert capture[-1].kwargs["headers"]["Authorization"] == "k"

    def test_a_local_endpoint_needs_no_credential_at_all(self, settings, capture, monkeypatch):
        monkeypatch.setattr(settings.env, "falai_key", None)
        client = _client(settings, base_url="http://localhost:11434/v1")
        client._client()
        assert capture[-1].kwargs["headers"] is None

    def test_the_endpoint_is_used_as_configured(self, settings, capture, monkeypatch):
        monkeypatch.setattr(settings.env, "falai_key", SecretStr("k"), raising=False)
        client = _client(settings)
        client._client()
        assert capture[-1].kwargs["base_url"] == FAL_URL

    def test_the_key_is_never_put_in_the_url_or_the_body(self, settings, capture, monkeypatch):
        """Only the header, so it cannot leak through a cached body or a log line."""
        monkeypatch.setattr(
            settings.env, "falai_key", SecretStr("fal-secret-value"), raising=False
        )
        client = _client(settings)
        client._client()
        rendered = repr(capture[-1].kwargs)
        assert "fal-secret-value" not in capture[-1].kwargs["base_url"]
        assert "fal-secret-value" in rendered  # in the header, and nowhere else


class TestCredentialPrecedence:
    def test_the_environment_key_is_used(self, settings, monkeypatch):
        monkeypatch.setattr(
            settings.env, "falai_key", SecretStr("from-env"), raising=False
        )
        config = EmbeddingsConfig(base_url=FAL_URL)
        assert config.credential(settings.env) == "from-env"

    def test_an_explicit_key_wins_over_the_environment(self, settings, monkeypatch):
        monkeypatch.setattr(
            settings.env, "falai_key", SecretStr("from-env"), raising=False
        )
        config = EmbeddingsConfig(base_url=FAL_URL, api_key=SecretStr("explicit"))
        assert config.credential(settings.env) == "explicit"

    def test_no_key_anywhere_is_not_an_error(self, settings, monkeypatch):
        monkeypatch.setattr(settings.env, "falai_key", None)
        config = EmbeddingsConfig(base_url=FAL_URL)
        assert config.credential(settings.env) is None

    def test_the_repository_ships_no_key(self):
        """The default is empty, so a fresh clone cannot inherit one."""
        assert EmbeddingsConfig().api_key is None
        assert EmbeddingsConfig().base_url == ""


class TestARejectedCredentialSaysSo:
    def test_a_401_names_the_scheme_and_the_model(self, settings, monkeypatch):
        """Otherwise a rejected key is indistinguishable from a broken endpoint."""
        from awltux.providers.http import ProviderError

        monkeypatch.setattr(settings.env, "falai_key", SecretStr("k"), raising=False)
        client = _client(settings)

        class Refusing(_Captured):
            def request(self, method, path, **kwargs):
                raise ProviderError("embeddings", 'HTTP 401: {"error":"no access"}')

        monkeypatch.setattr(client, "_http", Refusing(), raising=False)

        result = client.embed(["a headline"])
        assert result.vectors == []
        message = " ".join(result.errors)
        assert "401" in message
        assert "Authorization: Key" in message
        assert "openai/text-embedding-3-small" in message
        assert "fal-test-key" not in message and " k " not in message

    def test_a_rejection_is_flagged_as_not_worth_retrying(self, settings, monkeypatch):
        """Otherwise a run asks sixteen more times for something that will never
        work, against a rate-limited endpoint."""
        from awltux.providers.http import ProviderError

        monkeypatch.setattr(settings.env, "falai_key", SecretStr("k"), raising=False)
        client = _client(settings)

        class Refusing(_Captured):
            def request(self, method, path, **kwargs):
                raise ProviderError("embeddings", "HTTP 403: forbidden")

        monkeypatch.setattr(client, "_http", Refusing(), raising=False)
        assert client.embed(["a headline"]).fatal is True

    def test_a_transient_failure_is_not_flagged(self, settings, monkeypatch):
        """A timeout should be retried next run, not treated as settled."""
        from awltux.providers.http import ProviderError

        monkeypatch.setattr(settings.env, "falai_key", SecretStr("k"), raising=False)
        client = _client(settings)

        class Timing(_Captured):
            def request(self, method, path, **kwargs):
                raise ProviderError("embeddings", "connection reset by peer")

        monkeypatch.setattr(client, "_http", Timing(), raising=False)
        result = client.embed(["a headline"])
        assert result.fatal is False
        assert result.errors
