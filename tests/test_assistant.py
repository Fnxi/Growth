from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.assistant.context import ContextBuilder
from app.assistant.limits import AssistantRequestLimiter
from app.assistant.providers import AssistantProviderError, OpenAIResponsesProvider, ProviderResult
from app.assistant.service import AssistantService
from app.schemas import AssistantChatRequest


class FakeProvider:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content or '{"answer":"Observed data only.","observed_facts":["System is healthy."],"interpretations":[],"recommendations":[],"insufficient_information":[],"references":["invented:reference"]}'
        self.error = error
        self.calls = []

    def respond(self, instructions: str, input_text: str, max_output_tokens: int) -> ProviderResult:
        self.calls.append((instructions, input_text, max_output_tokens))
        if self.error:
            raise self.error
        return ProviderResult(content=self.content, input_tokens=10, output_tokens=5)


def settings(**overrides):
    values = {
        "ai_enabled": True,
        "ai_provider": "openai",
        "ai_openai_api_key": "test-key",
        "ai_model": "test-model",
        "ai_timeout_seconds": 1,
        "ai_max_output_tokens": 200,
        "ai_max_context_characters": 1000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_assistant_disabled_and_unconfigured_statuses() -> None:
    assert AssistantService(settings(ai_enabled=False)).status().status == "disabled"
    assert AssistantService(settings(ai_openai_api_key=None)).status().status == "not_configured"


def test_assistant_returns_valid_structured_response_without_writes() -> None:
    provider = FakeProvider()
    service = AssistantService(settings(), provider)
    session = SimpleNamespace(new=set())
    response = service.chat(session, uuid4(), AssistantChatRequest(question="Status?"))
    assert not session.new
    assert response.answer == "Observed data only."
    assert "invented:reference" not in response.references
    assert provider.calls
    assert "test-key" not in provider.calls[0][1]


def test_assistant_rejects_provider_failures_and_invalid_responses() -> None:
    session = SimpleNamespace()
    for provider in (FakeProvider(error=AssistantProviderError("timeout")), FakeProvider(content="not json")):
        try:
            AssistantService(settings(), provider).chat(session, uuid4(), AssistantChatRequest(question="Status?"))
        except AssistantProviderError:
            pass
        else:
            raise AssertionError("Provider failure should be controlled")


def test_openai_provider_uses_store_false_and_hides_authentication_error(monkeypatch) -> None:
    captured = {}
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")

    def response(*_args, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, request=request, json={"output_text": FakeProvider().content, "usage": {"input_tokens": 1, "output_tokens": 2}})

    monkeypatch.setattr("app.assistant.providers.httpx.post", response)
    result = OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert result.input_tokens == 1
    assert captured["json"]["store"] is False
    assert captured["timeout"] == 1

    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(401, request=request))
    try:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    except AssistantProviderError as error:
        assert error.code == "authentication_failed"
        assert "secret-key" not in str(error)
    else:
        raise AssertionError("Authentication failure should be controlled")


@pytest.mark.parametrize(("status_code", "expected_code"), [(403, "authentication_failed"), (429, "rate_limited")])
def test_openai_provider_classifies_provider_http_errors(monkeypatch, status_code: int, expected_code: str) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(status_code, request=request))
    with pytest.raises(AssistantProviderError, match=expected_code) as error:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert error.value.code == expected_code


@pytest.mark.parametrize(("failure", "expected_code"), [(httpx.TimeoutException("timeout"), "timeout"), (httpx.ConnectError("offline"), "connection_failed")])
def test_openai_provider_classifies_transport_errors(monkeypatch, failure: Exception, expected_code: str) -> None:
    def raise_error(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("app.assistant.providers.httpx.post", raise_error)
    with pytest.raises(AssistantProviderError, match=expected_code) as error:
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)
    assert error.value.code == expected_code


def test_openai_provider_rejects_malformed_response(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    monkeypatch.setattr("app.assistant.providers.httpx.post", lambda *_args, **_kwargs: httpx.Response(200, request=request, json=["unexpected"]))
    with pytest.raises(AssistantProviderError, match="invalid_response"):
        OpenAIResponsesProvider("secret-key", "test-model", 1).respond("instructions", "input", 100)


def test_assistant_limiter_enforces_rate_and_concurrency() -> None:
    limiter = AssistantRequestLimiter(limit=1, window_seconds=60, max_concurrent=1)
    assert limiter.acquire("client").allowed
    assert not limiter.acquire("other-client").allowed
    limiter.release()
    limited = limiter.acquire("client")
    assert not limited.allowed
    assert limited.retry_after


def test_assistant_errors_do_not_log_secret(caplog) -> None:
    provider = FakeProvider(error=AssistantProviderError("authentication_failed"))
    try:
        AssistantService(settings(ai_openai_api_key="secret-key"), provider).chat(SimpleNamespace(), uuid4(), AssistantChatRequest(question="Status?"))
    except AssistantProviderError:
        pass
    assert "secret-key" not in caplog.text


def test_context_is_bounded_and_does_not_include_link_destinations() -> None:
    class EmptyResult:
        def all(self):
            return []

    class EmptySession:
        def scalars(self, _statement):
            return []

        def execute(self, _statement):
            return EmptyResult()

    context, _ = ContextBuilder(200).build(EmptySession(), uuid4(), "tracking metrics")
    assert len(context) <= 200
    assert "destination_url" not in context


def test_assistant_keeps_only_context_references(monkeypatch) -> None:
    class FixedContextBuilder:
        def __init__(self, _max_characters):
            pass

        def build(self, _session, _organization_id, _question):
            return "{}", ["campaign:valid"]

    provider = FakeProvider(content='{"answer":"Observed.","observed_facts":[],"interpretations":[],"recommendations":[],"insufficient_information":[],"references":["campaign:valid","campaign:invented","event:arbitrary"]}')
    monkeypatch.setattr("app.assistant.service.ContextBuilder", FixedContextBuilder)
    response = AssistantService(settings(), provider).chat(None, uuid4(), AssistantChatRequest(question="Explain campaigns"))
    assert response.references == ["campaign:valid"]
